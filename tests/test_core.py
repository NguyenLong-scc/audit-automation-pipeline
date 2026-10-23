from __future__ import annotations

from io import BytesIO

import json
import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from audit_agent.config import REPORT_TEMPLATES
from audit_agent.critic import build_demo_assessment
from audit_agent.export import build_docx
from audit_agent.generator import build_demo_report, get_openai_reasoning_effort
from audit_agent.models import WarehouseClassification
from audit_agent.qa import completeness_score, run_qa
from audit_agent.warehouse import list_approved_reports, transfer_approved_report
from audit_agent.automation import run_automation_loop
from audit_agent.identifiers import report_code, version_code
from audit_agent.pipeline_validation import validate_for_warehouse
from audit_agent.ingestion_gateway import (
    approve_gateway_use,
    build_dataset_export,
    get_gateway_upload,
    list_gateway_uploads,
    preview_report_upload,
    stage_report_upload,
    validate_report_upload,
)
from audit_agent.learning_loop import assess_learning_readiness
from audit_agent.demo_learning_data import seed_demo_learning_data
from audit_agent.github_agent import (
    build_demo_plan,
    parse_github_repository_url,
    run_practice_agent,
)


def sample_payload() -> tuple[dict, list[dict]]:
    template = REPORT_TEMPLATES["Site Security Assessment"]
    demo = template["demo"]
    payload = {
        "report_type": "Site Security Assessment",
        **{key: value for key, value in demo.items() if key != "findings"},
    }
    return payload, demo["findings"]


def test_demo_report_is_structured_and_evidence_linked() -> None:
    payload, findings = sample_payload()
    report = build_demo_report(payload, findings)

    assert payload["client_name"] in report.report_title
    assert len(report.findings) == 1
    assert report.findings[0].risk_rating == "High"
    assert report.findings[0].evidence_reference != "Not provided"


