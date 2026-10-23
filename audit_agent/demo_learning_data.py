"""Fictional data for demonstrating the governed learning loop locally."""

from __future__ import annotations

from pathlib import Path

from .ingestion_gateway import approve_gateway_use, stage_report_upload


DEMO_TOPICS = (
    ("Vendor onboarding", "vendor master-file change did not retain independent approval"),
    ("Purchase approvals", "a purchase order exceeded its delegated approval limit"),
    ("Payment processing", "a payment batch was released without a second reviewer"),
    ("Inventory counts", "a cycle-count variance was not investigated within the policy window"),
    ("User access", "a terminated user retained procurement-system access"),
    ("Expense claims", "an expense claim lacked the required receipt"),
    ("Revenue recognition", "a contract modification was not documented before revenue posting"),
    ("Bank reconciliations", "an aged reconciling item did not have documented follow-up"),
    ("Fixed assets", "an asset disposal was processed without an approved disposal form"),
    ("Payroll changes", "a salary change lacked maker-checker evidence"),
)


def _report_text(number: int, area: str, finding: str) -> bytes:
    return (
        f"FICTIONAL ANONYMIZED AUDIT EXAMPLE {number:02d}\n\n"
        f"Objective: Assess {area.lower()} controls for a fictional entity.\n"
        f"Scope: {area}, approvals, and evidence retention.\n"
        "Conclusion: Controls require the documented remediation below.\n"
        f"Finding: {finding}.\n"
        "Risk: Moderate.\n"
        "Recommendation: Assign a control owner, retain approval evidence, and review exceptions monthly.\n"
        "Evidence reference: FICTIONAL-WP-01.\n"
    ).encode("utf-8")


def seed_demo_learning_data(db_path: str | Path | None = None) -> tuple[int, int]:
    """Stage and approve ten synthetic examples; returns (created, already_present)."""
    created = 0
    already_present = 0
    for number, (area, finding) in enumerate(DEMO_TOPICS, start=1):
        try:
            receipt = stage_report_upload(
                f"fictional-anonymized-example-{number:02d}.txt",
                _report_text(number, area, finding),
                media_type="text/plain",
                report_type="Internal Controls Review",
                training_input=(
                    f"Prepare a concise internal-controls finding for {area.lower()} "
                    "using the supplied fictional engagement facts."
                ),
                uploaded_by="Demo seed",
                upload_authorized=True,
                db_path=db_path,
            )
        except ValueError as exc:
            if "already been staged" not in str(exc):
                raise
            already_present += 1
            continue

        use_type = "RETRIEVAL" if number <= 5 else "EVALUATION"
        approve_gateway_use(
            receipt.upload_id,
            use_type,
            approved_by="Demo governance reviewer",
            anonymized=True,
            authority_confirmed=True,
            notes="Fictional, anonymized example for local demonstration only.",
            db_path=db_path,
        )
        created += 1
    return created, already_present
