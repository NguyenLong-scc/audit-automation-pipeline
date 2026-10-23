from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .config import get_template
from .models import AuditReport


QALevel = Literal["pass", "warning", "blocker"]


@dataclass(frozen=True)
class QACheck:
    level: QALevel
    title: str
    detail: str


def run_qa(payload: dict[str, Any], report: AuditReport) -> list[QACheck]:
    """Run transparent deterministic checks alongside model generation."""

    template = get_template(str(payload.get("report_type")))
    checks: list[QACheck] = []

    missing = [
        field
        for field in template["required_fields"]
        if not str(payload.get(field) or "").strip()
    ]
    if missing:
        checks.append(
            QACheck(
                "blocker",
                "Required engagement data is missing",
                ", ".join(field.replace("_", " ").title() for field in missing),
            )
        )
    else:
        checks.append(
            QACheck(
                "pass",
                "Required engagement data is complete",
                "All mandatory preparation fields contain a value.",
            )
        )

    unsupported = [
        finding.title
        for finding in report.findings
        if finding.evidence_reference.strip().lower()
        in {"", "not provided", "chưa cung cấp", "n/a", "không áp dụng"}
    ]
    if unsupported:
        checks.append(
            QACheck(
                "blocker",
                "Finding evidence references are missing",
                "; ".join(unsupported),
            )
        )
    elif report.findings:
        checks.append(
            QACheck(
                "pass",
                "Findings contain evidence references",
                "Each entered finding points to supporting evidence for reviewer confirmation.",
            )
        )
    else:
        checks.append(
            QACheck(
                "warning",
                "No findings were entered",
                "Confirm that a no-findings report is appropriate for this engagement.",
            )
        )

    high_risk_gaps = [
        finding.title
        for finding in report.findings
        if finding.risk_rating in {"High", "Critical"}
        and (
            finding.effect.strip().lower() in {"", "not provided", "chưa cung cấp"}
            or finding.recommendation.strip().lower()
            in {"", "not provided", "chưa cung cấp"}
        )
    ]
    if high_risk_gaps:
        checks.append(
            QACheck(
                "blocker",
                "High-risk finding is incomplete",
                "; ".join(high_risk_gaps),
            )
        )
    else:
        checks.append(
            QACheck(
                "pass",
                "Risk-response fields are complete",
                "High and critical findings include an effect and recommendation.",
            )
        )

    management_missing = [
        finding.title
        for finding in report.findings
        if finding.management_response.strip().lower()
        in {"", "not provided", "chưa cung cấp"}
    ]
    if management_missing:
        checks.append(
            QACheck(
                "warning",
                "Management response remains outstanding",
                "; ".join(management_missing),
            )
        )

    checks.append(
        QACheck(
            "warning",
            "Professional review is required",
            "Automated checks do not replace the firm's technical, evidence, and engagement-quality review.",
        )
    )
    return checks


def completeness_score(checks: list[QACheck]) -> int:
    if not checks:
        return 0
    weights = {"pass": 1.0, "warning": 0.65, "blocker": 0.0}
    return round(sum(weights[item.level] for item in checks) / len(checks) * 100)
