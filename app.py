from __future__ import annotations

import html
import json
import os
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from audit_agent.config import REPORT_TEMPLATES, get_template
from audit_agent.critic import build_demo_assessment, grade_with_openai
from audit_agent.export import build_docx
from audit_agent.generator import (
    InputFile,
    build_demo_report,
    generate_with_openai,
    get_openai_reasoning_effort,
    revise_with_openai,
)
from audit_agent.models import AuditReport, CriticAssessment, WarehouseClassification
from audit_agent.qa import completeness_score, run_qa
from audit_agent.warehouse import list_approved_reports, transfer_approved_report
from audit_agent.automation import PASSING_SCORE, run_automation_loop
from audit_agent.postgres_warehouse import approve_client_release, save_generated_version
from audit_agent.ingestion_gateway import (
    MIN_FINE_TUNING_EXAMPLES,
    approve_gateway_use,
    build_dataset_export,
    get_gateway_upload,
    list_gateway_datasets,
    list_gateway_uploads,
    preview_report_upload,
    stage_report_upload,
)
from audit_agent.learning_loop import assess_learning_readiness
from audit_agent.github_agent import (
    DEFAULT_REPOSITORY_URL,
    DEFAULT_TASK,
    run_practice_agent,
)


load_dotenv()

st.set_page_config(
    page_title="Audit Automation Pipeline",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)


RISK_LABELS_VI = {
    "Low": "Thấp",
    "Moderate": "Trung bình",
    "High": "Cao",
    "Critical": "Nghiêm trọng",
}

STATUS_LABELS_VI = {
    "VALIDATED": "Đã xác thực",
    "QUARANTINED": "Đã cách ly",
    "READY": "Sẵn sàng",
    "PREVIEW_ONLY": "Chỉ xem trước",
    "pass": "Đạt",
    "revision_required": "Cần chỉnh sửa",
    "passed": "Đạt",
    "evidence_blocker": "Bị chặn do bằng chứng",
    "revision_limit": "Đạt giới hạn chỉnh sửa",
}

USE_LABELS_VI = {
    "RETRIEVAL": "Truy xuất",
    "EVALUATION": "Đánh giá",
    "TRAINING": "Huấn luyện",
}

REASONING_LABELS_VI = {
    "none": "Không",
    "low": "Thấp",
    "medium": "Trung bình",
    "high": "Cao",
    "xhigh": "Rất cao",
    "max": "Tối đa",
}

INDUSTRY_LABELS_VI = {
    "Manufacturing": "Xây dựng dân dụng",
    "Distribution": "Hạ tầng & logistics",
    "Financial services": "Công nghiệp",
    "Not-for-profit": "Dự án cộng đồng",
    "Other": "Khác",
}

AUDIT_AREA_LABELS_VI = {
    "Internal controls": "Kiểm soát ra vào",
    "Inventory": "Vật tư & thiết bị",
    "Grant expenditure": "An toàn hiện trường",
    "Financial reporting": "Giám sát chu vi",
    "Other": "Khác",
}

CONFIDENTIALITY_LABELS_VI = {
    "Internal": "Nội bộ",
    "Confidential": "Bảo mật",
    "Highly confidential": "Bảo mật cao",
}

LEARNING_LABELS_VI = {
    "prohibited": "Không được phép",
    "retrieval_only": "Chỉ truy xuất",
    "evaluation_only": "Chỉ đánh giá",
    "training_approved": "Được phép huấn luyện",
}

QA_TITLES_VI = {
    "Required engagement data is missing": "Thiếu dữ liệu hợp đồng bắt buộc",
    "Required engagement data is complete": "Dữ liệu hợp đồng bắt buộc đã đầy đủ",
    "Finding evidence references are missing": "Thiếu tham chiếu bằng chứng cho phát hiện",
    "Findings contain evidence references": "Các phát hiện có tham chiếu bằng chứng",
    "No findings were entered": "Chưa nhập phát hiện",
    "High-risk finding is incomplete": "Phát hiện rủi ro cao chưa đầy đủ",
    "Risk-response fields are complete": "Các trường phản hồi rủi ro đã đầy đủ",
    "Management response remains outstanding": "Chưa có phản hồi của Ban Giám đốc",
    "Professional review is required": "Bắt buộc soát xét chuyên môn",
}

QA_DETAILS_VI = {
    "All mandatory preparation fields contain a value.": "Tất cả trường chuẩn bị bắt buộc đều đã có dữ liệu.",
    "Each entered finding points to supporting evidence for reviewer confirmation.": "Mỗi phát hiện đã nhập đều tham chiếu đến bằng chứng để người soát xét xác nhận.",
    "Confirm that a no-findings report is appropriate for this engagement.": "Xác nhận rằng báo cáo không có phát hiện là phù hợp với hợp đồng này.",
    "High and critical findings include an effect and recommendation.": "Các phát hiện mức cao và nghiêm trọng đã bao gồm ảnh hưởng và kiến nghị.",
    "Automated checks do not replace the firm's technical, evidence, and engagement-quality review.": "Kiểm tra tự động không thay thế việc soát xét kỹ thuật, bằng chứng và chất lượng hợp đồng của công ty.",
    "The independent grading engine found blocking issues that require revision.": "Bộ máy chấm điểm độc lập phát hiện nội dung bị chặn cần được chỉnh sửa.",
    "The draft passed the automated grading threshold and can proceed to human review.": "Dự thảo đã đạt ngưỡng chấm điểm tự động và có thể chuyển sang soát xét thủ công.",
}

REVISION_INSTRUCTIONS_VI = {
    "Add or correct the referenced information and regenerate the draft.": "Bổ sung hoặc sửa thông tin được tham chiếu rồi tạo lại dự thảo.",
    "Confirm this item during human review and update the report where necessary.": "Xác nhận nội dung này trong quá trình soát xét thủ công và cập nhật báo cáo khi cần.",
}

VALIDATION_DETAILS_VI = {
    "FILENAME_REQUIRED": "Bắt buộc cung cấp tên tệp.",
    "FILENAME_NORMALIZED": "Đã loại bỏ thành phần thư mục khỏi tên tệp được cung cấp.",
    "FILE_TYPE_NOT_ALLOWED": "Bản thử nghiệm chỉ chấp nhận DOCX, PDF có lớp văn bản, JSON và TXT mã hóa UTF-8.",
    "EMPTY_FILE": "Tệp tải lên không có nội dung.",
    "FILE_TOO_LARGE": "Tệp vượt quá giới hạn dung lượng của bản thử nghiệm.",
    "CONTENT_EXTRACTION_FAILED": "Không thể trích xuất nội dung từ tệp.",
    "CONTENT_TOO_SHORT": "Nội dung trích xuất quá ngắn và chưa giống một báo cáo hoàn chỉnh.",
    "POTENTIAL_EMAIL": "Báo cáo có thể chứa địa chỉ email; bắt buộc soát xét ẩn danh thủ công.",
    "POTENTIAL_PHONE": "Báo cáo có thể chứa số điện thoại; bắt buộc soát xét ẩn danh thủ công.",
}


def report_type_vi(report_type: str) -> str:
    return str(get_template(report_type).get("label_vi", report_type))


def risk_vi(risk: str) -> str:
    return RISK_LABELS_VI.get(risk, risk)


def status_vi(status: str) -> str:
    return STATUS_LABELS_VI.get(status, status.replace("_", " ").title())


def qa_text_vi(text: str) -> str:
    return QA_TITLES_VI.get(
        text,
        QA_DETAILS_VI.get(text, REVISION_INSTRUCTIONS_VI.get(text, text)),
    )


def validation_detail_vi(rule_code: str, detail: str) -> str:
    return VALIDATION_DETAILS_VI.get(rule_code, detail)


def approved_uses_vi(approved_uses: str) -> str:
    if not approved_uses:
        return "Không có"
    return ", ".join(
        USE_LABELS_VI.get(item.strip(), item.strip())
        for item in approved_uses.split(",")
    )


