from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

from .config import get_template
from .models import AuditReport, Finding


DEFAULT_OPENAI_REASONING_EFFORT = "medium"
SUPPORTED_OPENAI_REASONING_EFFORTS = {
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}


def get_openai_reasoning_effort() -> str:
    """Return the configured, validated reasoning effort for live API calls."""

    effort = os.getenv(
        "OPENAI_REASONING_EFFORT", DEFAULT_OPENAI_REASONING_EFFORT
    ).strip().lower()
    if effort not in SUPPORTED_OPENAI_REASONING_EFFORTS:
        supported = ", ".join(sorted(SUPPORTED_OPENAI_REASONING_EFFORTS))
        raise RuntimeError(
            f"OPENAI_REASONING_EFFORT must be one of: {supported}."
        )
    return effort


@dataclass(frozen=True)
class InputFile:
    """File data passed from the interface without depending on Streamlit types."""

    name: str
    content: bytes
    media_type: str | None = None
    role: str = "evidence"


def _clean_findings(rows: Iterable[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for row in rows:
        if not any(str(value or "").strip() for value in row.values()):
            continue
        normalized = {
            "title": str(row.get("title") or "Phát hiện chưa có tiêu đề").strip(),
            "area": str(row.get("area") or "Chưa cung cấp").strip(),
            "risk_rating": row.get("risk_rating") or "Moderate",
            "condition": str(row.get("condition") or "Chưa cung cấp").strip(),
            "criteria": str(row.get("criteria") or "Chưa cung cấp").strip(),
            "cause": str(row.get("cause") or "Chưa xác định").strip(),
            "effect": str(row.get("effect") or "Chưa cung cấp").strip(),
            "recommendation": str(row.get("recommendation") or "Chưa cung cấp").strip(),
            "management_response": str(
                row.get("management_response") or "Chưa cung cấp"
            ).strip(),
            "evidence_reference": str(
                row.get("evidence_reference") or "Chưa cung cấp"
            ).strip(),
        }
        findings.append(Finding.model_validate(normalized))
    return findings


def build_demo_report(payload: dict[str, Any], rows: Iterable[dict[str, Any]]) -> AuditReport:
    """Create a deterministic report so the presentation works without an API key."""

    findings = _clean_findings(rows)
    report_type = str(payload.get("report_type") or "Site Security Assessment")
    report_type_label = get_template(report_type).get("label_vi", report_type)
    client_name = str(payload.get("client_name") or "Chưa cung cấp tên đơn vị")
    period_end = str(payload.get("period_end") or "chưa cung cấp kỳ báo cáo")
    conclusion = str(payload.get("conclusion") or "Chưa cung cấp kết luận.")

    if findings:
        risk_labels = {
            "Critical": "nghiêm trọng",
            "High": "cao",
            "Moderate": "trung bình",
            "Low": "thấp",
        }
        risk_summary = ", ".join(
            f"{sum(1 for finding in findings if finding.risk_rating == rating)} mức {risk_labels[rating]}"
            for rating in ("Critical", "High", "Moderate", "Low")
            if any(finding.risk_rating == rating for finding in findings)
        )
        finding_sentence = (
            f"Dự thảo gồm {len(findings)} phát hiện, trong đó có {risk_summary}."
        )
    else:
        finding_sentence = "Không có phát hiện cần báo cáo được nhập cho dự thảo này."

    return AuditReport(
        report_title=f"{report_type_label} — {client_name}",
        executive_summary=(
            f"Chúng tôi đã thực hiện các hoạt động kiểm tra được mô tả trong biên bản này tại {client_name} "
            f"vào ngày {period_end}. {conclusion} {finding_sentence} Tài liệu này vẫn "
            "phải được soát xét và phê duyệt bởi người có thẩm quyền."
        ),
        objective=str(payload.get("objective") or "Chưa cung cấp"),
        scope=str(payload.get("scope") or "Chưa cung cấp"),
        methodology=str(payload.get("procedures") or "Chưa cung cấp"),
        conclusion=conclusion,
        findings=findings,
        limitations=[
            "Dự thảo thử nghiệm này chỉ dựa trên thông tin do người kiểm tra nhập hoặc đính kèm.",
            "Không được phát hành biên bản trước khi bằng chứng hiện trường và hành động khắc phục được người có thẩm quyền kiểm tra.",
        ],
        reviewer_notes=[
            "Xác nhận mọi ngày tháng, vị trí, ca làm việc và tham chiếu bằng chứng khớp với hồ sơ hiện trường.",
            "Xác nhận hành động khắc phục, chủ sở hữu và thời hạn tuân thủ kế hoạch an ninh công trường đã được phê duyệt.",
        ],
    )


def _extract_parsed_report(response: Any) -> AuditReport:
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return parsed if isinstance(parsed, AuditReport) else AuditReport.model_validate(parsed)

    for output in getattr(response, "output", []):
        for item in getattr(output, "content", []):
            item_parsed = getattr(item, "parsed", None)
            if item_parsed is not None:
                return (
                    item_parsed
                    if isinstance(item_parsed, AuditReport)
                    else AuditReport.model_validate(item_parsed)
                )
            refusal = getattr(item, "refusal", None)
            if refusal:
                raise RuntimeError(f"The model declined to generate the report: {refusal}")
    raise RuntimeError("The OpenAI response did not contain a structured report.")


def generate_with_openai(
    payload: dict[str, Any],
    rows: Iterable[dict[str, Any]],
    files: Iterable[InputFile] = (),
    *,
    model: str | None = None,
) -> AuditReport:
    """Generate a structured report using the current OpenAI Responses API."""

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - covered in integration use
        raise RuntimeError("The openai package is not installed.") from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")

    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
    template = get_template(str(payload.get("report_type")))
    normalized_findings = [finding.model_dump() for finding in _clean_findings(rows)]
    facts = {**payload, "findings": normalized_findings}

    system_prompt = f"""
    Bạn lập dự thảo biên bản an ninh công trường bằng tiếng Việt để người có thẩm quyền soát xét.

CHUẨN BÁO CÁO
Loại báo cáo: {template.get('label_vi', payload.get('report_type'))}
Thứ tự phần bắt buộc: {', '.join(template['sections'])}
Quy chuẩn trình bày: {template['style_profile']}

QUY TẮC BẮT BUỘC
- Chỉ sử dụng dữ liệu từ thông tin dự án và các tệp được gắn nhãn rõ là bằng chứng hiện trường.
- Chỉ dùng biên bản mẫu đã phê duyệt để tham khảo văn phong, cấu trúc và thuật ngữ; không sao chép dữ liệu dự án trong mẫu.
- Không tự tạo ngày tháng, vị trí, ca làm việc, tham chiếu bằng chứng, yêu cầu an ninh hoặc phản hồi của chỉ huy công trường.
- Ghi "Chưa cung cấp" hoặc thêm ghi chú soát xét khi thiếu thông tin bắt buộc.
- Phân biệt rõ hoạt động đã thực hiện, quan sát thực tế và đánh giá rủi ro.
- Xem kết quả là dự thảo cần phê duyệt thủ công, không phải biên bản đã phát hành.
- Không tuyên bố công trường an toàn, tuân thủ hoặc được bảo vệ tuyệt đối.
- Toàn bộ nội dung mô tả trong báo cáo phải được viết bằng tiếng Việt.
""".strip()

    user_content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": "Tạo báo cáo có cấu trúc từ dữ liệu hợp đồng sau:\n"
            + json.dumps(facts, ensure_ascii=False, indent=2),
        }
    ]
    client = OpenAI()
    uploaded_file_ids: list[str] = []

    try:
        for input_file in files:
            uploaded = client.files.create(
                file=(input_file.name, input_file.content, input_file.media_type),
                purpose="user_data",
            )
            uploaded_file_ids.append(uploaded.id)
            label = (
                "BÁO CÁO MẪU ĐÃ PHÊ DUYỆT — chỉ dùng cho văn phong"
                if input_file.role == "style"
                else "BẰNG CHỨNG HỢP ĐỒNG — có thể dùng để hỗ trợ dữ liệu thực tế"
            )
            user_content.extend(
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
                {"role": "user", "content": user_content},
            ],
            text_format=AuditReport,
        )
        return _extract_parsed_report(response)
    finally:
        for file_id in uploaded_file_ids:
            try:
                client.files.delete(file_id)
            except Exception:
                # Generation should not fail solely because best-effort cleanup failed.
                pass


