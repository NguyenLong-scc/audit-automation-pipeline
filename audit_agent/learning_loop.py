"""Read-only operational signals for the governed learning loop.

This module intentionally never changes model weights, sends documents to a
provider, or grants approval.  It summarizes the approved gateway state so a
human can decide the next safe improvement action.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ingestion_gateway import MIN_FINE_TUNING_EXAMPLES, list_gateway_uploads


@dataclass(frozen=True)
class LearningReadiness:
    validated_documents: int
    retrieval_documents: int
    evaluation_examples: int
    training_examples: int
    anonymized_training_examples: int
    training_ready: bool
    next_action: str


def _approved_uses(row: dict[str, object]) -> set[str]:
    return {
        value.strip()
        for value in str(row.get("approved_uses", "")).split(",")
        if value.strip()
    }


def assess_learning_readiness(
    db_path: str | Path | None = None,
) -> LearningReadiness:
    """Summarize approved learning assets without exposing document contents."""
    rows = list_gateway_uploads(db_path, limit=10_000)
    validated = [row for row in rows if row["validation_status"] == "VALIDATED"]
    retrieval = [row for row in validated if "RETRIEVAL" in _approved_uses(row)]
    evaluation = [row for row in validated if "EVALUATION" in _approved_uses(row)]
    training = [row for row in validated if "TRAINING" in _approved_uses(row)]
    anonymized_training = [row for row in training if bool(row["anonymized"])]
    training_ready = len(anonymized_training) >= MIN_FINE_TUNING_EXAMPLES

    if not retrieval:
        next_action = "Approve one validated document for retrieval, then implement cited search."
    elif not evaluation:
        next_action = "Approve reviewed input/output pairs for evaluation before changing prompts or models."
    elif not training_ready:
        remaining = MIN_FINE_TUNING_EXAMPLES - len(anonymized_training)
        next_action = (
            f"Collect {remaining} more anonymized, training-approved examples; "
            "continue improving retrieval and prompts in the meantime."
        )
    else:
        next_action = (
            "Run the evaluation dataset against the current workflow and require human "
            "review before considering a fine-tuning experiment."
        )

    return LearningReadiness(
        validated_documents=len(validated),
        retrieval_documents=len(retrieval),
        evaluation_examples=len(evaluation),
        training_examples=len(training),
        anonymized_training_examples=len(anonymized_training),
        training_ready=training_ready,
        next_action=next_action,
    )
