BEGIN;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS core.report_category (
    category_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_code varchar(40) NOT NULL UNIQUE,
    category_name_vi varchar(200) NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.client (
    client_id uuid PRIMARY KEY,
    client_code varchar(30) NOT NULL UNIQUE,
    legal_name varchar(300) NOT NULL,
    industry_code varchar(50) NOT NULL,
    confidentiality_level varchar(30) NOT NULL DEFAULT 'CONFIDENTIAL'
        CHECK (confidentiality_level IN ('INTERNAL', 'CONFIDENTIAL', 'HIGHLY_CONFIDENTIAL')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.report (
    report_id uuid PRIMARY KEY,
    report_code varchar(30) NOT NULL UNIQUE,
    category_id smallint NOT NULL REFERENCES core.report_category(category_id),
    client_id uuid NOT NULL REFERENCES core.client(client_id),
    lifecycle_status varchar(30) NOT NULL DEFAULT 'DRAFT'
        CHECK (lifecycle_status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'REVOKED')),
    created_by varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.report_version (
    report_version_id uuid PRIMARY KEY,
    report_id uuid NOT NULL REFERENCES core.report(report_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    language_code char(2) NOT NULL DEFAULT 'vi' CHECK (language_code = 'vi'),
    report_title text NOT NULL,
    structured_report jsonb NOT NULL,
    content_checksum char(64) NOT NULL,
    version_status varchar(30) NOT NULL DEFAULT 'DRAFT'
        CHECK (version_status IN ('DRAFT', 'IN_REVIEW', 'CLIENT_APPROVED', 'REVOKED')),
    generator_model varchar(100),
    prompt_version varchar(50),
    created_by varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_id, version_number),
    UNIQUE (report_version_id, report_id)
);

CREATE TABLE IF NOT EXISTS core.finding (
    finding_id uuid PRIMARY KEY,
    report_version_id uuid NOT NULL REFERENCES core.report_version(report_version_id),
    finding_number integer NOT NULL CHECK (finding_number > 0),
    title text NOT NULL,
    audit_area varchar(100) NOT NULL,
    risk_rating varchar(20) NOT NULL CHECK (risk_rating IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')),
    condition_text text NOT NULL,
    criteria_text text NOT NULL,
    cause_text text NOT NULL,
    effect_text text NOT NULL,
    recommendation_text text NOT NULL,
    management_response text,
    evidence_reference text NOT NULL,
    UNIQUE (report_version_id, finding_number)
);

CREATE TABLE IF NOT EXISTS core.generation_run (
    generation_run_id uuid PRIMARY KEY,
    report_version_id uuid NOT NULL REFERENCES core.report_version(report_version_id),
    run_number integer NOT NULL CHECK (run_number > 0),
    generator_model varchar(100) NOT NULL,
    critic_model varchar(100),
    critic_score smallint CHECK (critic_score BETWEEN 0 AND 100),
    critic_status varchar(30) CHECK (critic_status IN ('PASS', 'REVISION_REQUIRED', 'EVIDENCE_BLOCKED')),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    UNIQUE (report_version_id, run_number)
);

CREATE TABLE IF NOT EXISTS core.approval_event (
    approval_event_id uuid PRIMARY KEY,
    report_version_id uuid NOT NULL REFERENCES core.report_version(report_version_id),
    event_type varchar(40) NOT NULL CHECK (event_type IN (
        'SUBMITTED_FOR_REVIEW', 'RETURNED_FOR_REVISION', 'CLIENT_RELEASE_APPROVED',
        'CLIENT_RELEASE_REVOKED', 'RETRIEVAL_APPROVED', 'RETRIEVAL_REJECTED',
        'TRAINING_APPROVED', 'TRAINING_REJECTED'
    )),
    actor_id varchar(200) NOT NULL,
    actor_role varchar(50) NOT NULL,
    comment_text text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.document (
    document_id uuid PRIMARY KEY,
    report_version_id uuid NOT NULL REFERENCES core.report_version(report_version_id),
    document_type varchar(10) NOT NULL CHECK (document_type IN ('DOCX', 'PDF', 'JSON')),
    storage_uri text NOT NULL,
    content_checksum char(64) NOT NULL,
    file_size_bytes bigint NOT NULL CHECK (file_size_bytes >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_version_id, document_type, content_checksum)
);

CREATE TABLE IF NOT EXISTS governance.learning_decision (
    learning_decision_id uuid PRIMARY KEY,
    report_version_id uuid NOT NULL REFERENCES core.report_version(report_version_id),
    use_type varchar(20) NOT NULL CHECK (use_type IN ('RETRIEVAL', 'EVALUATION', 'TRAINING')),
    decision varchar(20) NOT NULL CHECK (decision IN ('PENDING', 'APPROVED', 'REJECTED', 'REVOKED')),
    anonymized boolean NOT NULL DEFAULT false,
    decided_by varchar(200),
    decided_at timestamptz,
    notes text,
    CHECK (decision = 'PENDING' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    CHECK (use_type <> 'TRAINING' OR decision <> 'APPROVED' OR anonymized),
    UNIQUE (report_version_id, use_type)
);

CREATE TABLE IF NOT EXISTS governance.pipeline_event (
    pipeline_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_version_id uuid NOT NULL REFERENCES core.report_version(report_version_id),
    event_status varchar(30) NOT NULL CHECK (event_status IN (
        'RECEIVED', 'VALIDATING', 'QUARANTINED', 'VALIDATED', 'LOADED', 'REJECTED'
    )),
    rule_code varchar(80),
    detail text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_report_client ON core.report(client_id);
CREATE INDEX IF NOT EXISTS idx_report_category_status ON core.report(category_id, lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_report_version_report_created ON core.report_version(report_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_finding_risk ON core.finding(risk_rating);
CREATE INDEX IF NOT EXISTS idx_approval_version_time ON core.approval_event(report_version_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_status_time ON governance.pipeline_event(event_status, occurred_at DESC);

CREATE OR REPLACE FUNCTION core.prevent_approved_version_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.version_status = 'CLIENT_APPROVED' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'Approved report versions are immutable; create a new version instead.';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_approved_version_immutable ON core.report_version;
CREATE TRIGGER trg_approved_version_immutable
BEFORE UPDATE ON core.report_version
FOR EACH ROW EXECUTE FUNCTION core.prevent_approved_version_mutation();

COMMIT;
