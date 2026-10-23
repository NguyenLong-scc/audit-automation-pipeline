from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskRating = Literal["Low", "Moderate", "High", "Critical"]


class Finding(BaseModel):
    """A single report finding with an evidence trail."""

    title: str = Field(description="Short, factual finding title")
    area: str = Field(description="Process or account area affected")
    risk_rating: RiskRating
    condition: str = Field(description="What was observed")
    criteria: str = Field(description="Expected policy, control, or requirement")
    cause: str = Field(description="Likely cause, or 'Not established'")
    effect: str = Field(description="Actual or potential consequence")
    recommendation: str = Field(description="Specific and implementable action")
    management_response: str = Field(default="Not provided")
    evidence_reference: str = Field(
        default="Not provided",
        description="Reference to entered or uploaded supporting evidence",
    )


class AuditReport(BaseModel):
    """Structured report returned by demo generation or the OpenAI API."""

    report_title: str
    executive_summary: str
    objective: str
    scope: str
    methodology: str
    conclusion: str
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reviewer_notes: list[str] = Field(default_factory=list)


class CriticIssue(BaseModel):
    severity: Literal["warning", "blocker"]
    category: Literal[
        "factual_evidence",
        "methodology_compliance",
        "completeness",
        "writing_style",
        "internal_consistency",
    ]
    title: str
    detail: str
    revision_instruction: str


class CriticAssessment(BaseModel):
    """Independent grading result for a generator-produced report."""

    factual_evidence_score: int = Field(ge=0, le=100)
    methodology_compliance_score: int = Field(ge=0, le=100)
    completeness_score: int = Field(ge=0, le=100)
    writing_style_score: int = Field(ge=0, le=100)
    internal_consistency_score: int = Field(ge=0, le=100)
    overall_score: int = Field(ge=0, le=100)
    status: Literal["pass", "revision_required"]
    summary: str
    issues: list[CriticIssue] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)


class WarehouseClassification(BaseModel):
    industry: str
    audit_area: str
    jurisdiction: str
    confidentiality: Literal["Internal", "Confidential", "Highly confidential"]
    learning_eligibility: Literal[
        "prohibited", "retrieval_only", "evaluation_only", "training_approved"
    ]
    anonymized: bool = False
