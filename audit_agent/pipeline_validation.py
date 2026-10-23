from __future__ import annotations

from dataclasses import dataclass

from .models import AuditReport, CriticAssessment, WarehouseClassification


@dataclass(frozen=True)
class ValidationFailure:
    rule_code: str
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    failures: list[ValidationFailure]

    @property
    def valid(self) -> bool:
        return not self.failures


def validate_for_warehouse(
    report: AuditReport,
    critic: CriticAssessment,
    classification: WarehouseClassification,
    *,
    client_release_approved: bool,
    approved_by: str,
) -> ValidationResult:
    failures: list[ValidationFailure] = []
    if not client_release_approved:
        failures.append(ValidationFailure("APPROVAL_REQUIRED", "Client-release approval is missing."))
    if not approved_by.strip():
        failures.append(ValidationFailure("APPROVER_REQUIRED", "An authorised approver is required."))
    if critic.status != "pass" or critic.overall_score < 85:
        failures.append(ValidationFailure("CRITIC_GATE_FAILED", "The critic must pass with at least 85/100."))
    if any(issue.severity == "blocker" for issue in critic.issues):
        failures.append(ValidationFailure("CRITIC_BLOCKER", "The report contains an unresolved blocker."))
    for number, finding in enumerate(report.findings, start=1):
        if not finding.evidence_reference.strip() or finding.evidence_reference == "Not provided":
            failures.append(
                ValidationFailure("EVIDENCE_REQUIRED", f"Finding {number} has no evidence reference.")
            )
    if classification.learning_eligibility == "training_approved" and not classification.anonymized:
        failures.append(
            ValidationFailure("ANONYMIZATION_REQUIRED", "Training-approved data must be anonymized.")
        )
    return ValidationResult(failures)
