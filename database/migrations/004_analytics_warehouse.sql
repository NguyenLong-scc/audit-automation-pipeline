BEGIN;

CREATE SCHEMA IF NOT EXISTS warehouse;

-- The warehouse deliberately excludes client legal names, report bodies, evidence text,
-- and management-response text. It contains analytical keys, classifications, statuses,
-- and counts only. Detailed confidential content remains in the controlled core schema.

CREATE TABLE IF NOT EXISTS warehouse.dim_date (
    date_key integer PRIMARY KEY,
    calendar_date date NOT NULL UNIQUE,
    day_of_month smallint NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    month_number smallint NOT NULL CHECK (month_number BETWEEN 1 AND 12),
    month_name_vi varchar(20) NOT NULL,
    quarter_number smallint NOT NULL CHECK (quarter_number BETWEEN 1 AND 4),
    year_number smallint NOT NULL,
    iso_week smallint NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    is_weekend boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse.dim_client (
    client_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id uuid NOT NULL UNIQUE,
    client_code varchar(30) NOT NULL UNIQUE,
    industry_code varchar(50) NOT NULL,
    confidentiality_level varchar(30) NOT NULL,
    source_created_at timestamptz NOT NULL,
    warehouse_synced_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS warehouse.dim_report_category (
    category_key smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id smallint NOT NULL UNIQUE,
    category_code varchar(40) NOT NULL UNIQUE,
    category_name_vi varchar(200) NOT NULL,
    is_active boolean NOT NULL,
    warehouse_synced_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS warehouse.dim_audit_area (
    audit_area_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_area varchar(100) NOT NULL UNIQUE,
    warehouse_synced_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS warehouse.dim_risk_rating (
    risk_key smallint PRIMARY KEY,
    risk_code varchar(20) NOT NULL UNIQUE,
    risk_name_vi varchar(30) NOT NULL,
    severity_order smallint NOT NULL UNIQUE CHECK (severity_order BETWEEN 1 AND 4),
    severity_weight numeric(4,2) NOT NULL CHECK (severity_weight > 0)
);

CREATE TABLE IF NOT EXISTS warehouse.fact_report_version (
    report_version_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_version_id uuid NOT NULL UNIQUE,
    report_id uuid NOT NULL,
    report_code varchar(30) NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    created_date_key integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    client_key bigint NOT NULL REFERENCES warehouse.dim_client(client_key),
    category_key smallint NOT NULL REFERENCES warehouse.dim_report_category(category_key),
    lifecycle_status varchar(30) NOT NULL,
    version_status varchar(30) NOT NULL,
    language_code char(2) NOT NULL,
    finding_count integer NOT NULL DEFAULT 0 CHECK (finding_count >= 0),
    critical_finding_count integer NOT NULL DEFAULT 0 CHECK (critical_finding_count >= 0),
    high_finding_count integer NOT NULL DEFAULT 0 CHECK (high_finding_count >= 0),
    moderate_finding_count integer NOT NULL DEFAULT 0 CHECK (moderate_finding_count >= 0),
    low_finding_count integer NOT NULL DEFAULT 0 CHECK (low_finding_count >= 0),
    evidence_linked_finding_count integer NOT NULL DEFAULT 0
        CHECK (evidence_linked_finding_count >= 0),
    management_response_count integer NOT NULL DEFAULT 0
        CHECK (management_response_count >= 0),
    latest_critic_score smallint CHECK (latest_critic_score BETWEEN 0 AND 100),
    latest_critic_status varchar(30),
    was_client_approved boolean NOT NULL,
    source_created_at timestamptz NOT NULL,
    warehouse_synced_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_id, version_number)
);

CREATE TABLE IF NOT EXISTS warehouse.fact_finding (
    finding_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    finding_id uuid NOT NULL UNIQUE,
    report_version_key bigint NOT NULL
        REFERENCES warehouse.fact_report_version(report_version_key),
    finding_date_key integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    client_key bigint NOT NULL REFERENCES warehouse.dim_client(client_key),
    category_key smallint NOT NULL REFERENCES warehouse.dim_report_category(category_key),
    audit_area_key bigint NOT NULL REFERENCES warehouse.dim_audit_area(audit_area_key),
    risk_key smallint NOT NULL REFERENCES warehouse.dim_risk_rating(risk_key),
    finding_number integer NOT NULL CHECK (finding_number > 0),
    has_management_response boolean NOT NULL,
    has_evidence_reference boolean NOT NULL,
    finding_count smallint NOT NULL DEFAULT 1 CHECK (finding_count = 1),
    warehouse_synced_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_version_key, finding_number)
);

CREATE TABLE IF NOT EXISTS warehouse.fact_generation_run (
    generation_run_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    generation_run_id uuid NOT NULL UNIQUE,
    report_version_key bigint NOT NULL
        REFERENCES warehouse.fact_report_version(report_version_key),
    run_date_key integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    client_key bigint NOT NULL REFERENCES warehouse.dim_client(client_key),
    category_key smallint NOT NULL REFERENCES warehouse.dim_report_category(category_key),
    run_number integer NOT NULL CHECK (run_number > 0),
    generator_model varchar(100) NOT NULL,
    critic_model varchar(100),
    critic_score smallint CHECK (critic_score BETWEEN 0 AND 100),
    critic_status varchar(30),
    duration_milliseconds bigint CHECK (duration_milliseconds >= 0),
    completed boolean NOT NULL,
    generation_count smallint NOT NULL DEFAULT 1 CHECK (generation_count = 1),
    source_started_at timestamptz NOT NULL,
    warehouse_synced_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_version_key, run_number)
);

CREATE TABLE IF NOT EXISTS warehouse.fact_pipeline_event (
    pipeline_event_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_event_id bigint NOT NULL UNIQUE,
    report_version_key bigint NOT NULL
        REFERENCES warehouse.fact_report_version(report_version_key),
    event_date_key integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    client_key bigint NOT NULL REFERENCES warehouse.dim_client(client_key),
    category_key smallint NOT NULL REFERENCES warehouse.dim_report_category(category_key),
    event_status varchar(30) NOT NULL,
    rule_code varchar(80),
    event_count smallint NOT NULL DEFAULT 1 CHECK (event_count = 1),
    source_occurred_at timestamptz NOT NULL,
    warehouse_synced_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS warehouse.fact_approval_event (
    approval_event_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    approval_event_id uuid NOT NULL UNIQUE,
    report_version_key bigint NOT NULL
        REFERENCES warehouse.fact_report_version(report_version_key),
    event_date_key integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    client_key bigint NOT NULL REFERENCES warehouse.dim_client(client_key),
    category_key smallint NOT NULL REFERENCES warehouse.dim_report_category(category_key),
    event_type varchar(40) NOT NULL,
    actor_role varchar(50) NOT NULL,
    approval_event_count smallint NOT NULL DEFAULT 1 CHECK (approval_event_count = 1),
    source_occurred_at timestamptz NOT NULL,
    warehouse_synced_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON SCHEMA warehouse IS
    'De-identified analytical star schema for internal audit reporting and AI-governance metrics.';
COMMENT ON TABLE warehouse.fact_report_version IS
    'Grain: one row per immutable report version.';
COMMENT ON TABLE warehouse.fact_finding IS
    'Grain: one row per audit finding in one report version; descriptive finding text is excluded.';
COMMENT ON TABLE warehouse.fact_generation_run IS
    'Grain: one row per AI generation and critic run.';
COMMENT ON TABLE warehouse.fact_pipeline_event IS
    'Grain: one validation, quarantine, or loading event.';
COMMENT ON TABLE warehouse.fact_approval_event IS
    'Grain: one human approval or rejection event; actor identity and comments are excluded.';

INSERT INTO warehouse.dim_date (
    date_key, calendar_date, day_of_month, month_number, month_name_vi,
    quarter_number, year_number, iso_week, is_weekend
)
SELECT
    to_char(day_value, 'YYYYMMDD')::integer,
    day_value,
    extract(day FROM day_value)::smallint,
    extract(month FROM day_value)::smallint,
    CASE extract(month FROM day_value)::integer
        WHEN 1 THEN 'Tháng 1' WHEN 2 THEN 'Tháng 2' WHEN 3 THEN 'Tháng 3'
        WHEN 4 THEN 'Tháng 4' WHEN 5 THEN 'Tháng 5' WHEN 6 THEN 'Tháng 6'
        WHEN 7 THEN 'Tháng 7' WHEN 8 THEN 'Tháng 8' WHEN 9 THEN 'Tháng 9'
        WHEN 10 THEN 'Tháng 10' WHEN 11 THEN 'Tháng 11' ELSE 'Tháng 12'
    END,
    extract(quarter FROM day_value)::smallint,
    extract(year FROM day_value)::smallint,
    extract(week FROM day_value)::smallint,
    extract(isodow FROM day_value) IN (6, 7)
FROM generate_series(date '2020-01-01', date '2040-12-31', interval '1 day') AS day_series(day_value)
ON CONFLICT (date_key) DO NOTHING;

INSERT INTO warehouse.dim_risk_rating (
    risk_key, risk_code, risk_name_vi, severity_order, severity_weight
)
VALUES
    (1, 'LOW', 'Thấp', 1, 1.00),
    (2, 'MODERATE', 'Trung bình', 2, 2.00),
    (3, 'HIGH', 'Cao', 3, 3.00),
    (4, 'CRITICAL', 'Nghiêm trọng', 4, 4.00)
ON CONFLICT (risk_key) DO UPDATE
SET risk_code = EXCLUDED.risk_code,
    risk_name_vi = EXCLUDED.risk_name_vi,
    severity_order = EXCLUDED.severity_order,
    severity_weight = EXCLUDED.severity_weight;

CREATE OR REPLACE FUNCTION warehouse.refresh_audit_warehouse()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO warehouse.dim_client (
        client_id, client_code, industry_code, confidentiality_level, source_created_at
    )
    SELECT client_id, client_code, industry_code, confidentiality_level, created_at
    FROM core.client
    ON CONFLICT (client_id) DO UPDATE
    SET client_code = EXCLUDED.client_code,
        industry_code = EXCLUDED.industry_code,
        confidentiality_level = EXCLUDED.confidentiality_level,
        source_created_at = EXCLUDED.source_created_at,
        warehouse_synced_at = now();

    INSERT INTO warehouse.dim_report_category (
        category_id, category_code, category_name_vi, is_active
    )
    SELECT category_id, category_code, category_name_vi, is_active
    FROM core.report_category
    ON CONFLICT (category_id) DO UPDATE
    SET category_code = EXCLUDED.category_code,
        category_name_vi = EXCLUDED.category_name_vi,
        is_active = EXCLUDED.is_active,
        warehouse_synced_at = now();

    INSERT INTO warehouse.dim_audit_area (audit_area)
    SELECT DISTINCT btrim(audit_area)
    FROM core.finding
    WHERE nullif(btrim(audit_area), '') IS NOT NULL
    ON CONFLICT (audit_area) DO UPDATE
    SET warehouse_synced_at = now();

    INSERT INTO warehouse.fact_report_version (
        report_version_id, report_id, report_code, version_number,
        created_date_key, client_key, category_key, lifecycle_status,
        version_status, language_code, finding_count, critical_finding_count,
        high_finding_count, moderate_finding_count, low_finding_count,
        evidence_linked_finding_count, management_response_count,
        latest_critic_score, latest_critic_status, was_client_approved,
        source_created_at
    )
    SELECT
        rv.report_version_id,
        r.report_id,
        r.report_code,
        rv.version_number,
        to_char(rv.created_at AT TIME ZONE 'Asia/Ho_Chi_Minh', 'YYYYMMDD')::integer,
        dc.client_key,
        drc.category_key,
        r.lifecycle_status,
        rv.version_status,
        rv.language_code,
        coalesce(fs.finding_count, 0),
        coalesce(fs.critical_count, 0),
        coalesce(fs.high_count, 0),
        coalesce(fs.moderate_count, 0),
        coalesce(fs.low_count, 0),
        coalesce(fs.evidence_count, 0),
        coalesce(fs.management_response_count, 0),
        latest_run.critic_score,
        latest_run.critic_status,
        rv.version_status = 'CLIENT_APPROVED',
        rv.created_at
    FROM core.report_version rv
    JOIN core.report r ON r.report_id = rv.report_id
    JOIN warehouse.dim_client dc ON dc.client_id = r.client_id
    JOIN warehouse.dim_report_category drc ON drc.category_id = r.category_id
    LEFT JOIN LATERAL (
        SELECT
            count(*)::integer AS finding_count,
            count(*) FILTER (WHERE risk_rating = 'CRITICAL')::integer AS critical_count,
            count(*) FILTER (WHERE risk_rating = 'HIGH')::integer AS high_count,
            count(*) FILTER (WHERE risk_rating = 'MODERATE')::integer AS moderate_count,
            count(*) FILTER (WHERE risk_rating = 'LOW')::integer AS low_count,
            count(*) FILTER (
                WHERE nullif(btrim(evidence_reference), '') IS NOT NULL
                  AND lower(btrim(evidence_reference)) NOT IN ('not provided', 'chưa cung cấp')
            )::integer AS evidence_count,
            count(*) FILTER (
                WHERE nullif(btrim(management_response), '') IS NOT NULL
                  AND lower(btrim(management_response)) NOT IN ('not provided', 'chưa cung cấp')
            )::integer AS management_response_count
        FROM core.finding f
        WHERE f.report_version_id = rv.report_version_id
    ) fs ON true
    LEFT JOIN LATERAL (
        SELECT critic_score, critic_status
        FROM core.generation_run gr
        WHERE gr.report_version_id = rv.report_version_id
        ORDER BY run_number DESC
        LIMIT 1
    ) latest_run ON true
    ON CONFLICT (report_version_id) DO UPDATE
    SET lifecycle_status = EXCLUDED.lifecycle_status,
        version_status = EXCLUDED.version_status,
        finding_count = EXCLUDED.finding_count,
        critical_finding_count = EXCLUDED.critical_finding_count,
        high_finding_count = EXCLUDED.high_finding_count,
        moderate_finding_count = EXCLUDED.moderate_finding_count,
        low_finding_count = EXCLUDED.low_finding_count,
        evidence_linked_finding_count = EXCLUDED.evidence_linked_finding_count,
        management_response_count = EXCLUDED.management_response_count,
        latest_critic_score = EXCLUDED.latest_critic_score,
        latest_critic_status = EXCLUDED.latest_critic_status,
        was_client_approved = EXCLUDED.was_client_approved,
        warehouse_synced_at = now();

    INSERT INTO warehouse.fact_finding (
        finding_id, report_version_key, finding_date_key, client_key,
        category_key, audit_area_key, risk_key, finding_number,
        has_management_response, has_evidence_reference
    )
    SELECT
        f.finding_id,
        frv.report_version_key,
        frv.created_date_key,
        frv.client_key,
        frv.category_key,
        daa.audit_area_key,
        drr.risk_key,
        f.finding_number,
        nullif(btrim(f.management_response), '') IS NOT NULL
            AND lower(btrim(f.management_response)) NOT IN ('not provided', 'chưa cung cấp'),
        nullif(btrim(f.evidence_reference), '') IS NOT NULL
            AND lower(btrim(f.evidence_reference)) NOT IN ('not provided', 'chưa cung cấp')
    FROM core.finding f
    JOIN warehouse.fact_report_version frv
      ON frv.report_version_id = f.report_version_id
    JOIN warehouse.dim_audit_area daa ON daa.audit_area = btrim(f.audit_area)
    JOIN warehouse.dim_risk_rating drr ON drr.risk_code = f.risk_rating
    ON CONFLICT (finding_id) DO UPDATE
    SET audit_area_key = EXCLUDED.audit_area_key,
        risk_key = EXCLUDED.risk_key,
        has_management_response = EXCLUDED.has_management_response,
        has_evidence_reference = EXCLUDED.has_evidence_reference,
        warehouse_synced_at = now();

    INSERT INTO warehouse.fact_generation_run (
        generation_run_id, report_version_key, run_date_key, client_key,
        category_key, run_number, generator_model, critic_model,
        critic_score, critic_status, duration_milliseconds, completed,
        source_started_at
    )
    SELECT
        gr.generation_run_id,
        frv.report_version_key,
        to_char(gr.started_at AT TIME ZONE 'Asia/Ho_Chi_Minh', 'YYYYMMDD')::integer,
        frv.client_key,
        frv.category_key,
        gr.run_number,
        gr.generator_model,
        gr.critic_model,
        gr.critic_score,
        gr.critic_status,
        CASE WHEN gr.completed_at IS NULL THEN NULL
             ELSE greatest(0, round(extract(epoch FROM (gr.completed_at - gr.started_at)) * 1000))::bigint
        END,
        gr.completed_at IS NOT NULL,
        gr.started_at
    FROM core.generation_run gr
    JOIN warehouse.fact_report_version frv
      ON frv.report_version_id = gr.report_version_id
    ON CONFLICT (generation_run_id) DO UPDATE
    SET critic_score = EXCLUDED.critic_score,
        critic_status = EXCLUDED.critic_status,
        duration_milliseconds = EXCLUDED.duration_milliseconds,
        completed = EXCLUDED.completed,
        warehouse_synced_at = now();

    INSERT INTO warehouse.fact_pipeline_event (
        pipeline_event_id, report_version_key, event_date_key, client_key,
        category_key, event_status, rule_code, source_occurred_at
    )
    SELECT
        pe.pipeline_event_id,
        frv.report_version_key,
        to_char(pe.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh', 'YYYYMMDD')::integer,
        frv.client_key,
        frv.category_key,
        pe.event_status,
        pe.rule_code,
        pe.occurred_at
    FROM governance.pipeline_event pe
    JOIN warehouse.fact_report_version frv
      ON frv.report_version_id = pe.report_version_id
    ON CONFLICT (pipeline_event_id) DO UPDATE
    SET event_status = EXCLUDED.event_status,
        rule_code = EXCLUDED.rule_code,
        warehouse_synced_at = now();

    INSERT INTO warehouse.fact_approval_event (
        approval_event_id, report_version_key, event_date_key, client_key,
        category_key, event_type, actor_role, source_occurred_at
    )
    SELECT
        ae.approval_event_id,
        frv.report_version_key,
        to_char(ae.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh', 'YYYYMMDD')::integer,
        frv.client_key,
        frv.category_key,
        ae.event_type,
        ae.actor_role,
        ae.occurred_at
    FROM core.approval_event ae
    JOIN warehouse.fact_report_version frv
      ON frv.report_version_id = ae.report_version_id
    ON CONFLICT (approval_event_id) DO UPDATE
    SET event_type = EXCLUDED.event_type,
        actor_role = EXCLUDED.actor_role,
        warehouse_synced_at = now();
END;
$$;

CREATE INDEX IF NOT EXISTS idx_fact_report_version_date_category
    ON warehouse.fact_report_version(created_date_key, category_key);
CREATE INDEX IF NOT EXISTS idx_fact_report_version_client_status
    ON warehouse.fact_report_version(client_key, version_status);
CREATE INDEX IF NOT EXISTS idx_fact_finding_risk_area
    ON warehouse.fact_finding(risk_key, audit_area_key);
CREATE INDEX IF NOT EXISTS idx_fact_finding_client_date
    ON warehouse.fact_finding(client_key, finding_date_key);
CREATE INDEX IF NOT EXISTS idx_fact_generation_model_date
    ON warehouse.fact_generation_run(generator_model, run_date_key);
CREATE INDEX IF NOT EXISTS idx_fact_pipeline_status_date
    ON warehouse.fact_pipeline_event(event_status, event_date_key);
CREATE INDEX IF NOT EXISTS idx_fact_approval_type_date
    ON warehouse.fact_approval_event(event_type, event_date_key);

CREATE OR REPLACE VIEW warehouse.v_report_overview AS
SELECT
    dd.year_number,
    dd.month_number,
    drc.category_code,
    drc.category_name_vi,
    count(*) AS report_version_count,
    count(DISTINCT frv.report_id) AS report_count,
    sum(frv.finding_count) AS finding_count,
    sum(frv.high_finding_count + frv.critical_finding_count) AS high_or_critical_count,
    round(avg(frv.latest_critic_score), 1) AS average_critic_score,
    count(*) FILTER (WHERE frv.was_client_approved) AS approved_version_count
FROM warehouse.fact_report_version frv
JOIN warehouse.dim_date dd ON dd.date_key = frv.created_date_key
JOIN warehouse.dim_report_category drc ON drc.category_key = frv.category_key
GROUP BY dd.year_number, dd.month_number, drc.category_code, drc.category_name_vi;

CREATE OR REPLACE VIEW warehouse.v_risk_summary AS
SELECT
    dd.year_number,
    dc.industry_code,
    daa.audit_area,
    drr.risk_code,
    drr.risk_name_vi,
    drr.severity_order,
    count(*) AS finding_count,
    sum(drr.severity_weight) AS weighted_risk_points
FROM warehouse.fact_finding ff
JOIN warehouse.dim_date dd ON dd.date_key = ff.finding_date_key
JOIN warehouse.dim_client dc ON dc.client_key = ff.client_key
JOIN warehouse.dim_audit_area daa ON daa.audit_area_key = ff.audit_area_key
JOIN warehouse.dim_risk_rating drr ON drr.risk_key = ff.risk_key
GROUP BY dd.year_number, dc.industry_code, daa.audit_area,
         drr.risk_code, drr.risk_name_vi, drr.severity_order;

CREATE OR REPLACE VIEW warehouse.v_pipeline_health AS
SELECT
    dd.calendar_date,
    fpe.event_status,
    coalesce(fpe.rule_code, 'NO_RULE') AS rule_code,
    count(*) AS event_count
FROM warehouse.fact_pipeline_event fpe
JOIN warehouse.dim_date dd ON dd.date_key = fpe.event_date_key
GROUP BY dd.calendar_date, fpe.event_status, coalesce(fpe.rule_code, 'NO_RULE');

SELECT warehouse.refresh_audit_warehouse();

COMMIT;
