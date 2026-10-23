from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import AuditReport, CriticAssessment


PASSING_SCORE = 85
MAX_REVISION_CYCLES = 3


@dataclass(frozen=True)
class AutomationRound:
    round_number: int
    score: int
    status: str
    issue_count: int
    summary: str


@dataclass(frozen=True)
class AutomationResult:
    report: AuditReport
    assessment: CriticAssessment
    revision_cycles: int
    stop_reason: str
    history: list[AutomationRound]

    @property
    def passed(self) -> bool:
        return (
            self.assessment.status == "pass"
            and self.assessment.overall_score >= PASSING_SCORE
            and not any(issue.severity == "blocker" for issue in self.assessment.issues)
        )


def run_automation_loop(
    initial_report: AuditReport,
    grade: Callable[[AuditReport], CriticAssessment],
    revise: Callable[[AuditReport, CriticAssessment], AuditReport],
    *,
    max_revision_cycles: int = MAX_REVISION_CYCLES,
    passing_score: int = PASSING_SCORE,
) -> AutomationResult:
    """Grade and revise a draft until it passes or reaches a safe stop condition."""

    if max_revision_cycles < 0:
        raise ValueError("max_revision_cycles cannot be negative.")
    if not 0 <= passing_score <= 100:
        raise ValueError("passing_score must be between 0 and 100.")

    report = initial_report
    history: list[AutomationRound] = []
    revision_cycles = 0

    while True:
        assessment = grade(report)
        blockers = [issue for issue in assessment.issues if issue.severity == "blocker"]
        passed = (
            assessment.status == "pass"
            and assessment.overall_score >= passing_score
            and not blockers
        )
        history.append(
            AutomationRound(
                round_number=len(history) + 1,
                score=assessment.overall_score,
                status="pass" if passed else "revision_required",
                issue_count=len(assessment.issues),
                summary=assessment.summary,
            )
        )

        if passed:
            return AutomationResult(
                report, assessment, revision_cycles, "passed", history
            )
        if blockers:
            return AutomationResult(
                report, assessment, revision_cycles, "evidence_blocker", history
            )
        if revision_cycles >= max_revision_cycles:
            return AutomationResult(
                report, assessment, revision_cycles, "revision_limit", history
            )

        report = revise(report, assessment)
        revision_cycles += 1