st.markdown(
    """
<style>
    :root {
        --ink: #102a35;
        --muted: #5f737d;
        --paper: #f3f6f5;
        --card: #ffffff;
        --teal: #087f78;
        --teal-deep: #075d5a;
        --teal-soft: #e4f3f0;
        --navy: #102d3a;
        --gold: #c99a47;
        --gold-soft: #f8efdf;
        --line: #d8e3e0;
        --shadow: 0 12px 32px rgba(16, 45, 58, .07);
    }
    html { scroll-behavior: smooth; }
    .stApp {
        background:
            radial-gradient(circle at 92% 2%, rgba(8,127,120,.08), transparent 24rem),
            var(--paper);
        color: var(--ink);
        font-family: Inter, "SF Pro Text", "Segoe UI", Arial, sans-serif;
    }
    /* The product workspace is intentionally full-width for this iteration. */
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    .block-container { padding-top: 1.15rem; padding-bottom: 4rem; max-width: 1360px; }
    .app-topbar {
        display: flex; align-items: center; justify-content: space-between; gap: 1rem;
        min-height: 4.25rem; margin: 0 0 1rem; overflow: visible;
    }
    .brand-wordmark { position: relative; display: inline-block; min-height: 3.5rem; padding-top: .9rem; }
    .brand-wordmark strong { color: #050505; font-size: 1.9rem; line-height: 1; letter-spacing: -.04em; }
    .topbar-meta { color: var(--muted); font-size: .78rem; font-weight: 600; }
    .brand-kicker {
        letter-spacing: .16em; text-transform: uppercase; font-weight: 700;
        font-size: .7rem; color: var(--teal); margin-bottom: .65rem;
    }
    .hero {
        position: relative; overflow: hidden;
        border: 1px solid #d4e2de; border-radius: 24px; padding: 2.15rem 2.3rem;
        background: linear-gradient(135deg, #ffffff 0%, #edf6f3 64%, #e6f2ef 100%);
        box-shadow: var(--shadow); margin-bottom: 1rem;
    }
    .hero::after {
        content: ""; position: absolute; width: 16rem; height: 16rem; border-radius: 50%;
        right: -5rem; top: -8rem; background: rgba(8,127,120,.08);
    }
    .hero-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(250px, .75fr); gap: 2rem; align-items: center; }
    .hero h1 { color: var(--ink); margin: 0 0 .65rem 0; font-size: clamp(2rem, 3vw, 3rem); line-height: 1.08; letter-spacing: -.045em; max-width: 820px; }
    .hero p { color: var(--muted); margin: 0; max-width: 760px; font-size: 1.02rem; line-height: 1.65; }
    .hero-control-panel {
        position: relative; z-index: 1; background: rgba(255,255,255,.78); border: 1px solid rgba(255,255,255,.9);
        border-radius: 16px; padding: .55rem 1rem; box-shadow: 0 8px 22px rgba(16,45,58,.07);
        backdrop-filter: blur(8px);
    }
    .control-row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .72rem 0; border-bottom: 1px solid var(--line); }
    .control-row:last-child { border-bottom: 0; }
    .control-label { color: var(--muted); font-size: .76rem; }
    .control-value { color: var(--ink); font-size: .8rem; font-weight: 800; text-align: right; }
    .control-dot { display: inline-block; width: .48rem; height: .48rem; border-radius: 50%; background: var(--teal); margin-right: .38rem; box-shadow: 0 0 0 4px rgba(8,127,120,.1); }
    .status-pill {
        display: inline-block; margin-top: 1rem; padding: .38rem .7rem;
        border-radius: 999px; background: var(--teal-soft); color: #075c59;
        font-size: .78rem; font-weight: 700;
    }
    .automation-overview { margin: 1.45rem 0 1.2rem; }
    .automation-heading { display: flex; align-items: end; justify-content: space-between; gap: 1rem; margin: 0 0 .8rem; }
    .automation-heading h2 { margin: 0; color: var(--navy); font-size: 1.25rem; letter-spacing: -.025em; }
    .automation-heading p { margin: 0; max-width: 38rem; color: var(--muted); font-size: .82rem; line-height: 1.5; }
    .automation-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .7rem; }
    .automation-card { min-height: 9.2rem; padding: 1rem; background: rgba(255,255,255,.86); border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 5px 15px rgba(16,45,58,.035); }
    .automation-card:nth-child(1), .automation-card:nth-child(2), .automation-card:nth-child(3) { grid-column: span 1; }
    .automation-card:nth-child(7) { grid-column: span 1; }
    .automation-index { display: inline-grid; place-items: center; width: 1.6rem; height: 1.6rem; border-radius: 8px; background: var(--teal-soft); color: var(--teal-deep); font-size: .68rem; font-weight: 850; }
    .automation-card h3 { margin: .62rem 0 .32rem; color: var(--ink); font-size: .94rem; letter-spacing: -.015em; }
    .automation-card p { margin: 0; color: var(--muted); font-size: .77rem; line-height: 1.48; }
    .workflow-nav {
        position: sticky; top: .35rem; z-index: 999;
        display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: .35rem;
        padding: .45rem; margin: 1rem 0 1.25rem;
        background: rgba(255,255,255,.9); border: 1px solid var(--line); border-radius: 15px;
        box-shadow: 0 8px 24px rgba(16,45,58,.07); backdrop-filter: blur(12px);
    }
    .workflow-nav a {
        display: flex; align-items: center; justify-content: center; gap: .35rem;
        color: var(--muted); text-decoration: none !important; border-radius: 10px;
        padding: .6rem .35rem; font-size: .72rem; font-weight: 750; white-space: nowrap;
        transition: background .16s ease, color .16s ease, transform .16s ease;
    }
    .workflow-nav a:hover { background: var(--teal-soft); color: var(--teal-deep); transform: translateY(-1px); }
    .workflow-nav b { color: var(--teal); font-size: .66rem; }
    [data-testid="stMetric"] {
        background: var(--card); border: 1px solid var(--line); border-radius: 14px;
        padding: .82rem 1rem; box-shadow: 0 5px 16px rgba(20,45,61,.04);
    }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { color: var(--navy); letter-spacing: -.03em; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255,255,255,.82); border-color: var(--line); border-radius: 20px;
        box-shadow: 0 9px 28px rgba(16,45,58,.045); margin-bottom: .8rem;
    }
    .section-anchor { scroll-margin-top: 5.5rem; }
    .section-heading { display: flex; align-items: flex-start; gap: .9rem; margin: .15rem 0 1.1rem; }
    .section-number {
        flex: 0 0 auto; display: grid; place-items: center; width: 2.2rem; height: 2.2rem;
        border-radius: 11px; background: var(--navy); color: white; font-size: .72rem; font-weight: 850;
        box-shadow: 0 6px 14px rgba(16,45,58,.15);
    }
    .section-copy h2 { margin: -.1rem 0 .18rem; color: var(--navy); font-size: 1.34rem; letter-spacing: -.025em; }
    .section-copy p { margin: 0; color: var(--muted); font-size: .83rem; line-height: 1.45; }
    .section-card {
        border: 1px solid var(--line); background: var(--card); border-radius: 16px;
        padding: 1.1rem 1.25rem; margin: .5rem 0 1rem 0;
    }
    .section-card h3 { margin-top: 0; color: var(--ink); }
    .report-paper {
        background: #fff; border: 1px solid #d8e1de; border-radius: 16px;
        box-shadow: 0 12px 28px rgba(20,45,61,.07); padding: 2rem 2.4rem;
    }
    .report-paper h2, .report-paper h3 { color: var(--ink); }
    .report-paper p { color: #334b58; line-height: 1.65; }
    .risk-badge {
        display: inline-block; border-radius: 999px; padding: .2rem .55rem;
        background: #f5ead9; color: #7b4f14; font-size: .74rem; font-weight: 700;
    }
    .sidebar-brand {
        border-bottom: 1px solid #31505a; padding: .3rem 0 1.2rem 0; margin-bottom: 1rem;
    }
    .sidebar-brand h2 { margin: 0; font-size: 1.3rem; }
    .sidebar-brand p { color: #b9c9cc !important; margin: .2rem 0 0 0; font-size: .82rem; }
    .small-note { color: var(--muted); font-size: .85rem; }
    .stButton > button, .stDownloadButton > button {
        border-radius: 11px; font-weight: 750; min-height: 2.8rem;
        border-color: #cadbd6; transition: transform .15s ease, box-shadow .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(16,45,58,.1); }
    [data-testid="stBaseButton-primary"] { background: var(--teal); border-color: var(--teal); }
    [data-testid="stFileUploaderDropzone"] { border-radius: 14px; border-color: #c9dbd6; background: #fbfdfc; }
    [data-baseweb="input"] > div, [data-baseweb="textarea"] > div, [data-baseweb="select"] > div { border-radius: 10px !important; }
    div[data-testid="stTabs"] button { font-weight: 650; }
    .app-footer {
        display: flex; justify-content: space-between; gap: 1rem; align-items: center;
        color: var(--muted); font-size: .75rem; border-top: 1px solid var(--line);
        margin-top: 1.7rem; padding-top: 1.2rem;
    }
    @media (max-width: 900px) {
        .hero-grid { grid-template-columns: 1fr; }
        .automation-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .workflow-nav { grid-template-columns: repeat(3, 1fr); position: static; }
        .topbar-meta { display: none; }
    }
    @media (max-width: 600px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; }
        .hero { padding: 1.55rem; }
        .automation-grid { grid-template-columns: 1fr; }
        .workflow-nav { grid-template-columns: repeat(2, 1fr); }
        .workflow-nav a { justify-content: flex-start; padding-left: .65rem; }
        .app-footer { flex-direction: column; align-items: flex-start; }
    }
</style>
""",
    unsafe_allow_html=True,
)


