BEGIN;

CREATE SEQUENCE IF NOT EXISTS core.report_code_sequence START WITH 1;

CREATE OR REPLACE FUNCTION core.next_report_code()
RETURNS varchar LANGUAGE sql AS $$
    SELECT 'RPT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
           lpad(nextval('core.report_code_sequence')::text, 6, '0');
$$;

INSERT INTO core.report_category (category_code, category_name_vi)
VALUES
    ('AGREED_UPON_PROCEDURES', 'Báo cáo các thủ tục thỏa thuận trước'),
    ('GRANT_EXPENDITURE', 'Báo cáo xác nhận chi tiêu nguồn tài trợ')
ON CONFLICT (category_code) DO UPDATE
SET category_name_vi = EXCLUDED.category_name_vi,
    is_active = true;

COMMIT;
