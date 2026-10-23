from __future__ import annotations


COMMON_REQUIRED_FIELDS = [
    "client_name", "period_end", "prepared_by", "objective", "scope", "procedures", "conclusion",
]


def _demo(*, project: str, date: str, lead: str, objective: str, scope: str,
          procedures: str, conclusion: str, finding: dict) -> dict:
    return {
        "client_name": project, "period_end": date, "prepared_by": "Nhóm An ninh Công trường",
        "engagement_partner": lead, "objective": objective, "scope": scope,
        "procedures": procedures, "conclusion": conclusion, "findings": [finding],
    }


REPORT_TEMPLATES: dict[str, dict] = {
    "Site Security Assessment": {
        "code": "SSA", "label_vi": "Đánh giá an ninh công trường",
        "purpose": "Đánh giá các biện pháp bảo vệ con người, vật tư, thiết bị và khu vực thi công.",
        "sections": ["Tóm tắt điều hành", "Mục tiêu và phạm vi", "Phương pháp kiểm tra", "Kết luận", "Rủi ro chi tiết", "Giới hạn"],
        "required_fields": COMMON_REQUIRED_FIELDS,
        "style_profile": "Dùng ngôn ngữ thực tế, trung lập và hướng hành động. Tách rõ quan sát, yêu cầu công trường, nguyên nhân, tác động và hành động khắc phục. Không khẳng định công trường an toàn tuyệt đối; mọi kết luận phải có bằng chứng.",
        "demo": _demo(
            project="Dự án Riverside Tower", date="21 tháng 7 năm 2026", lead="N. Tran",
            objective="Đánh giá tính đầy đủ của kiểm soát ra vào, giám sát chu vi và bảo vệ thiết bị tại công trường.",
            scope="Cổng chính, kho vật tư, khu vực máy móc và hàng rào chu vi tại công trường Riverside Tower trong ca tối.",
            procedures="Đi bộ kiểm tra hiện trường, đối chiếu nhật ký khách ra vào, thử nghiệm chọn mẫu thẻ ra vào và phỏng vấn bảo vệ ca đêm.",
            conclusion="Các biện pháp nền tảng đã có, nhưng khu vực kho vật tư cần được kiểm soát tốt hơn trước khi nhận thiết bị giá trị cao.",
            finding={"title": "Kho vật tư chưa có kiểm soát ra vào nhất quán", "area": "Kiểm soát ra vào và vật tư", "risk_rating": "High", "condition": "Quan sát 3 lượt ra vào kho vật tư trong ca tối không có ghi nhận thẻ hoặc sổ bàn giao.", "criteria": "Kế hoạch an ninh công trường yêu cầu chỉ người được ủy quyền được vào kho và mọi lượt ra vào phải được ghi nhận.", "cause": "Khóa cửa kho sử dụng chung và chưa phân công người quản lý chìa khóa trong ca tối.", "effect": "Vật tư, dụng cụ và thiết bị nhỏ có thể bị thất thoát mà không xác định được người tiếp cận.", "recommendation": "Cấp thẻ hoặc chìa khóa theo danh sách ủy quyền, duy trì nhật ký số và kiểm tra ngoại lệ mỗi ngày.", "management_response": "Chỉ huy trưởng sẽ triển khai danh sách ủy quyền và tủ khóa có nhật ký trước ngày 31 tháng 7 năm 2026.", "evidence_reference": "Quan sát SEC-01 đến SEC-03; nhật ký bảo vệ ca tối ngày 18 tháng 7 năm 2026"},
        ),
    },
    "Worksite Safety Inspection": {
        "code": "WSI", "label_vi": "Kiểm tra an toàn công trường",
        "purpose": "Ghi nhận các điều kiện an toàn có thể ảnh hưởng đến người lao động và khách thăm công trường.",
        "sections": ["Tóm tắt", "Khu vực kiểm tra", "Quan sát và bằng chứng", "Rủi ro", "Hành động khắc phục", "Giới hạn"],
        "required_fields": COMMON_REQUIRED_FIELDS,
        "style_profile": "Ghi nhận quan sát theo thời điểm và vị trí cụ thể. Không suy diễn nguyên nhân hoặc tình trạng tuân thủ nếu không có bằng chứng. Ưu tiên hành động khắc phục rõ chủ sở hữu và thời hạn.",
        "demo": _demo(
            project="Dự án Metro Depot", date="21 tháng 7 năm 2026", lead="H. Le",
            objective="Kiểm tra điều kiện an toàn tại khu vực thi công trên cao trước ca làm việc buổi sáng.",
            scope="Giàn giáo tầng 4, lối đi tiếp cận và khu vực tập kết vật liệu tại khối B.",
            procedures="Quan sát trực tiếp trước ca, kiểm tra biển báo, đối chiếu danh sách kiểm tra giàn giáo và phỏng vấn giám sát hiện trường.",
            conclusion="Cần hoàn tất che chắn mép sàn và xác nhận lại việc kiểm tra giàn giáo trước khi tiếp tục công việc tại tầng 4.",
            finding={"title": "Mép sàn tại lối tiếp cận giàn giáo chưa được che chắn hoàn chỉnh", "area": "Làm việc trên cao", "risk_rating": "Critical", "condition": "Một đoạn khoảng 2 mét cạnh lối tiếp cận tầng 4 chỉ có dây cảnh báo, không có lan can hoặc tấm chắn.", "criteria": "Kế hoạch an toàn dự án yêu cầu bảo vệ mép sàn đầy đủ trước khi người lao động tiếp cận khu vực có nguy cơ ngã.", "cause": "Hạng mục lan can tạm bị tháo để vận chuyển vật liệu và chưa được lắp lại.", "effect": "Người lao động hoặc khách thăm có nguy cơ ngã cao độ.", "recommendation": "Dừng tiếp cận khu vực, lắp lại lan can đạt yêu cầu và xác nhận bằng kiểm tra của cán bộ an toàn trước khi mở lại.", "management_response": "Giám sát hiện trường đã cô lập khu vực và sẽ xác nhận khắc phục trước ca chiều.", "evidence_reference": "Ảnh SAFE-11; checklist giàn giáo SCF-B4 ngày 21 tháng 7 năm 2026"},
        ),
    },
    "Contractor Access Review": {
        "code": "CAR", "label_vi": "Soát xét quyền ra vào của nhà thầu",
        "purpose": "Đánh giá việc cấp, thu hồi và giám sát quyền ra vào của nhà thầu và khách thăm.",
        "sections": ["Mục đích", "Phạm vi", "Thủ tục", "Ngoại lệ", "Hành động đề xuất", "Giới hạn"],
        "required_fields": COMMON_REQUIRED_FIELDS,
        "style_profile": "Đối chiếu từng quyền ra vào với hồ sơ ủy quyền. Không nêu tên cá nhân không cần thiết; sử dụng mã thẻ và bằng chứng đã được tối thiểu hóa.",
        "demo": _demo(
            project="Dự án Cảng Logistics East", date="21 tháng 7 năm 2026", lead="P. Nguyen",
            objective="Soát xét việc thu hồi thẻ ra vào sau khi nhân sự nhà thầu kết thúc nhiệm vụ.",
            scope="Danh sách thẻ nhà thầu phụ hết hiệu lực trong tháng 6 năm 2026 và nhật ký cổng chính.",
            procedures="Đối chiếu danh sách thẻ hết hiệu lực với danh sách nhân sự nhà thầu, nhật ký cổng và biên bản bàn giao thẻ.",
            conclusion="Quy trình thu hồi thẻ đang vận hành nhưng cần bổ sung đối soát định kỳ để xử lý các thẻ chưa được thu hồi đúng hạn.",
            finding={"title": "Thẻ nhà thầu hết hạn chưa được khóa kịp thời", "area": "Quản lý thẻ ra vào", "risk_rating": "Moderate", "condition": "2 trong 18 thẻ hết hạn vẫn hiển thị trạng thái hoạt động trong hệ thống kiểm soát ra vào sau ngày kết thúc nhiệm vụ.", "criteria": "Quy trình ra vào yêu cầu vô hiệu hóa thẻ nhà thầu ngay khi nhiệm vụ kết thúc hoặc thẻ hết hạn.", "cause": "Danh sách nhân sự kết thúc nhiệm vụ được gửi thủ công và chưa có bước đối soát hằng ngày.", "effect": "Người không còn được ủy quyền có thể tiếp cận công trường ngoài thời hạn cần thiết.", "recommendation": "Tự động hóa danh sách hết hạn và thiết lập đối soát hằng ngày giữa ban chỉ huy, bảo vệ và quản trị thẻ.", "management_response": "Bộ phận an ninh sẽ thực hiện đối soát hằng ngày từ tuần tới.", "evidence_reference": "Báo cáo thẻ ACCESS-JUN-26; nhật ký cổng ngày 3 tháng 7 năm 2026"},
        ),
    },
}


def get_template(report_type: str) -> dict:
    try:
        return REPORT_TEMPLATES[report_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported report type: {report_type}") from exc