def revise_with_openai(
    payload: dict[str, Any],
    report: AuditReport,
    revision_instructions: list[str],
    files: Iterable[InputFile] = (),
    *,
    model: str | None = None,
) -> AuditReport:
    """Revise a draft from critic feedback without introducing new facts."""

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("The openai package is not installed.") from exc
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")

    client = OpenAI()
    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
    uploaded_file_ids: list[str] = []
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "DỮ LIỆU HỢP ĐỒNG:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
                + "\n\nDỰ THẢO HIỆN TẠI:\n"
                + json.dumps(report.model_dump(), ensure_ascii=False, indent=2)
                + "\n\nHƯỚNG DẪN CHỈNH SỬA TỪ BỘ MÁY PHẢN BIỆN:\n- "
                + "\n- ".join(revision_instructions)
            ),
        }
    ]
    system_prompt = """
Bạn chỉnh sửa dự thảo báo cáo đảm bảo chuyên nghiệp bằng tiếng Việt sau khi có phản biện độc lập.
Chỉ áp dụng các hướng dẫn chỉnh sửa được liệt kê và giữ nguyên lược đồ báo cáo có cấu trúc.
Chỉ sử dụng dữ liệu hợp đồng và bằng chứng đã gắn nhãn. Không tự tạo hoặc suy diễn bằng chứng,
ngày tháng, số tiền, cỡ mẫu, chính sách, phát hiện hoặc phản hồi của Ban Giám đốc còn thiếu.
Nếu không thể xử lý phản hồi từ dữ liệu đã cung cấp, hãy giữ lại giới hạn và thêm ghi chú soát xét.
Kết quả vẫn là dự thảo cần người có thẩm quyền phê duyệt. Toàn bộ nội dung phải bằng tiếng Việt.
""".strip()

    try:
        for input_file in files:
            uploaded = client.files.create(
                file=(input_file.name, input_file.content, input_file.media_type),
                purpose="user_data",
            )
            uploaded_file_ids.append(uploaded.id)
            label = (
                "BÁO CÁO MẪU ĐÃ PHÊ DUYỆT — chỉ dùng cho văn phong"
                if input_file.role == "style"
                else "BẰNG CHỨNG HỢP ĐỒNG — hỗ trợ dữ liệu thực tế"
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
            text_format=AuditReport,
        )
        return _extract_parsed_report(response)
    finally:
        for file_id in uploaded_file_ids:
            try:
                client.files.delete(file_id)
            except Exception:
                pass
