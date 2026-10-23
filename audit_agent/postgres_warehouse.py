from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import AuditReport, CriticAssessment


REPORT_CATEGORY_CODES = {
    "Site Security Assessment": "COMPLIANCE",
    "Worksite Safety Inspection": "COMPLIANCE",
    "Contractor Access Review": "COMPLIANCE",
}


@dataclass(frozen=True)
class SavedVersion:
    report_id: uuid.UUID
    report_code: str
    report_version_id: uuid.UUID
    version_number: int


def database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql:///audit_warehouse")


def _connect(url: str | None = None):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install psycopg to use the PostgreSQL warehouse.") from exc
    return psycopg.connect(url or database_url())


def _checksum(report: AuditReport) -> str:
    canonical = json.dumps(
        report.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _client_code(client_name: str) -> str:
    digest = hashlib.sha256(client_name.strip().casefold().encode("utf-8")).hexdigest()
    return f"CLI-{digest[:12].upper()}"


def save_generated_version(
    payload: dict[str, Any],
    report: AuditReport,
    critic: CriticAssessment,
    *,
    generated_by: str,
    generator_model: str,
    critic_model: str,
    report_id: uuid.UUID | str | None = None,
    prompt_version: str = "v1",
    url: str | None = None,
) -> SavedVersion:
    """Create a permanent report when needed and append an immutable draft version."""

    client_name = str(payload.get("client_name") or "Chưa cung cấp").strip()
    category_code = REPORT_CATEGORY_CODES.get(
        str(payload.get("report_type")), "COMPLIANCE"
    )
    resolved_report_id = uuid.UUID(str(report_id)) if report_id else uuid.uuid4()
    client_id = uuid.uuid5(uuid.NAMESPACE_URL, f"audit-pipeline-client:{client_name.casefold()}")
    report_version_id = uuid.uuid4()
    generation_run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO core.client (
                    client_id, client_code, legal_name, industry_code, confidentiality_level
                ) VALUES (%s, %s, %s, %s, 'CONFIDENTIAL')
                ON CONFLICT (client_id) DO UPDATE SET legal_name = EXCLUDED.legal_name
                """,
                (client_id, _client_code(client_name), client_name, "UNCLASSIFIED"),
            )
            if report_id is None:
                cursor.execute(
                    """
                    INSERT INTO core.report (
                        report_id, report_code, category_id, client_id, created_by
                    )
                    SELECT %s, core.next_report_code(), category_id, %s, %s
                    FROM core.report_category WHERE category_code = %s
                    RETURNING report_code
                    """,
                    (resolved_report_id, client_id, generated_by, category_code),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError(f"Unknown report category: {category_code}")
                report_label = row[0]
                version_number = 1
            else:
                cursor.execute(
                    "SELECT report_code FROM core.report WHERE report_id = %s FOR UPDATE",
                    (resolved_report_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("The supplied report ID does not exist.")
                report_label = row[0]
                cursor.execute(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 FROM core.report_version WHERE report_id = %s",
                    (resolved_report_id,),
                )
                version_number = cursor.fetchone()[0]

            cursor.execute(
                """
                INSERT INTO core.report_version (
                    report_version_id, report_id, version_number, report_title,
                    structured_report, content_checksum, generator_model,
                    prompt_version, created_by
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                """,
                (
                    report_version_id,
                    resolved_report_id,
                    version_number,
                    report.report_title,
                    json.dumps(report.model_dump(), ensure_ascii=False),
                    _checksum(report),
                    generator_model,
                    prompt_version,
                    generated_by,
                ),
            )
            for number, finding in enumerate(report.findings, start=1):
                cursor.execute(
                    """
                    INSERT INTO core.finding (
                        finding_id, report_version_id, finding_number, title, audit_area,
                        risk_rating, condition_text, criteria_text, cause_text, effect_text,
                        recommendation_text, management_response, evidence_reference
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid.uuid4(), report_version_id, number, finding.title, finding.area,
                        finding.risk_rating.upper(), finding.condition, finding.criteria,
                        finding.cause, finding.effect, finding.recommendation,
                        finding.management_response, finding.evidence_reference,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO core.generation_run (
                    generation_run_id, report_version_id, run_number, generator_model,
                    critic_model, critic_score, critic_status, started_at, completed_at
                ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s)
                """,
                (
                    generation_run_id,
                    report_version_id,
                    generator_model,
                    critic_model,
                    critic.overall_score,
                    "PASS" if critic.status == "pass" else "REVISION_REQUIRED",
                    now,
                    now,
                ),
            )
            cursor.execute(
                "UPDATE core.report SET lifecycle_status = 'IN_REVIEW' WHERE report_id = %s",
                (resolved_report_id,),
            )
            cursor.execute(
                """
                INSERT INTO governance.pipeline_event (
                    report_version_id, event_status, rule_code, detail
                ) VALUES (%s, 'RECEIVED', 'REPORT_VERSION_CREATED', %s)
                """,
                (report_version_id, f"{report_label}-V{version_number:02d}"),
            )
            if critic.status == "pass" and critic.overall_score >= 85:
                cursor.execute(
                    """
                    INSERT INTO governance.pipeline_event (
                        report_version_id, event_status, rule_code, detail
                    ) VALUES (%s, 'VALIDATED', 'AUTOMATED_GATE_PASSED', %s)
                    """,
                    (report_version_id, f"Critic score {critic.overall_score}/100"),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO governance.pipeline_event (
                        report_version_id, event_status, rule_code, detail
                    ) VALUES (%s, 'QUARANTINED', 'AUTOMATED_GATE_FAILED', %s)
                    """,
                    (report_version_id, f"Critic score {critic.overall_score}/100"),
                )
    return SavedVersion(resolved_report_id, report_label, report_version_id, version_number)


def approve_client_release(
    report_version_id: uuid.UUID | str,
    *,
    approved_by: str,
    comment: str | None = None,
    url: str | None = None,
) -> None:
    if not approved_by.strip():
        raise ValueError("An authorised approver is required.")
    version_id = uuid.UUID(str(report_version_id))
    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE core.report_version
                SET version_status = 'CLIENT_APPROVED'
                WHERE report_version_id = %s AND version_status IN ('DRAFT', 'IN_REVIEW')
                RETURNING report_id
                """,
                (version_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("This report version cannot be approved.")
            cursor.execute(
                "UPDATE core.report SET lifecycle_status = 'APPROVED' WHERE report_id = %s",
                (row[0],),
            )
            cursor.execute(
                """
                INSERT INTO core.approval_event (
                    approval_event_id, report_version_id, event_type,
                    actor_id, actor_role, comment_text
                ) VALUES (%s, %s, 'CLIENT_RELEASE_APPROVED', %s, 'AUTHORISED_REVIEWER', %s)
                """,
                (uuid.uuid4(), version_id, approved_by.strip(), comment),
            )
            for use_type in ("RETRIEVAL", "EVALUATION", "TRAINING"):
                cursor.execute(
                    """
                    INSERT INTO governance.learning_decision (
                        learning_decision_id, report_version_id, use_type, decision,
                        anonymized, notes
                    ) VALUES (%s, %s, %s, 'PENDING', false, %s)
                    ON CONFLICT (report_version_id, use_type) DO NOTHING
                    """,
                    (
                        uuid.uuid4(),
                        version_id,
                        use_type,
                        "Developer review required; client approval does not grant AI-use permission.",
                    ),
                )
            cursor.execute(
                """
                INSERT INTO governance.pipeline_event (
                    report_version_id, event_status, rule_code, detail
                ) VALUES (%s, 'LOADED', 'CLIENT_RELEASE_APPROVED', %s)
                """,
                (version_id, approved_by.strip()),
            )


def list_report_versions(*, limit: int = 50, url: str | None = None) -> list[dict[str, Any]]:
    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.report_code, rv.version_number, rv.report_title,
                       rv.version_status, rv.created_by, rv.created_at
                FROM core.report_version rv
                JOIN core.report r ON r.report_id = rv.report_id
                ORDER BY rv.created_at DESC LIMIT %s
                """,
                (limit,),
            )
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
