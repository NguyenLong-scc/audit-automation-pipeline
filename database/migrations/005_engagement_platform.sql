BEGIN;

-- Verified business-entity registry (Phase 1 of the client-intake platform).
-- Operationalizes a documented lookup procedure: search -> cross-check against
-- the official business registration portal -> record with source + verification date,
-- instead of that verification living only in chat history.

CREATE TABLE IF NOT EXISTS core.entity (
    entity_id uuid PRIMARY KEY,
    tax_code varchar(20) UNIQUE,
    legal_name varchar(300) NOT NULL,
    international_name varchar(300),
    short_name varchar(100),
    address text,
    legal_representative varchar(200),
    operating_status varchar(50) NOT NULL DEFAULT 'UNKNOWN'
        CHECK (operating_status IN ('ACTIVE', 'SUSPENDED', 'DISSOLVED', 'UNKNOWN')),
    established_date date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Append-only verification log: one row per lookup/verification event, never mutated.
-- Same pattern as core.approval_event / governance.pipeline_event elsewhere in this schema.
CREATE TABLE IF NOT EXISTS core.entity_verification (
    entity_verification_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id uuid NOT NULL REFERENCES core.entity(entity_id),
    verification_source varchar(50) NOT NULL CHECK (verification_source IN (
        'OFFICIAL_BUSINESS_REGISTRY', 'SECONDARY_AGGREGATOR', 'CLIENT_PROVIDED', 'OTHER'
    )),
    source_url text,
    fields_confirmed text[] NOT NULL DEFAULT '{}',
    verified_by varchar(200) NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT now(),
    notes text
);

ALTER TABLE core.client ADD COLUMN IF NOT EXISTS entity_id uuid REFERENCES core.entity(entity_id);

CREATE INDEX IF NOT EXISTS idx_entity_verification_entity_time
    ON core.entity_verification(entity_id, verified_at DESC);
CREATE INDEX IF NOT EXISTS idx_client_entity ON core.client(entity_id);

-- Legal-reference currency tracking. Operationalizes the "luôn dùng luật hiện hành"
-- principle as a queryable table instead of a rule that only lives in prose.

CREATE TABLE IF NOT EXISTS core.legal_reference (
    legal_reference_id uuid PRIMARY KEY,
    document_type varchar(30) NOT NULL CHECK (document_type IN (
        'LUAT', 'NGHI_DINH', 'THONG_TU', 'QUYET_DINH', 'CONG_DIEN', 'KHAC'
    )),
    document_number varchar(60) NOT NULL,
    title text NOT NULL,
    issuing_body varchar(200),
    issued_date date,
    effective_date date,
    effectiveness_status varchar(30) NOT NULL DEFAULT 'CON_HIEU_LUC'
        CHECK (effectiveness_status IN (
            'CON_HIEU_LUC', 'DA_THAY_THE', 'HET_HIEU_LUC', 'CHUA_XAC_DINH'
        )),
    superseded_by_id uuid REFERENCES core.legal_reference(legal_reference_id),
    superseded_document_number varchar(60),
    source_url text NOT NULL,
    last_verified_at timestamptz NOT NULL DEFAULT now(),
    verified_by varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_type, document_number)
);

CREATE TABLE IF NOT EXISTS core.legal_reference_category (
    legal_reference_id uuid NOT NULL REFERENCES core.legal_reference(legal_reference_id),
    category_id smallint NOT NULL REFERENCES core.report_category(category_id),
    PRIMARY KEY (legal_reference_id, category_id)
);

CREATE INDEX IF NOT EXISTS idx_legal_reference_status
    ON core.legal_reference(effectiveness_status);
CREATE INDEX IF NOT EXISTS idx_legal_reference_last_verified
    ON core.legal_reference(last_verified_at);

CREATE OR REPLACE VIEW core.v_legal_reference_needs_review AS
SELECT
    legal_reference_id,
    document_type,
    document_number,
    title,
    effectiveness_status,
    last_verified_at,
    now() - last_verified_at AS staleness
FROM core.legal_reference
WHERE effectiveness_status = 'CON_HIEU_LUC'
  AND last_verified_at < now() - interval '180 days'
ORDER BY last_verified_at ASC;

-- Wire the client-intake pipeline: tie an upload batch to the engagement (report) it
-- belongs to from the moment client files start arriving, before any report_version
-- exists yet. ingestion.source_document.report_version_id (already nullable in
-- 003_ingestion_gateway.sql) is set later, once a specific version is approved, to mark
-- exactly which files fed that approved output. report_id groups the whole engagement's
-- file bundle; report_version_id narrows to the exact inputs behind one approved output.
ALTER TABLE ingestion.upload_batch
    ADD COLUMN IF NOT EXISTS report_id uuid REFERENCES core.report(report_id);

CREATE INDEX IF NOT EXISTS idx_upload_batch_report ON ingestion.upload_batch(report_id);

COMMIT;
