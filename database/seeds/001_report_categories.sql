INSERT INTO core.report_category (category_code, category_name_vi)
VALUES
    ('INTERNAL_CONTROL', 'Báo cáo kiểm toán hệ thống kiểm soát nội bộ'),
    ('CREDIT_ACTIVITY', 'Báo cáo kiểm toán hoạt động tín dụng'),
    ('FINANCIAL_STATEMENT', 'Báo cáo kiểm toán báo cáo tài chính'),
    ('COMPLIANCE', 'Báo cáo kiểm toán tuân thủ'),
    ('IT_AUDIT', 'Báo cáo kiểm toán công nghệ thông tin')
ON CONFLICT (category_code) DO UPDATE
SET category_name_vi = EXCLUDED.category_name_vi,
    is_active = true;
