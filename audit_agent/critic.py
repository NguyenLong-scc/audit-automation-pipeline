from __future__ import annotations

import json
import os
from typing import Any, Iterable

from .generator import InputFile, get_openai_reasoning_effort
from .models import AuditReport, CriticAssessment, CriticIssue
from .qa import run_qa


PASSING_SCORE = 85


def build_demo_assessment(
    payload: dict[str, Any], report: AuditReport
) -> CriticAssessment:
    """Grade a draft transparently when no second model is configured."""

    qa_checks = run_qa(payload, report)
    issues: list[CriticIssue] = []
    for check in qa_checks:
        if check.level == "pass" or check.title == "Professional review is required":
            continue
        category = "completeness"
        lowered = check.title.lower()
        if "evidence" in lowered:
            category = "factual_evidence"
        elif "risk" in lowered:
            category = "methodology_compliance"
        issues.append(
            CriticIssue(
                severity="blocker" if check.level == "blocker" else "warning",
                category=category,
                title=check.title,
                detail=check.detail,
                revision_instruction=(
                    "Bổ sung hoặc sửa thông tin được tham chiếu rồi tạo lại dự thảo."
                    if check.level == "blocker"
                    else "Xác nhận nội dung này trong quá trình soát xét thủ công và cập nhật báo cáo khi cần."
                ),
            )
        )

    evidence_score = 96
    completeness = 96
    methodology = 92
    writing = 91
    consistency = 94
    for issue in issues:
        deduction = 38 if issue.severity == "blocker" else 12
        if issue.category == "factual_evidence":
            evidence_score -= deduction
        elif issue.category == "methodology_compliance":
            methodology -= deduction
        elif issue.category == "writing_style":
            writing -= deduction
        elif issue.category == "internal_consistency":
            consistency -= deduction
        else:
            completeness -= deduction

    category_scores = {
        "factual_evidence": max(0, evidence_score),
        "methodology": max(0, methodology),
        "completeness": max(0, completeness),
        "writing": max(0, writing),
        "consistency": max(0, consistency),
    }
    overall = round(
        category_scores["factual_evidence"] * 0.40
        + category_scores["methodology"] * 0.20
        + category_scores["completeness"] * 0.15
        + category_scores["writing"] * 0.15
        + category_scores["consistency"] * 0.10
    )
    blockers = [issue for issue in issues if issue.severity == "blocker"]
    status = "revision_required" if blockers or overall < PASSING_SCORE else "pass"

    return CriticAssessment(
        factual_evidence_score=category_scores["factual_evidence"],
        methodology_compliance_score=category_scores["methodology"],
        completeness_score=category_scores["completeness"],
        writing_style_score=category_scores["writing"],
        internal_consistency_score=category_scores["consistency"],
        overall_score=overall,
        status=status,
        summary=(
            "Bộ máy chấm điểm độc lập phát hiện nội dung bị chặn cần được chỉnh sửa."
            if status == "revision_required"
            else "Dự thảo đã đạt ngưỡng chấm điểm tự động và có thể chuyển sang soát xét thủ công."
        ),
        issues=issues,
        revision_instructions=[issue.revision_instruction for issue in issues],
    )


def _extract_assessment(response: Any) -> CriticAssessment:
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return (
            parsed
            if isinstance(parsed, CriticAssessment)
            else CriticAssessment.model_validate(parsed)
        )
    for output in getattr(response, "output", []):
        for item in getattr(output, "content", []):
            item_parsed = getattr(item, "parsed", None)
            if item_parsed is not None:
                return (
                    item_parsed
                    if isinstance(item_parsed, CriticAssessment)
                    else CriticAssessment.model_validate(item_parsed)
                )
            refusal = getattr(item, "refusal", None)
            if refusal:
                raise RuntimeError(f"The critic declined to grade the report: {refusal}")
    raise RuntimeError("The OpenAI response did not contain a structured critic assessment.")


def grade_with_openai(
    payload: dict[str, Any],
    report: AuditReport,
    files: Iterable[InputFile] = (),
    *,
    model: str | None = None,
) -> CriticAssessment:
    """Use a separate model call as an independent report critic."""

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("The openai package is not installed.") from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")

    client = OpenAI()
    selected_model = model or os.getenv(
        "OPENAI_CRITIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
    )
    uploaded_file_ids: list[str] = []
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "DỮ LIỆU HỢP ĐỒNG GỐC:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
                + "\n\nDỰ THẢO ĐÃ TẠO:\n"
                + json.dumps(report.model_dump(), ensure_ascii=False, indent=2)
            ),
        }
    ]
    system_prompt = """
Bạn là bộ máy phản biện độc lập trong quy trình báo cáo đảm bảo chuyên nghiệp.
Chấm điểm dự thảo dựa trên dữ liệu hợp đồng gốc và mọi bằng chứng đã gắn nhãn.
Không đánh giá cao cách diễn đạt tự tin nếu thiếu hỗ trợ. Không viết lại báo cáo.

Sử dụng các trọng số sau khi tính overall_score:
- dữ liệu thực tế và bằng chứng hỗ trợ: 40%
- tuân thủ phương pháp: 20%
- tính đầy đủ: 15%
- văn phong: 15%
- tính nhất quán nội bộ: 10%

Mọi dữ liệu tự tạo hoặc mâu thuẫn, kết luận thiếu hỗ trợ, thiếu bằng chứng cho phát hiện hoặc
thiếu phần bắt buộc đều là nội dung bị chặn và yêu cầu trạng thái revision_required.
Trả về hướng dẫn chỉnh sửa chính xác bằng tiếng Việt để bộ máy tạo báo cáo áp dụng.
Soát xét thủ công vẫn bắt buộc ngay cả khi đạt điểm tự động.
Chỉ đặt trạng thái pass khi overall_score đạt ít nhất 85 và không có nội dung bị chặn.
""".strip()

    try:
        for input_file in files:
            uploaded = client.files.create(
                file=(input_file.name, input_file.content, input_file.media_type),
                purpose="user_data",
            )
            uploaded_file_ids.append(uploaded.id)
            label = (
                "BÁO CÁO MẪU — không xem dữ liệu khách hàng trong mẫu là bằng chứng hiện tại"
                if input_file.role == "style"
                else "BẰNG CHỨNG HỢP ĐỒNG HIỆN TẠI"
            )
            content.extend(
                [
                    {"type": "input_text", "text": f"{label}: {input_file.name}"},
                    {"type": "input_file", "file_id": uploaded.id},
                ]
            )
        response = client.responses.parse(
            model=selected_model,
            reasoning={"effort": get_openai_reasoning_effort()},
            store=False,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            text_format=CriticAssessment,
        )
        return _extract_assessment(response)
    finally:
        for file_id in uploaded_file_ids:
            try:
                client.files.delete(file_id)
            except Exception:
                pass