def test_openai_reasoning_defaults_to_medium(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    assert get_openai_reasoning_effort() == "medium"


def test_openai_reasoning_rejects_unsupported_effort(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "ultra")

    with pytest.raises(RuntimeError, match="OPENAI_REASONING_EFFORT"):
        get_openai_reasoning_effort()


def test_github_repository_url_is_validated() -> None:
    assert parse_github_repository_url("https://github.com/sonbkt303/ai-orchestrator") == (
        "sonbkt303",
        "ai-orchestrator",
    )
    with pytest.raises(ValueError):
        parse_github_repository_url("https://example.com/sonbkt303/ai-orchestrator")


def test_github_practice_agent_is_read_only_and_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(
        "audit_agent.github_agent.fetch_repository_snapshot",
        lambda *args, **kwargs: None,
    )
    result = run_practice_agent(
        "https://github.com/sonbkt303/ai-orchestrator",
        "Explain the request lifecycle",
    )

    assert result.mode == "Presentation demo"
    assert result.plan["files_to_inspect"][:2] == ["readme.md", "package.json"]
    assert any("No commits" in guardrail for guardrail in result.plan["guardrails"])
    assert build_demo_plan(result.repository_url, result.task)["summary"].startswith(
        "Practice analysis"
    )


def test_qa_passes_complete_demo_and_requires_human_review() -> None:
    payload, findings = sample_payload()
    report = build_demo_report(payload, findings)
    checks = run_qa(payload, report)

    assert not [item for item in checks if item.level == "blocker"]
    assert any(item.title == "Professional review is required" for item in checks)
    assert 70 <= completeness_score(checks) <= 100


def test_qa_blocks_missing_evidence() -> None:
    payload, findings = sample_payload()
    findings = [{**findings[0], "evidence_reference": "Not provided"}]
    report = build_demo_report(payload, findings)
    checks = run_qa(payload, report)

    assert any(
        item.level == "blocker" and "evidence" in item.title.lower()
        for item in checks
    )


def test_word_export_opens_and_contains_draft_marker() -> None:
    payload, findings = sample_payload()
    report = build_demo_report(payload, findings)
    content = build_docx(report, payload)
    document = Document(BytesIO(content))
    paragraphs = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert content.startswith(b"PK")
    assert "DRAFT" in paragraphs
    assert report.report_title in paragraphs


def test_critic_passes_complete_approved_example() -> None:
    payload, findings = sample_payload()
    report = build_demo_report(payload, findings)
    critic = build_demo_assessment(payload, report)

    assert critic.status == "pass"
    assert critic.overall_score >= 80
    assert critic.factual_evidence_score >= 80


def test_critic_requires_revision_when_evidence_is_missing() -> None:
    payload, findings = sample_payload()
    findings = [{**findings[0], "evidence_reference": "Not provided"}]
    report = build_demo_report(payload, findings)
    critic = build_demo_assessment(payload, report)

    assert critic.status == "revision_required"
    assert any(issue.severity == "blocker" for issue in critic.issues)


def test_only_human_approved_report_enters_warehouse(tmp_path) -> None:
    payload, findings = sample_payload()
    report = build_demo_report(payload, findings)
    critic = build_demo_assessment(payload, report)
    classification = WarehouseClassification(
        industry="Manufacturing",
        audit_area="Internal controls",
        jurisdiction="Vietnam",
        confidentiality="Confidential",
        learning_eligibility="retrieval_only",
        anonymized=False,
    )
    db_path = tmp_path / "warehouse.sqlite3"

    report_id = transfer_approved_report(
        payload,
        report,
        critic,
        classification,
        approved_by="A. Reviewer",
        human_approved=True,
        generator_mode="Presentation demo",
        db_path=db_path,
    )
    rows = list_approved_reports(db_path)

    assert rows[0]["report_id"] == report_id
    assert rows[0]["learning_eligibility"] == "retrieval_only"


def test_automation_passes_complete_report_without_revision() -> None:
    payload, findings = sample_payload()
    report = build_demo_report(payload, findings)
    result = run_automation_loop(
        report,
        lambda draft: build_demo_assessment(payload, draft),
        lambda draft, _assessment: draft,
    )

    assert result.passed
    assert result.revision_cycles == 0
    assert result.stop_reason == "passed"


def test_automation_stops_immediately_for_evidence_blocker() -> None:
    payload, findings = sample_payload()
    findings = [{**findings[0], "evidence_reference": "Not provided"}]
    report = build_demo_report(payload, findings)
    revision_calls = 0

    def revise(draft, _assessment):
        nonlocal revision_calls
        revision_calls += 1
        return draft

    result = run_automation_loop(
        report, lambda draft: build_demo_assessment(payload, draft), revise
    )

    assert result.stop_reason == "evidence_blocker"
    assert revision_calls == 0


def test_human_readable_identifiers_are_stable() -> None:
    assert report_code(42, year=2026) == "RPT-2026-000042"
    assert version_code("RPT-2026-000042", 3) == "RPT-2026-000042-V03"


def test_pipeline_validation_separates_release_and_training_approval() -> None:
    payload, findings = sample_payload()
    report = build_demo_report(payload, findings)
    critic = build_demo_assessment(payload, report)
    classification = WarehouseClassification(
        industry="Financial services",
        audit_area="Internal controls",
        jurisdiction="Vietnam",
        confidentiality="Confidential",
        learning_eligibility="training_approved",
        anonymized=False,
    )

    result = validate_for_warehouse(
        report,
        critic,
        classification,
        client_release_approved=True,
        approved_by="A. Reviewer",
    )

    assert not result.valid
    assert any(item.rule_code == "ANONYMIZATION_REQUIRED" for item in result.failures)


def gateway_report_text() -> bytes:
    return (
        "APPROVED INTERNAL CONTROL REPORT\n"
        "Objective: assess purchasing controls for the reporting period.\n"
        "Scope: vendor onboarding, purchase approval, and payment processing.\n"
        "Conclusion: controls were generally effective except for the documented finding.\n"
        "Finding: one vendor change lacked independent electronic approval evidence.\n"
        "Recommendation: require workflow approval and retain the approval record."
    ).encode("utf-8")


def gateway_report_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 72 720 Td "
        b"(APPROVED INTERNAL CONTROL REPORT. Objective: assess purchasing controls. "
        b"Conclusion: controls were generally effective with documented recommendations.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_gateway_quarantines_disallowed_file_type() -> None:
    validation = validate_report_upload("approved-report.xlsx", gateway_report_text())

    assert not validation.valid
    assert any(message.rule_code == "FILE_TYPE_NOT_ALLOWED" for message in validation.messages)


def test_gateway_extracts_embedded_text_from_digital_pdf() -> None:
    validation = validate_report_upload("approved-report.pdf", gateway_report_pdf())

    assert validation.valid
    assert "APPROVED INTERNAL CONTROL REPORT" in validation.extracted_text


def test_gateway_preview_extracts_without_staging_source(tmp_path) -> None:
    preview = preview_report_upload("approved-report.txt", gateway_report_text(), preview_limit=60)

    assert preview.validation.valid
    assert preview.character_count > 80
    assert preview.word_count > 10
    assert len(preview.preview) == 60
    assert list_gateway_uploads(tmp_path / "gateway.sqlite3") == []


def test_gateway_stages_and_lists_validated_report(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    receipt = stage_report_upload(
        "approved-report.txt",
        gateway_report_text(),
        media_type="text/plain",
        report_type="Site Security Assessment",
        training_input="Prepare an internal control report from the supplied engagement facts.",
        uploaded_by="Developer One",
        upload_authorized=True,
        db_path=db_path,
    )

    assert receipt.status == "VALIDATED"
    rows = list_gateway_uploads(db_path)
    detail = get_gateway_upload(receipt.upload_id, db_path)
    assert rows[0]["upload_id"] == receipt.upload_id
    assert detail is not None
    assert detail["extracted_characters"] > 80


def test_gateway_requires_anonymization_before_training_approval(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    receipt = stage_report_upload(
        "approved-report.txt",
        gateway_report_text(),
        media_type="text/plain",
        report_type="Site Security Assessment",
        training_input="Prepare an internal control report from the supplied engagement facts.",
        uploaded_by="Developer One",
        upload_authorized=True,
        db_path=db_path,
    )

    with pytest.raises(ValueError, match="anonymized"):
        approve_gateway_use(
            receipt.upload_id,
            "TRAINING",
            approved_by="AI Governance Reviewer",
            anonymized=False,
            authority_confirmed=True,
            db_path=db_path,
        )


def test_gateway_builds_chat_jsonl_preview_from_training_approval(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    receipt = stage_report_upload(
        "approved-report.txt",
        gateway_report_text(),
        media_type="text/plain",
        report_type="Site Security Assessment",
        training_input="Prepare an internal control report from the supplied engagement facts.",
        uploaded_by="Developer One",
        upload_authorized=True,
        db_path=db_path,
    )
    approve_gateway_use(
        receipt.upload_id,
        "TRAINING",
        approved_by="AI Governance Reviewer",
        anonymized=True,
        authority_confirmed=True,
        db_path=db_path,
    )

    dataset = build_dataset_export(
        "TRAINING", created_by="Developer One", db_path=db_path
    )
    record = json.loads(dataset.content.decode("utf-8").strip())

    assert dataset.status == "PREVIEW_ONLY"
    assert dataset.item_count == 1
    assert set(record) == {"messages"}
    assert record["messages"][0]["role"] == "user"
    assert record["messages"][1]["role"] == "assistant"
    detail = get_gateway_upload(receipt.upload_id, db_path)
    assert detail is not None
    assert detail["anonymized"] == 1


def test_learning_readiness_requires_retrieval_then_evaluation_then_training(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    receipt = stage_report_upload(
        "approved-report.txt",
        gateway_report_text(),
        media_type="text/plain",
        report_type="Site Security Assessment",
        training_input="Prepare an internal control report from the supplied engagement facts.",
        uploaded_by="Developer One",
        upload_authorized=True,
        db_path=db_path,
    )

    initial = assess_learning_readiness(db_path)
    assert initial.validated_documents == 1
    assert initial.retrieval_documents == 0
    assert "retrieval" in initial.next_action.lower()

    approve_gateway_use(
        receipt.upload_id, "RETRIEVAL", approved_by="Reviewer", anonymized=False,
        authority_confirmed=True, db_path=db_path,
    )
    retrieval_ready = assess_learning_readiness(db_path)
    assert retrieval_ready.retrieval_documents == 1
    assert "evaluation" in retrieval_ready.next_action.lower()

    approve_gateway_use(
        receipt.upload_id, "EVALUATION", approved_by="Reviewer", anonymized=False,
        authority_confirmed=True, db_path=db_path,
    )
    evaluation_ready = assess_learning_readiness(db_path)
    assert evaluation_ready.evaluation_examples == 1
    assert not evaluation_ready.training_ready
    assert "more anonymized" in evaluation_ready.next_action.lower()


def test_demo_seed_creates_separate_retrieval_and_evaluation_examples(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"

    created, already_present = seed_demo_learning_data(db_path)
    readiness = assess_learning_readiness(db_path)

    assert (created, already_present) == (10, 0)
    assert readiness.retrieval_documents == 5
    assert readiness.evaluation_examples == 5
    assert readiness.training_examples == 0