def render_section_header(anchor: str, number: str, title: str, description: str) -> None:
    st.markdown(
        f"""
        <div id="{html.escape(anchor)}" class="section-anchor"></div>
        <div class="section-heading">
            <div class="section-number">{html.escape(number)}</div>
            <div class="section-copy">
                <h2>{html.escape(title)}</h2>
                <p>{html.escape(description)}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_selected_demo() -> None:
    report_type = st.session_state.get("report_type", next(iter(REPORT_TEMPLATES)))
    demo = get_template(report_type)["demo"]
    for key, value in demo.items():
        if key == "findings":
            st.session_state.finding_rows = [dict(item) for item in value]
            st.session_state.pop("findings_editor", None)
        else:
            st.session_state[key] = value
    st.session_state.generated_report = None
    st.session_state.generated_critic = None
    st.session_state.automation_history = []
    st.session_state.report_id = None
    st.session_state.report_code = None
    st.session_state.report_version_id = None
    st.session_state.version_number = None


def initialise_state() -> None:
    if "report_type" not in st.session_state:
        st.session_state.report_type = next(iter(REPORT_TEMPLATES))
    demo = get_template(st.session_state.report_type)["demo"]
    for key, value in demo.items():
        if key == "findings":
            st.session_state.setdefault("finding_rows", [dict(item) for item in value])
        else:
            st.session_state.setdefault(key, value)
    st.session_state.setdefault("generated_report", None)
    st.session_state.setdefault("generated_critic", None)
    st.session_state.setdefault("generated_mode", None)
    st.session_state.setdefault("revision_cycles", 0)
    st.session_state.setdefault("automation_history", [])
    st.session_state.setdefault("automation_stop_reason", None)
    st.session_state.setdefault("report_id", None)
    st.session_state.setdefault("report_code", None)
    st.session_state.setdefault("report_version_id", None)
    st.session_state.setdefault("version_number", None)
    st.session_state.setdefault("gateway_flash", None)
    st.session_state.setdefault("gateway_dataset_content", None)
    st.session_state.setdefault("gateway_dataset_filename", None)
    st.session_state.setdefault("gateway_dataset_status", None)
    st.session_state.setdefault("gateway_dataset_id", None)
    st.session_state.setdefault("github_agent_repo_url", DEFAULT_REPOSITORY_URL)
    st.session_state.setdefault("github_agent_task", DEFAULT_TASK)
    st.session_state.setdefault("github_agent_mode", "Presentation demo")
    st.session_state.setdefault("github_agent_result", None)


def collect_payload() -> dict[str, Any]:
    return {
        "report_type": st.session_state.report_type,
        "client_name": st.session_state.get("client_name", ""),
        "period_end": st.session_state.get("period_end", ""),
        "prepared_by": st.session_state.get("prepared_by", ""),
        "engagement_partner": st.session_state.get("engagement_partner", ""),
        "objective": st.session_state.get("objective", ""),
        "scope": st.session_state.get("scope", ""),
        "procedures": st.session_state.get("procedures", ""),
        "conclusion": st.session_state.get("conclusion", ""),
    }


def convert_uploads(uploaded_files: list[Any] | None, role: str) -> list[InputFile]:
    return [
        InputFile(
            name=item.name,
            content=item.getvalue(),
            media_type=getattr(item, "type", None),
            role=role,
        )
        for item in (uploaded_files or [])
    ]


def render_report(report: AuditReport) -> None:
    st.markdown('<div class="report-paper">', unsafe_allow_html=True)
    st.markdown(f"## {html.escape(report.report_title)}")
    st.caption("DỰ THẢO · CHỈ DÙNG CHO SOÁT XÉT HIỆN TRƯỜNG CÓ THẨM QUYỀN")
    st.markdown("### Tóm tắt điều hành")
    st.write(report.executive_summary)
    st.markdown("### Mục tiêu")
    st.write(report.objective)
    st.markdown("### Phạm vi")
    st.write(report.scope)
    st.markdown("### Hoạt động kiểm tra")
    st.write(report.methodology)
    st.markdown("### Kết luận")
    st.write(report.conclusion)
    st.markdown("### Rủi ro và hành động chi tiết")
    if not report.findings:
        st.info("Chưa nhập rủi ro hoặc quan sát cần xử lý.")
    for number, finding in enumerate(report.findings, start=1):
        with st.expander(
            f"{number}. {finding.title} · {risk_vi(finding.risk_rating)}", expanded=True
        ):
            st.markdown(f'<span class="risk-badge">Mức độ {risk_vi(finding.risk_rating).lower()}</span>', unsafe_allow_html=True)
            left, right = st.columns(2)
            with left:
                st.markdown("**Hiện trạng**")
                st.write(finding.condition)
                st.markdown("**Yêu cầu kiểm soát**")
                st.write(finding.criteria)
                st.markdown("**Nguyên nhân**")
                st.write(finding.cause)
            with right:
                st.markdown("**Ảnh hưởng**")
                st.write(finding.effect)
                st.markdown("**Hành động khắc phục**")
                st.write(finding.recommendation)
                st.markdown("**Ảnh / nhật ký bằng chứng**")
                st.write(finding.evidence_reference)
            st.markdown("**Phản hồi của chỉ huy**")
            st.write(finding.management_response)
    st.markdown("### Giới hạn")
    for item in report.limitations:
        st.markdown(f"- {item}")
    st.markdown("</div>", unsafe_allow_html=True)


initialise_state()

# Configuration is kept server-side while the workspace UI is being designed.
generation_mode = "Presentation demo"
api_ready = bool(os.getenv("OPENAI_API_KEY"))
automation_enabled = True

st.markdown(
    """
    <div class="app-topbar">
        <div class="brand-wordmark" aria-label="Audit Automation Pipeline">
            <strong>Audit Pipeline</strong>
        </div>
        <div class="topbar-meta">Audit Management Platform</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <div class="hero-grid">
            <div>
                <div class="brand-kicker">Audit Automation Pipeline · Assurance Prototype</div>
                <h1>Quản lý cuộc kiểm toán từ lập kế hoạch đến phát hành báo cáo</h1>
                <p>Một không gian kiểm toán có kiểm soát để ghi nhận bằng chứng, đánh giá phát hiện và hoàn tất phê duyệt chuyên môn.</p>
                <span class="status-pill">Môi trường trình diễn · dữ liệu giả lập được kiểm soát</span>
            </div>
            <div class="hero-control-panel">
                <div class="control-row">
                    <span class="control-label">Trạng thái hồ sơ</span>
                    <span class="control-value"><i class="control-dot"></i>Đang lập kế hoạch</span>
                </div>
                <div class="control-row">
                    <span class="control-label">Phương pháp</span>
                    <span class="control-value">Dựa trên rủi ro</span>
                </div>
                <div class="control-row">
                    <span class="control-label">Cổng phê duyệt</span>
                    <span class="control-value">Soát xét cấp quản lý</span>
                </div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

summary_cols = st.columns(4)
summary_cols[0].metric("Chương trình kiểm toán", get_template(st.session_state.report_type)["code"])
summary_cols[1].metric("Đơn vị được kiểm toán", st.session_state.get("client_name", "Chưa cung cấp"))
summary_cols[2].metric("Phát hiện ghi nhận", len(st.session_state.get("finding_rows", [])))
summary_cols[3].metric(
    "Trạng thái hồ sơ", "Chờ soát xét" if st.session_state.generated_report else "Đang lập kế hoạch"
)

st.markdown(
    """
    <section class="automation-overview" aria-label="Năng lực tự động hóa kiểm toán">
        <div class="automation-heading">
            <h2>7 năng lực tự động hóa kiểm toán</h2>
            <p>Mỗi mô-đun giải quyết một điểm nghẽn riêng trong chu trình kiểm toán, từ đánh giá rủi ro đến thu thập bằng chứng.</p>
        </div>
        <div class="automation-grid">
            <article class="automation-card"><span class="automation-index">01</span><h3>Phân tích bằng chứng</h3><p>Kiểm tra tính đầy đủ, liên kết nguồn và dấu hiệu bất thường trong tài liệu, dữ liệu và giấy tờ làm việc trước khi đánh giá.</p></article>
            <article class="automation-card"><span class="automation-index">02</span><h3>Phân tích dự báo</h3><p>Phân tích dữ liệu lịch sử và thời gian thực để nhận diện xu hướng, đánh giá rủi ro và cảnh báo vấn đề sớm.</p></article>
            <article class="automation-card"><span class="automation-index">03</span><h3>Tự động hóa quy trình (RPA)</h3><p>Tự động xử lý các thao tác lặp lại, theo quy tắc như đối chiếu số liệu và trích xuất dữ liệu hóa đơn.</p></article>
            <article class="automation-card"><span class="automation-index">04</span><h3>Tạo báo cáo</h3><p>Chuyển dữ liệu phức tạp thành báo cáo, tóm tắt và phát hiện nhất quán, rõ ràng và chuyên nghiệp.</p></article>
            <article class="automation-card"><span class="automation-index">05</span><h3>Quản lý cuộc kiểm toán</h3><p>Tập trung kế hoạch, tiến độ, nhiệm vụ và luồng phê duyệt để nhóm phối hợp hiệu quả và đúng hạn.</p></article>
            <article class="automation-card"><span class="automation-index">06</span><h3>Quản lý tài liệu</h3><p>Lưu trữ, truy xuất và chia sẻ hồ sơ có cấu trúc, bảo đảm kiểm soát phiên bản và khả năng tuân thủ.</p></article>
            <article class="automation-card"><span class="automation-index">07</span><h3>Cổng PBC khách hàng</h3><p>Quản lý yêu cầu Prepared By Client, nhận tài liệu và theo dõi trạng thái ngay trên một không gian chung.</p></article>
        </div>
    </section>
    """,
    unsafe_allow_html=True,
)

github_agent_tab = st.container(border=True)
with github_agent_tab:
    render_section_header(
        "github-agent",
        "07",
        "Phòng thực hành AI agent cho GitHub",
        "Cho agent đọc metadata và README của một repository công khai, sau đó lập kế hoạch kiểm tra có kiểm soát.",
    )
    agent_left, agent_right = st.columns([1.05, 0.95])
    with agent_left:
        st.text_input(
            "Repository GitHub",
            key="github_agent_repo_url",
            help="Chỉ chấp nhận URL dạng https://github.com/owner/repository.",
        )
        st.text_area(
            "Nhiệm vụ thực hành",
            key="github_agent_task",
            height=100,
            help="Ví dụ: Truy tìm entry point và đề xuất cách viết test cho luồng chat.",
        )
        github_agent_mode = st.radio(
            "Chế độ agent",
            ["Presentation demo", "Live OpenAI API"],
            key="github_agent_mode",
            format_func=lambda value: {
                "Presentation demo": "Bản trình diễn (không cần API key)",
                "Live OpenAI API": "OpenAI API trực tiếp",
            }[value],
            horizontal=True,
        )
        run_github_agent = st.button(
            "Chạy agent GitHub",
            type="primary",
            width="stretch",
            key="run_github_agent",
        )
    with agent_right:
        st.markdown(
            """
            <div class="section-card">
                <h3>Phạm vi an toàn của bản thực hành</h3>
                <p class="small-note">Agent chỉ đọc metadata, danh sách tệp gốc và README. Nó không tạo commit, issue, pull request, merge hoặc deployment.</p>
                <p class="small-note">Repository được coi là dữ liệu không đáng tin cậy; mọi thay đổi trong tương lai vẫn cần người dùng phê duyệt và kiểm tra diff.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if run_github_agent:
        try:
            with st.spinner("Đang cho agent đọc repository và lập kế hoạch..."):
                github_run = run_practice_agent(
                    st.session_state.github_agent_repo_url,
                    st.session_state.github_agent_task,
                    mode=github_agent_mode,
                )
            st.session_state.github_agent_result = github_run.as_dict()
            st.success("Agent đã hoàn tất lượt thực hành chỉ-đọc.")
        except Exception as exc:
            st.session_state.github_agent_result = None
            st.error(f"Agent GitHub thất bại: {exc}")

    if st.session_state.github_agent_result:
        github_result = st.session_state.github_agent_result
        snapshot = github_result.get("snapshot") or {}
        plan = github_result.get("plan") or {}
        if github_result.get("fetch_error"):
            st.warning(
                "Không đọc được API GitHub trong lượt này; agent vẫn dựng kế hoạch từ URL và bộ khung demo. "
                + str(github_result["fetch_error"])
            )
        if snapshot:
            agent_metrics = st.columns(4)
            agent_metrics[0].metric("Repository", snapshot.get("full_name", "—"))
            agent_metrics[1].metric("Ngôn ngữ", snapshot.get("language", "—"))
            agent_metrics[2].metric("Stars", snapshot.get("stars", 0))
            agent_metrics[3].metric("Nhánh mặc định", snapshot.get("default_branch", "—"))
            st.caption(snapshot.get("description", ""))
        st.markdown("### Kế hoạch của agent")
        st.info(str(plan.get("summary", "Chưa có tóm tắt.")))
        for number, step in enumerate(plan.get("plan", []), start=1):
            st.write(f"{number}. {step}")
        detail_left, detail_right = st.columns(2)
        with detail_left:
            st.markdown("**Tệp nên kiểm tra**")
            st.code("\n".join(plan.get("files_to_inspect", [])) or "Chưa xác định", language="text")
        with detail_right:
            st.markdown("**Công cụ và rào chắn**")
            for item in plan.get("proposed_tools", []):
                st.write(f"• {item}")
            for item in plan.get("guardrails", []):
                st.write(f"• {item}")
        st.markdown(f"**Bước tiếp theo:** {plan.get('next_step', 'Cần người dùng xác nhận.')}")

st.markdown(
    """
    <nav class="workflow-nav" aria-label="Điều hướng quy trình">
        <a href="#chuan-bi"><b>01</b> Lập kế hoạch</a>
        <a href="#chuan-bao-cao"><b>02</b> Chuẩn kiểm toán</a>
        <a href="#tao-bao-cao"><b>03</b> Hồ sơ &amp; báo cáo</a>
        <a href="#soat-xet"><b>04</b> Soát xét chất lượng</a>
        <a href="#kho-du-lieu"><b>05</b> Kho tri thức</a>
        <a href="#cong-ai"><b>06</b> Quản trị AI</a>
        <a href="#github-agent"><b>07</b> Công cụ bổ trợ</a>
    </nav>
    """,
    unsafe_allow_html=True,
)

prepare_tab = st.container(border=True)
standards_tab = st.container(border=True)
draft_tab = st.container(border=True)
review_tab = st.container(border=True)
warehouse_tab = st.container(border=True)
gateway_tab = st.container(border=True)

with prepare_tab:
    render_section_header(
        "chuan-bi",
        "01",
        "Lập kế hoạch cuộc kiểm toán",
        "Xác định đơn vị được kiểm toán, phạm vi, thủ tục và các khu vực trọng yếu cần đánh giá.",
    )
    st.markdown("### Thông tin cuộc kiểm toán")
    st.caption("Dữ liệu trình diễn là giả lập. Khi vận hành thực tế, chỉ nhập thông tin đã được phép xử lý.")
    first, second = st.columns(2)
    with first:
        st.text_input("Đơn vị được kiểm toán", key="client_name")
        st.text_input("Kiểm toán viên phụ trách", key="prepared_by")
    with second:
        st.text_input("Kỳ / ngày kiểm toán", key="period_end")
        st.text_input("Trưởng nhóm / người soát xét", key="engagement_partner")

    st.markdown("### Phạm vi và thủ tục kiểm toán")
    st.text_area("Mục tiêu", key="objective", height=95)
    st.text_area("Phạm vi", key="scope", height=100)
    st.text_area("Thủ tục đã thực hiện", key="procedures", height=120)
    st.text_area("Kết luận kiểm toán dự kiến", key="conclusion", height=115)

    st.markdown("### Phát hiện và khuyến nghị")
    st.caption("Thêm hoặc xóa dòng. Mỗi phát hiện phải có tham chiếu rõ ràng đến bằng chứng kiểm toán.")
    edited_findings = st.data_editor(
        st.session_state.finding_rows,
        key="findings_editor",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "title": st.column_config.TextColumn("Phát hiện / quan sát", width="large", required=True),
            "area": st.column_config.TextColumn("Quy trình / khu vực", width="medium"),
            "risk_rating": st.column_config.SelectboxColumn(
                "Mức độ", options=["Low", "Moderate", "High", "Critical"],
                format_func=risk_vi, required=True
            ),
            "condition": st.column_config.TextColumn("Hiện trạng", width="large"),
            "criteria": st.column_config.TextColumn("Yêu cầu kiểm soát", width="large"),
            "cause": st.column_config.TextColumn("Nguyên nhân", width="large"),
            "effect": st.column_config.TextColumn("Ảnh hưởng", width="large"),
            "recommendation": st.column_config.TextColumn("Hành động khắc phục", width="large"),
            "management_response": st.column_config.TextColumn("Phản hồi của đơn vị", width="large"),
            "evidence_reference": st.column_config.TextColumn("Tham chiếu bằng chứng", width="large"),
        },
    )
    st.session_state.finding_rows = list(edited_findings)

    st.markdown("### Bằng chứng kiểm toán")
    evidence_uploads = st.file_uploader(
        "Đính kèm giấy tờ làm việc, checklist hoặc tệp hỗ trợ",
        type=["pdf", "docx", "xlsx", "csv", "txt"],
        accept_multiple_files=True,
        help="Chế độ trình diễn chỉ liệt kê và không truyền tệp. Chế độ trực tiếp gửi tệp dưới nhãn bằng chứng kiểm toán.",
    )
    if evidence_uploads:
        st.caption("Đã đính kèm: " + ", ".join(item.name for item in evidence_uploads))

with standards_tab:
    render_section_header(
        "chuan-bao-cao",
        "02",
        "Chuẩn mực và phương pháp kiểm toán",
        "Áp dụng cấu trúc báo cáo, quy ước ghi nhận và nguyên tắc độc lập đối với bằng chứng.",
    )
    selected_template = get_template(st.session_state.report_type)
    left, right = st.columns([1.05, 0.95])
    with left:
        st.markdown("### Cấu trúc báo cáo đã phê duyệt")
        for number, section in enumerate(selected_template["sections"], start=1):
            st.markdown(f"**{number}.** {section}")
        st.markdown("### Quy chuẩn trình bày")
        st.info(selected_template["style_profile"])
    with right:
        st.markdown("### Báo cáo mẫu đã phê duyệt")
        st.caption(
            "Trong chế độ trực tiếp, báo cáo mẫu chỉ định hướng cấu trúc và văn phong. Dữ liệu của đơn vị trong mẫu luôn được loại trừ rõ ràng."
        )
        style_uploads = st.file_uploader(
            "Tải lên báo cáo mẫu đã phê duyệt và ẩn danh",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
            key="style_uploads",
        )
        if style_uploads:
            st.success(f"Đã sẵn sàng {len(style_uploads)} báo cáo mẫu văn phong")
        else:
            st.markdown(
                """
                <div class="section-card">
                    <h3>Quy chuẩn trình diễn tích hợp sẵn</h3>
                    <p class="small-note">Bản trình diễn đã có quy chuẩn văn phong giả lập nên có thể tạo báo cáo hoàn chỉnh mà không cần tải lên tài liệu công ty.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("### Quy tắc tách biệt")
        st.markdown("- **Báo cáo mẫu:** cách diễn đạt, giọng văn và cấu trúc")
        st.markdown("- **Bằng chứng kiểm toán:** dữ liệu của cuộc kiểm toán hiện tại")
        st.markdown("- **Dữ liệu do con người nhập:** chương trình, đánh giá và phê duyệt")

payload = collect_payload()

with draft_tab:
    render_section_header(
        "tao-bao-cao",
        "03",
        "Lập hồ sơ và dự thảo báo cáo",
        "Tạo dự thảo có cấu trúc, duy trì nguồn gốc bằng chứng và chạy đánh giá chất lượng trong giới hạn an toàn.",
    )
    st.markdown("### Tạo báo cáo có kiểm soát")
    st.caption(
        "Chế độ tự động chấm điểm từng dự thảo và chỉnh sửa tối đa ba lần. Điểm đạt yêu cầu là 85."
    )
    generate_col, note_col = st.columns([0.34, 0.66])
    with generate_col:
        generate_clicked = st.button(
            "Tạo dự thảo báo cáo",
            type="primary",
            width="stretch",
        )
    with note_col:
        st.caption(
            "Tệp tải lên chỉ được sử dụng trong chế độ trực tiếp. Tài liệu được tạo luôn được đánh dấu là dự thảo."
        )

    if generate_clicked:
        use_live_api = generation_mode == "Live OpenAI API" and api_ready
        try:
            with st.spinner(
                "Đang tạo dự thảo bằng OpenAI API..." if use_live_api else "Đang tạo dự thảo trình diễn..."
            ):
                if use_live_api:
                    input_files = convert_uploads(style_uploads, "style") + convert_uploads(
                        evidence_uploads, "evidence"
                    )
                    report = generate_with_openai(
                        payload,
                        st.session_state.finding_rows,
                        input_files,
                    )
                    st.session_state.generated_mode = "OpenAI API"
                    grade = lambda draft: grade_with_openai(payload, draft, input_files)
                    revise = lambda draft, review: revise_with_openai(
                        payload,
                        draft,
                        review.revision_instructions,
                        input_files,
                    )
                else:
                    report = build_demo_report(payload, st.session_state.finding_rows)
                    st.session_state.generated_mode = "Bản trình diễn"
                    grade = lambda draft: build_demo_assessment(payload, draft)
                    # The deterministic demo cannot safely manufacture missing facts.
                    revise = lambda draft, _review: draft

                if automation_enabled:
                    result = run_automation_loop(report, grade, revise)
                    report = result.report
                    assessment = result.assessment
                    st.session_state.revision_cycles = result.revision_cycles
                    st.session_state.automation_stop_reason = result.stop_reason
                    st.session_state.automation_history = [
                        {
                            "Vòng": item.round_number,
                            "Điểm": item.score,
                            "Kết quả": status_vi(item.status),
                            "Vấn đề": item.issue_count,
                        }
                        for item in result.history
                    ]
                else:
                    assessment = grade(report)
                    st.session_state.revision_cycles = 0
                    st.session_state.automation_stop_reason = "single_grade"
                    st.session_state.automation_history = [
                        {
                            "Vòng": 1,
                            "Điểm": assessment.overall_score,
                            "Kết quả": status_vi(assessment.status),
                            "Vấn đề": len(assessment.issues),
                        }
                    ]
                st.session_state.generated_report = report.model_dump()
                st.session_state.generated_critic = assessment.model_dump()
                saved = save_generated_version(
                    payload,
                    report,
                    assessment,
                    generated_by=str(payload.get("prepared_by") or "Không rõ người lập"),
                    generator_model=(
                        os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
                        if use_live_api
                        else "demo-generator-v1"
                    ),
                    critic_model=(
                        os.getenv("OPENAI_CRITIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6-terra"))
                        if use_live_api
                        else "demo-critic-v1"
                    ),
                    report_id=st.session_state.report_id,
                )
                st.session_state.report_id = str(saved.report_id)
                st.session_state.report_code = saved.report_code
                st.session_state.report_version_id = str(saved.report_version_id)
                st.session_state.version_number = saved.version_number
            stop_reason = st.session_state.automation_stop_reason
            if stop_reason == "passed":
                st.success("Tự động hóa đã chuyển dự thảo sang bước soát xét thủ công bắt buộc.")
            elif stop_reason == "evidence_blocker":
                st.error("Tự động hóa đã dừng: bằng chứng hợp đồng bị thiếu hoặc mâu thuẫn.")
            elif stop_reason == "revision_limit":
                st.warning("Tự động hóa đã dừng sau giới hạn an toàn ba lần chỉnh sửa.")
            else:
                st.success(f"Đã tạo dự thảo bằng {st.session_state.generated_mode}.")
        except Exception as exc:
            st.error(f"Tạo dự thảo thất bại: {exc}")

    if st.session_state.generated_report:
        generated_report = AuditReport.model_validate(st.session_state.generated_report)
        generated_critic = CriticAssessment.model_validate(st.session_state.generated_critic)
        gate_cols = st.columns(4)
        gate_cols[0].metric("Mã báo cáo", st.session_state.report_code or "Chưa lưu")
        gate_cols[1].metric("Phiên bản", f"V{st.session_state.version_number:02d}" if st.session_state.version_number else "—")
        gate_cols[2].metric("Điểm phản biện", f"{generated_critic.overall_score}/100")
        gate_cols[3].metric(
            "Cổng kiểm soát tự động",
            "Đạt" if generated_critic.status == "pass" else "Cần chỉnh sửa",
        )
        if st.session_state.automation_history:
            st.markdown("#### Lịch sử tự động hóa")
            st.dataframe(
                st.session_state.automation_history,
                hide_index=True,
                width="stretch",
            )
            st.caption(
                f"{st.session_state.revision_cycles} vòng chỉnh sửa · "
                f"ngưỡng đạt {PASSING_SCORE}/100 · vẫn bắt buộc phê duyệt thủ công"
            )
        render_report(generated_report)
    else:
        st.info("Hoàn tất phần chuẩn bị, sau đó tạo dự thảo đầu tiên.")

with review_tab:
    render_section_header(
        "soat-xet",
        "04",
        "Phản biện và soát xét thủ công",
        "Đánh giá bằng chứng, tính đầy đủ, phương pháp và quyết định phát hành của người soát xét.",
    )
    if not st.session_state.generated_report or not st.session_state.generated_critic:
        st.info("Hãy tạo dự thảo trước khi chạy các bước kiểm tra soát xét.")
    else:
        current_report = AuditReport.model_validate(st.session_state.generated_report)
        critic = CriticAssessment.model_validate(st.session_state.generated_critic)
        checks = run_qa(payload, current_report)
        score = completeness_score(checks)
        blockers = sum(item.level == "blocker" for item in checks)
        warnings = sum(item.level == "warning" for item in checks)

        st.markdown("### Bộ máy phản biện độc lập")
        critic_metrics = st.columns(5)
        critic_metrics[0].metric("Bằng chứng", critic.factual_evidence_score)
        critic_metrics[1].metric("Phương pháp", critic.methodology_compliance_score)
        critic_metrics[2].metric("Tính đầy đủ", critic.completeness_score)
        critic_metrics[3].metric("Văn phong", critic.writing_style_score)
        critic_metrics[4].metric("Tính nhất quán", critic.internal_consistency_score)
        if critic.status == "pass":
            st.success(f"**ĐẠT · {critic.overall_score}/100** — {qa_text_vi(critic.summary)}")
        else:
            st.error(f"**CẦN CHỈNH SỬA · {critic.overall_score}/100** — {qa_text_vi(critic.summary)}")
        for issue in critic.issues:
            message = (
                f"**{qa_text_vi(issue.title)}** — {qa_text_vi(issue.detail)}  \n"
                f"Hướng dẫn chỉnh sửa: {qa_text_vi(issue.revision_instruction)}"
            )
            if issue.severity == "blocker":
                st.error(message)
            else:
                st.warning(message)

        st.markdown("### Kiểm tra xác định trước khi phát hành")
        qa_metrics = st.columns(3)
        qa_metrics[0].metric("Mức đầy đủ theo quy tắc", f"{score}%")
        qa_metrics[1].metric("Nội dung bị chặn", blockers)
        qa_metrics[2].metric("Cảnh báo soát xét", warnings)

        for item in checks:
            message = f"**{qa_text_vi(item.title)}** — {qa_text_vi(item.detail)}"
            if item.level == "pass":
                st.success(message)
            elif item.level == "warning":
                st.warning(message)
            else:
                st.error(message)

        st.markdown("### Quyết định của người soát xét")
        decision = st.radio(
            "Quyết định",
            ["Return for updates", "Ready for technical review", "Human-approved final"],
            format_func=lambda value: {
                "Return for updates": "Trả lại để cập nhật",
                "Ready for technical review": "Sẵn sàng soát xét kỹ thuật",
                "Human-approved final": "Bản cuối đã được phê duyệt",
            }[value],
            horizontal=True,
            key="review_decision",
        )
        st.text_area(
            "Nhận xét của người soát xét",
            placeholder="Ghi lại các thay đổi cần thiết hoặc điều kiện phê duyệt...",
            key="reviewer_comment",
        )
        if blockers:
            st.error("Có thể xuất Word để soát xét, nhưng báo cáo vẫn còn nội dung bị chặn chưa xử lý.")
        else:
            st.success("Không còn nội dung bị chặn tự động. Vẫn bắt buộc soát xét kỹ thuật thủ công.")

        word_bytes = build_docx(current_report, payload)
        safe_code = get_template(st.session_state.report_type)["code"].lower()
        downloads = st.columns(2)
        downloads[0].download_button(
            "Tải xuống dự thảo Word",
            data=word_bytes,
            file_name=f"{safe_code}-draft-report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            width="stretch",
        )
        downloads[1].download_button(
            "Tải xuống dữ liệu có cấu trúc",
            data=json.dumps(current_report.model_dump(), ensure_ascii=False, indent=2),
            file_name=f"{safe_code}-draft-record.json",
            mime="application/json",
            width="stretch",
        )
        decision_label = {
            "Return for updates": "Trả lại để cập nhật",
            "Ready for technical review": "Sẵn sàng soát xét kỹ thuật",
            "Human-approved final": "Bản cuối đã được phê duyệt",
        }[decision]
        st.caption(f"Quyết định hiện tại của người soát xét: {decision_label}")

with warehouse_tab:
    render_section_header(
        "kho-du-lieu",
        "05",
        "Kho dữ liệu học tập",
        "Chỉ tiếp nhận báo cáo cuối đã phê duyệt và quản trị riêng từng mục đích sử dụng AI.",
    )
    st.markdown("### Chuyển báo cáo đã được phê duyệt thủ công")
    st.caption(
        "Chỉ báo cáo cuối cùng được con người chấp thuận rõ ràng mới được đưa vào kho dữ liệu quản trị. "
        "Quyền sử dụng cho học tập được phân loại riêng với việc phê duyệt báo cáo."
    )
    if not st.session_state.generated_report or not st.session_state.generated_critic:
        st.info("Hãy tạo và chấm điểm báo cáo trước khi chuẩn bị chuyển vào kho dữ liệu.")
    else:
        warehouse_report = AuditReport.model_validate(st.session_state.generated_report)
        warehouse_critic = CriticAssessment.model_validate(st.session_state.generated_critic)
        class_left, class_right = st.columns(2)
        with class_left:
            industry = st.selectbox(
                "Ngành",
                ["Manufacturing", "Distribution", "Financial services", "Not-for-profit", "Other"],
                format_func=lambda value: INDUSTRY_LABELS_VI[value],
            )
            audit_area = st.selectbox(
                "Lĩnh vực kiểm toán",
                ["Internal controls", "Inventory", "Grant expenditure", "Financial reporting", "Other"],
                format_func=lambda value: AUDIT_AREA_LABELS_VI[value],
            )
            jurisdiction = st.text_input("Khu vực pháp lý", value="Việt Nam")
        with class_right:
            confidentiality = st.selectbox(
                "Mức độ bảo mật",
                ["Internal", "Confidential", "Highly confidential"],
                index=1,
                format_func=lambda value: CONFIDENTIALITY_LABELS_VI[value],
            )
            learning_eligibility = st.selectbox(
                "Điều kiện sử dụng cho học tập",
                ["prohibited", "retrieval_only", "evaluation_only", "training_approved"],
                index=1,
                format_func=lambda value: LEARNING_LABELS_VI[value],
                help="Phê duyệt phát hành báo cáo không đồng nghĩa với phê duyệt sử dụng để huấn luyện mô hình.",
            )
            anonymized = st.checkbox(
                "Bản sao học tập đã được ẩn danh",
                help="Bắt buộc trước khi phân loại báo cáo là được phép huấn luyện.",
            )

        st.markdown("### Cổng phê duyệt")
        approved_by = st.text_input(
            "Người phê duyệt",
            value=st.session_state.get("engagement_partner", ""),
            key="warehouse_approver",
        )
        human_approved = st.checkbox(
            "Tôi xác nhận người có thẩm quyền đã phê duyệt báo cáo cuối cùng này",
            key="human_approval_confirmation",
        )
        if warehouse_critic.status != "pass":
            st.error("Không thể chuyển vì bộ máy phản biện yêu cầu chỉnh sửa.")
        elif st.session_state.get("review_decision") != "Human-approved final":
            st.warning("Hãy đặt quyết định soát xét thành Bản cuối đã được phê duyệt trước khi chuyển.")
        elif learning_eligibility == "training_approved" and not anonymized:
            st.warning("Báo cáo được phép huấn luyện phải có bản sao học tập đã ẩn danh.")
        else:
            st.success("Báo cáo đủ điều kiện chuyển có kiểm soát vào kho dữ liệu sau khi xác nhận.")

        transfer_blocked = (
            warehouse_critic.status != "pass"
            or st.session_state.get("review_decision") != "Human-approved final"
            or not human_approved
            or not approved_by.strip()
            or (learning_eligibility == "training_approved" and not anonymized)
        )
        if st.button(
            "Chuyển báo cáo đã phê duyệt",
            type="primary",
            disabled=transfer_blocked,
            width="stretch",
        ):
            try:
                if not st.session_state.report_version_id:
                    raise ValueError("Phiên bản báo cáo PostgreSQL chưa được tạo.")
                approve_client_release(
                    st.session_state.report_version_id,
                    approved_by=approved_by,
                    comment=st.session_state.get("reviewer_comment"),
                )
                report_id = transfer_approved_report(
                    payload,
                    warehouse_report,
                    warehouse_critic,
                    WarehouseClassification(
                        industry=industry,
                        audit_area=audit_area,
                        jurisdiction=jurisdiction,
                        confidentiality=confidentiality,
                        learning_eligibility=learning_eligibility,
                        anonymized=anonymized,
                    ),
                    approved_by=approved_by,
                    human_approved=human_approved,
                    generator_mode=st.session_state.generated_mode or "Unknown",
                    revision_cycles=st.session_state.revision_cycles,
                )
                st.success(f"Đã chuyển vào kho dữ liệu học tập với mã {report_id}.")
            except Exception as exc:
                st.error(f"Chuyển vào kho dữ liệu thất bại: {exc}")

        st.markdown("### Kho báo cáo đã phê duyệt")
        warehouse_rows = list_approved_reports()
        if warehouse_rows:
            warehouse_display_rows = [
                {
                    "Mã báo cáo": row["report_id"],
                    "Khách hàng": row["client_name"],
                    "Loại báo cáo": report_type_vi(row["report_type"]),
                    "Ngành": INDUSTRY_LABELS_VI.get(row["industry"], row["industry"]),
                    "Lĩnh vực kiểm toán": AUDIT_AREA_LABELS_VI.get(row["audit_area"], row["audit_area"]),
                    "Bảo mật": CONFIDENTIALITY_LABELS_VI.get(row["confidentiality"], row["confidentiality"]),
                    "Điều kiện học tập": LEARNING_LABELS_VI.get(row["learning_eligibility"], row["learning_eligibility"]),
                    "Đã ẩn danh": bool(row["anonymized"]),
                    "Người phê duyệt": row["approved_by"],
                    "Thời điểm phê duyệt": row["approved_at"],
                    "Điểm phản biện": row["critic_score"],
                }
                for row in warehouse_rows
            ]
            st.dataframe(warehouse_display_rows, width="stretch", hide_index=True)
        else:
            st.info("Chưa có báo cáo được phê duyệt nào được chuyển trong bản thử nghiệm cục bộ này.")

with gateway_tab:
    render_section_header(
        "cong-ai",
        "06",
        "Trung tâm tiếp nhận & trích xuất",
        "Nhận nguồn, trích xuất để soát xét, rồi mới tạm lưu và cấp quyền sử dụng AI.",
    )
    st.markdown("### Tiếp nhận báo cáo có kiểm soát")
    st.caption(
        "Tạm lưu báo cáo đã phê duyệt, soát xét cảnh báo xác thực, cấp quyền sử dụng AI cụ thể "
        "và tạo bản chụp dữ liệu bất biến. Bản thử nghiệm này không gửi dữ liệu đến OpenAI."
    )
    st.info(
        "Giới hạn bản thử nghiệm cục bộ: tệp chỉ được lưu trong cơ sở dữ liệu cổng tiếp nhận cục bộ. "
        "Đồng bộ truy xuất bên ngoài và tinh chỉnh mô hình vẫn bị vô hiệu hóa."
    )

    learning_readiness = assess_learning_readiness()
    st.markdown("### Vòng lặp cải tiến có quản trị")
    readiness_cols = st.columns(4)
    readiness_cols[0].metric("Tài liệu hợp lệ", learning_readiness.validated_documents)
    readiness_cols[1].metric("Sẵn sàng truy xuất", learning_readiness.retrieval_documents)
    readiness_cols[2].metric("Ví dụ đánh giá", learning_readiness.evaluation_examples)
    readiness_cols[3].metric(
        "Ví dụ huấn luyện ẩn danh",
        f"{learning_readiness.anonymized_training_examples}/{MIN_FINE_TUNING_EXAMPLES}",
    )
    if learning_readiness.training_ready:
        st.success(learning_readiness.next_action)
    else:
        st.info(learning_readiness.next_action)

    gateway_flash = st.session_state.pop("gateway_flash", None)
    if gateway_flash:
        flash_level, flash_message = gateway_flash
        if flash_level == "success":
            st.success(flash_message)
        else:
            st.error(flash_message)

    st.markdown("#### 1. Nhận và trích xuất trước khi tạm lưu")
    intake_left, intake_right = st.columns([0.9, 1.1])
    with intake_left:
        gateway_file = st.file_uploader(
            "Tệp báo cáo đã phê duyệt",
            type=["docx", "pdf", "json", "txt"],
            key="gateway_report_file",
            help="Chấp nhận DOCX, PDF có lớp văn bản, JSON có cấu trúc và TXT mã hóa UTF-8, tối đa 10 MB. PDF quét ảnh cần OCR riêng.",
        )
        gateway_report_type = st.selectbox(
            "Loại báo cáo",
            options=list(REPORT_TEMPLATES),
            format_func=report_type_vi,
            key="gateway_report_type",
        )
        gateway_uploader = st.text_input(
            "Người tải lên",
            value=st.session_state.get("prepared_by", ""),
            key="gateway_uploader",
        )
    with intake_right:
        gateway_training_input = st.text_area(
            "Bối cảnh hợp đồng gốc / dữ liệu đầu vào mong muốn cho mô hình",
            height=145,
            key="gateway_training_input",
            placeholder=(
                "Mô tả yêu cầu báo cáo, dữ liệu hợp đồng, phát hiện, tham chiếu bằng chứng và các "
                "ràng buộc cần thiết để tạo ra báo cáo cuối cùng đã được phê duyệt này."
            ),
            help=(
                "Bắt buộc cho đánh giá hoặc huấn luyện. Chỉ riêng báo cáo cuối cùng hữu ích cho truy xuất "
                "nhưng chưa phải là một ví dụ huấn luyện có giám sát hoàn chỉnh."
            ),
        )
        gateway_upload_authorized = st.checkbox(
            "Tôi có thẩm quyền tạm lưu báo cáo này trong bản thử nghiệm có kiểm soát",
            key="gateway_upload_authorized",
        )

    if gateway_file is not None:
        extraction_preview = preview_report_upload(
            gateway_file.name, gateway_file.getvalue()
        )
        preview_cols = st.columns(4)
        preview_cols[0].metric("Trạng thái trích xuất", "Sẵn sàng" if extraction_preview.validation.valid else "Bị chặn")
        preview_cols[1].metric("Ký tự", extraction_preview.character_count)
        preview_cols[2].metric("Từ", extraction_preview.word_count)
        preview_cols[3].metric("Dòng", extraction_preview.line_count)
        for message in extraction_preview.validation.messages:
            rendered = (
                f"**{message.rule_code}** — "
                f"{validation_detail_vi(message.rule_code, message.detail)}"
            )
            if message.level == "blocker":
                st.error(rendered)
            else:
                st.warning(rendered)
        if extraction_preview.preview:
            with st.expander("Xem trước nội dung đã trích xuất", expanded=True):
                st.text(extraction_preview.preview)
                if extraction_preview.character_count > len(extraction_preview.preview):
                    st.caption("Bản xem trước được giới hạn ở 4.000 ký tự; toàn bộ nội dung chỉ được lưu sau khi tạm lưu có thẩm quyền.")
        else:
            st.info("Chưa có nội dung có thể trích xuất. Hãy xử lý các lỗi đang chặn trước khi tạm lưu.")

    if st.button(
        "Xác nhận tạm lưu nguồn đã trích xuất",
        type="primary",
        disabled=gateway_file is None or not gateway_uploader.strip() or not gateway_upload_authorized,
        key="gateway_stage_button",
    ):
        try:
            receipt = stage_report_upload(
                gateway_file.name,
                gateway_file.getvalue(),
                media_type=getattr(gateway_file, "type", None),
                report_type=gateway_report_type,
                training_input=gateway_training_input,
                uploaded_by=gateway_uploader,
                upload_authorized=gateway_upload_authorized,
            )
            if receipt.status == "VALIDATED":
                st.session_state.gateway_flash = (
                    "success",
                    f"{receipt.upload_id} đã vượt qua xác thực cấu trúc và sẵn sàng cho soát xét quản trị.",
                )
            else:
                st.session_state.gateway_flash = (
                    "error",
                    f"{receipt.upload_id} đã bị cách ly. Hãy xem các kết quả xác thực đang chặn xử lý.",
                )
            st.rerun()
        except Exception as exc:
            st.error(f"Tạm lưu qua cổng tiếp nhận thất bại: {exc}")

    gateway_rows = list_gateway_uploads()
    gateway_metrics = st.columns(4)
    gateway_metrics[0].metric("Đã tải lên", len(gateway_rows))
    gateway_metrics[1].metric(
        "Đã xác thực", sum(row["validation_status"] == "VALIDATED" for row in gateway_rows)
    )
    gateway_metrics[2].metric(
        "Đã cách ly", sum(row["validation_status"] == "QUARANTINED" for row in gateway_rows)
    )
    gateway_metrics[3].metric(
        "Được phép huấn luyện",
        sum("TRAINING" in row["approved_uses"] for row in gateway_rows),
    )

    if gateway_rows:
        display_rows = [
            {
                "Mã tải lên": row["upload_id"],
                "Tệp": row["source_name"],
                "Loại báo cáo": report_type_vi(row["report_type"]),
                "Trạng thái": status_vi(row["validation_status"]),
                "Đã ẩn danh": bool(row["anonymized"]),
                "Mục đích được phép": approved_uses_vi(row["approved_uses"]),
                "Người tải lên": row["uploaded_by"],
            }
            for row in gateway_rows
        ]
        st.dataframe(display_rows, width="stretch", hide_index=True)

        st.markdown("#### 2. Soát xét và phê duyệt mục đích sử dụng AI cụ thể")
        upload_options = {
            f"{row['upload_id']} · {row['source_name']} · {row['validation_status']}": row["upload_id"]
            for row in gateway_rows
        }
        selected_upload_label = st.selectbox(
            "Báo cáo trong cổng tiếp nhận",
            options=list(upload_options),
            key="gateway_selected_upload",
        )
        selected_upload_id = upload_options[selected_upload_label]
        selected_upload = get_gateway_upload(selected_upload_id)
        if selected_upload:
            detail_cols = st.columns(4)
            detail_cols[0].metric("Trạng thái", status_vi(selected_upload["validation_status"]))
            detail_cols[1].metric("Số ký tự", selected_upload["extracted_characters"])
            detail_cols[2].metric("Dung lượng", f"{selected_upload['byte_size'] / 1024:.1f} KB")
            detail_cols[3].metric("SHA-256", selected_upload["content_checksum"][:12] + "…")
            for message in selected_upload["validation_messages"]:
                rendered = f"**{message['rule_code']}** — {validation_detail_vi(message['rule_code'], message['detail'])}"
                if message["level"] == "blocker":
                    st.error(rendered)
                else:
                    st.warning(rendered)
            if selected_upload["extracted_text"]:
                with st.expander("Nội dung đã trích xuất trong kho tạm", expanded=False):
                    st.text(selected_upload["extracted_text"][:4_000])
                    if selected_upload["extracted_characters"] > 4_000:
                        st.caption("Bản xem trước được giới hạn ở 4.000 ký tự.")

        approval_left, approval_right = st.columns(2)
        with approval_left:
            gateway_use_type = st.selectbox(
                "Mục đích sử dụng AI được phê duyệt",
                ["RETRIEVAL", "EVALUATION", "TRAINING"],
                key="gateway_use_type",
                format_func=lambda value: USE_LABELS_VI[value],
                help="Mỗi mục đích cần một quyết định riêng được ghi nhận.",
            )
            gateway_approver = st.text_input(
                "Người phê duyệt sử dụng AI",
                value=st.session_state.get("engagement_partner", ""),
                key="gateway_approver",
            )
            gateway_anonymized = st.checkbox(
                "Tôi đã soát xét bản sao học tập và xác nhận dữ liệu đã được ẩn danh",
                value=bool(selected_upload and selected_upload["anonymized"]),
                key="gateway_anonymized",
                help="Bắt buộc khi phê duyệt huấn luyện; đặc biệt khuyến nghị cho mọi mục đích học tập.",
            )
        with approval_right:
            gateway_approval_notes = st.text_area(
                "Ghi chú quyết định",
                height=95,
                key="gateway_approval_notes",
                placeholder="Ghi lại phạm vi, điều kiện, nội dung loại trừ hoặc yêu cầu lưu giữ.",
            )
            gateway_authority_confirmed = st.checkbox(
                "Tôi có thẩm quyền phê duyệt mục đích sử dụng AI cụ thể này",
                key="gateway_authority_confirmed",
            )

        approval_blocked = (
            not selected_upload
            or selected_upload["validation_status"] != "VALIDATED"
            or not gateway_approver.strip()
            or not gateway_authority_confirmed
            or (gateway_use_type == "TRAINING" and not gateway_anonymized)
        )
        if st.button(
            "Ghi nhận phê duyệt sử dụng AI",
            type="primary",
            disabled=approval_blocked,
            key="gateway_approve_button",
        ):
            try:
                approve_gateway_use(
                    selected_upload_id,
                    gateway_use_type,
                    approved_by=gateway_approver,
                    anonymized=gateway_anonymized,
                    authority_confirmed=gateway_authority_confirmed,
                    notes=gateway_approval_notes,
                )
                st.session_state.gateway_flash = (
                    "success",
                    f"{selected_upload_id} đã được phê duyệt cho mục đích {USE_LABELS_VI[gateway_use_type].lower()}.",
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Phê duyệt sử dụng AI thất bại: {exc}")
    else:
        st.info("Chưa có báo cáo được tạm lưu. Hãy tải lên một báo cáo mẫu giả lập hoặc đã ẩn danh ở trên.")

    st.markdown("#### 3. Tạo bản chụp dữ liệu bất biến")
    dataset_left, dataset_right = st.columns([0.65, 0.35])
    with dataset_left:
        gateway_dataset_use = st.selectbox(
            "Mục đích của bộ dữ liệu",
            ["RETRIEVAL", "EVALUATION", "TRAINING"],
            key="gateway_dataset_use",
            format_func=lambda value: USE_LABELS_VI[value],
        )
        gateway_dataset_creator = st.text_input(
            "Người tạo bộ dữ liệu",
            value=st.session_state.get("prepared_by", ""),
            key="gateway_dataset_creator",
        )
    with dataset_right:
        st.caption(
            f"Bản chụp huấn luyện có ít hơn {MIN_FINE_TUNING_EXAMPLES} ví dụ sẽ được đánh dấu "
            "Chỉ xem trước và chưa thể xem là sẵn sàng triển khai."
        )
        if st.button(
            "Tạo bản chụp dữ liệu",
            disabled=not gateway_dataset_creator.strip(),
            key="gateway_build_dataset",
            width="stretch",
        ):
            try:
                dataset = build_dataset_export(
                    gateway_dataset_use,
                    created_by=gateway_dataset_creator,
                )
                st.session_state.gateway_dataset_content = dataset.content
                st.session_state.gateway_dataset_filename = dataset.filename
                st.session_state.gateway_dataset_status = dataset.status
                st.session_state.gateway_dataset_id = dataset.dataset_id
            except Exception as exc:
                st.error(f"Tạo bộ dữ liệu thất bại: {exc}")

    if st.session_state.gateway_dataset_content:
        dataset_status = st.session_state.gateway_dataset_status
        if dataset_status == "READY":
            st.success(
                f"{st.session_state.gateway_dataset_id} đã sẵn sàng dưới dạng bản chụp cục bộ có quản trị."
            )
        else:
            st.warning(
                f"{st.session_state.gateway_dataset_id} là bản chụp xem trước. Hãy bổ sung thêm "
                "ví dụ đã phê duyệt và đánh giá chất lượng trước mọi tác vụ tinh chỉnh mô hình."
            )
        st.download_button(
            "Tải xuống bản chụp JSONL có quản trị",
            data=st.session_state.gateway_dataset_content,
            file_name=st.session_state.gateway_dataset_filename,
            mime="application/x-ndjson",
            key="gateway_download_dataset",
        )

    gateway_datasets = list_gateway_datasets()
    if gateway_datasets:
        gateway_dataset_rows = [
            {
                "Mã bộ dữ liệu": row["dataset_id"],
                "Mục đích": USE_LABELS_VI.get(row["use_type"], row["use_type"]),
                "Trạng thái": status_vi(row["dataset_status"]),
                "Số mục": row["item_count"],
                "Mã kiểm tra nội dung": row["content_checksum"],
                "Người tạo": row["created_by"],
                "Thời điểm tạo": row["created_at"],
            }
            for row in gateway_datasets
        ]
        st.dataframe(gateway_dataset_rows, width="stretch", hide_index=True)

    st.markdown("#### Đồng bộ bên ngoài")
    sync_col, boundary_col = st.columns([0.3, 0.7])
    with sync_col:
        st.button(
            "Gửi bộ dữ liệu đến OpenAI",
            disabled=True,
            help="Chủ động vô hiệu hóa cho đến khi cấu hình lưu giữ, xóa dữ liệu, thông tin xác thực và kiểm soát truy cập bên ngoài.",
            width="stretch",
        )
    with boundary_col:
        st.caption(
            "Giai đoạn bảo mật tiếp theo: vai trò được xác thực, lưu trữ đối tượng có quản lý, quét mã độc, "
            "quản lý bí mật, xóa tệp tại nhà cung cấp, lịch lưu giữ và nhật ký kiểm toán môi trường vận hành."
        )

st.markdown(
    """
    <div class="app-footer">
        <span>◆ Audit Automation Pipeline · Không gian lập báo cáo</span>
        <span>Dự thảo do AI hỗ trợ · Phê duyệt chuyên môn vẫn bắt buộc</span>
    </div>
    """,
    unsafe_allow_html=True,
)
