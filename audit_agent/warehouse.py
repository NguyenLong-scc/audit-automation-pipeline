from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AuditReport, CriticAssessment, WarehouseClassification
from .pipeline_validation import validate_for_warehouse


DEFAULT_DB_PATH = Path("data/learning_warehouse.sqlite3")


def _connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or os.getenv("WAREHOUSE_DB_PATH", DEFAULT_DB_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise_warehouse(db_path: str | Path | None = None) -> None:
    with _connection(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS approved_reports (
                report_id TEXT PRIMARY KEY,
                engagement_id TEXT NOT NULL,
                client_name TEXT NOT NULL,
                report_type TEXT NOT NULL,
                period_end TEXT,
                industry TEXT NOT NULL,
                audit_area TEXT NOT NULL,
                jurisdiction TEXT NOT NULL,
                confidentiality TEXT NOT NULL,
                learning_eligibility TEXT NOT NULL,
                anonymized INTEGER NOT NULL,
                approved_by TEXT NOT NULL,
                approved_at TEXT NOT NULL,
                generator_mode TEXT NOT NULL,
                generator_model TEXT,
                critic_model TEXT,
                critic_score INTEGER NOT NULL,
                revision_cycles INTEGER NOT NULL,
                final_report_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approved_findings (
                finding_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                finding_number INTEGER NOT NULL,
                area TEXT NOT NULL,
                risk_rating TEXT NOT NULL,
                title TEXT NOT NULL,
                condition_text TEXT NOT NULL,
                criteria_text TEXT NOT NULL,
                cause_text TEXT NOT NULL,
                effect_text TEXT NOT NULL,
                recommendation_text TEXT NOT NULL,
                management_response TEXT NOT NULL,
                evidence_reference TEXT NOT NULL,
                FOREIGN KEY (report_id) REFERENCES approved_reports(report_id)
            );
            """
        )


def transfer_approved_report(
    payload: dict[str, Any],
    report: AuditReport,
    critic: CriticAssessment,
    classification: WarehouseClassification,
    *,
    approved_by: str,
    human_approved: bool,
    generator_mode: str,
    revision_cycles: int = 0,
    db_path: str | Path | None = None,
) -> str:
    """Transfer only explicitly human-approved reports into the warehouse."""

    validation = validate_for_warehouse(
        report,
        critic,
        classification,
        client_release_approved=human_approved,
        approved_by=approved_by,
    )
    if not validation.valid:
        details = "; ".join(
            f"{failure.rule_code}: {failure.detail}" for failure in validation.failures
        )
        raise ValueError(f"Warehouse validation failed: {details}")

    initialise_warehouse(db_path)
    report_id = f"RPT-{uuid.uuid4().hex[:12].upper()}"
    engagement_id = str(payload.get("engagement_id") or f"ENG-{uuid.uuid4().hex[:10].upper()}")
    approved_at = datetime.now(timezone.utc).isoformat()

    with _connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO approved_reports (
                report_id, engagement_id, client_name, report_type, period_end,
                industry, audit_area, jurisdiction, confidentiality,
                learning_eligibility, anonymized, approved_by, approved_at,
                generator_mode, generator_model, critic_model, critic_score,
                revision_cycles, final_report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                engagement_id,
                str(payload.get("client_name") or "Not provided"),
                str(payload.get("report_type") or "Not provided"),
                str(payload.get("period_end") or "Not provided"),
                classification.industry,
                classification.audit_area,
                classification.jurisdiction,
                classification.confidentiality,
                classification.learning_eligibility,
                int(classification.anonymized),
                approved_by.strip(),
                approved_at,
                generator_mode,
                os.getenv("OPENAI_MODEL") if generator_mode == "OpenAI API" else "demo-generator-v1",
                os.getenv("OPENAI_CRITIC_MODEL") if generator_mode == "OpenAI API" else "demo-critic-v1",
                critic.overall_score,
                revision_cycles,
                json.dumps(report.model_dump(), ensure_ascii=False),
            ),
        )
        connection.executemany(
            """
            INSERT INTO approved_findings (
                finding_id, report_id, finding_number, area, risk_rating, title,
                condition_text, criteria_text, cause_text, effect_text,
                recommendation_text, management_response, evidence_reference
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"FND-{uuid.uuid4().hex[:12].upper()}",
                    report_id,
                    number,
                    finding.area,
                    finding.risk_rating,
                    finding.title,
                    finding.condition,
                    finding.criteria,
                    finding.cause,
                    finding.effect,
                    finding.recommendation,
                    finding.management_response,
                    finding.evidence_reference,
                )
                for number, finding in enumerate(report.findings, start=1)
            ],
        )
    return report_id


def list_approved_reports(
    db_path: str | Path | None = None, *, limit: int = 50
) -> list[dict[str, Any]]:
    initialise_warehouse(db_path)
    with _connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT report_id, client_name, report_type, industry, audit_area,
                   confidentiality, learning_eligibility, anonymized,
                   approved_by, approved_at, critic_score
            FROM approved_reports
            ORDER BY approved_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
