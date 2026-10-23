BEGIN;

CREATE SCHEMA IF NOT EXISTS ingestion;

CREATE TABLE IF NOT EXISTS ingestion.upload_batch (
    upload_batch_id uuid PRIMARY KEY,
    uploaded_by varchar(200) NOT NULL,
    authorization_confirmed boolean NOT NULL DEFAULT false,
    batch_status varchar(30) NOT NULL DEFAULT 'OPEN'
        CHECK (batch_status IN ('OPEN', 'VALIDATING', 'VALIDATED', 'QUARANTINED', 'CLOSED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    CHECK (closed_at IS NULL OR batch_status = 'CLOSED')
);

CREATE TABLE IF NOT EXISTS ingestion.source_document (
    source_document_id uuid PRIMARY KEY,
    upload_batch_id uuid NOT NULL REFERENCES ingestion.upload_batch(upload_batch_id),
    report_version_id uuid REFERENCES core.report_version(report_version_id),
    original_filename text NOT NULL,
    media_type varchar(150),
    file_extension varchar(20) NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    content_checksum char(64) NOT NULL UNIQUE,
    storage_uri text NOT NULL,
    extraction_payload jsonb,
    document_status varchar(30) NOT NULL DEFAULT 'RECEIVED'
        CHECK (document_status IN (
            'RECEIVED', 'VALIDATING', 'VALIDATED', 'QUARANTINED', 'LOADED', 'REJECTED'
        )),
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    loaded_at timestamptz,
    CHECK (loaded_at IS NULL OR document_status = 'LOADED')
);

CREATE TABLE IF NOT EXISTS ingestion.validation_result (
    validation_result_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_document_id uuid NOT NULL REFERENCES ingestion.source_document(source_document_id),
    rule_code varchar(80) NOT NULL,
    result_level varchar(20) NOT NULL CHECK (result_level IN ('PASS', 'WARNING', 'BLOCKER')),
    detail text NOT NULL,
    checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.dataset (
    dataset_id uuid PRIMARY KEY,
    dataset_code varchar(40) NOT NULL UNIQUE,
    dataset_name varchar(200) NOT NULL,
    use_type varchar(20) NOT NULL CHECK (use_type IN ('RETRIEVAL', 'EVALUATION', 'TRAINING')),
    version_number integer NOT NULL CHECK (version_number > 0),
    dataset_status varchar(30) NOT NULL DEFAULT 'DRAFT'
        CHECK (dataset_status IN ('DRAFT', 'PREVIEW_ONLY', 'READY', 'EXPORTED', 'REVOKED')),
    item_count integer NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    content_checksum char(64),
    created_by varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    sealed_at timestamptz,
    UNIQUE (dataset_name, use_type, version_number)
);

CREATE TABLE IF NOT EXISTS governance.dataset_item (
    dataset_item_id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES governance.dataset(dataset_id),
    report_version_id uuid NOT NULL REFERENCES core.report_version(report_version_id),
    source_document_id uuid REFERENCES ingestion.source_document(source_document_id),
    item_number integer NOT NULL CHECK (item_number > 0),
    record_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, item_number),
    UNIQUE (dataset_id, report_version_id)
);

CREATE TABLE IF NOT EXISTS governance.training_job (
    training_job_id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES governance.dataset(dataset_id),
    provider varchar(50) NOT NULL,
    provider_job_id varchar(200),
    provider_file_id varchar(200),
    base_model varchar(150) NOT NULL,
    result_model varchar(200),
    job_status varchar(30) NOT NULL DEFAULT 'DRAFT'
        CHECK (job_status IN (
            'DRAFT', 'FILE_UPLOADED', 'QUEUED', 'RUNNING', 'SUCCEEDED',
            'FAILED', 'CANCELLED', 'DELETION_REQUESTED', 'DELETED'
        )),
    requested_by varchar(200) NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    delete_after timestamptz,
    error_detail text,
    UNIQUE (provider, provider_job_id)
);

CREATE INDEX IF NOT EXISTS idx_source_document_batch_status
    ON ingestion.source_document(upload_batch_id, document_status);
CREATE INDEX IF NOT EXISTS idx_validation_document_level
    ON ingestion.validation_result(source_document_id, result_level);
CREATE INDEX IF NOT EXISTS idx_dataset_use_status
    ON governance.dataset(use_type, dataset_status);
CREATE INDEX IF NOT EXISTS idx_dataset_item_version
    ON governance.dataset_item(report_version_id);
CREATE INDEX IF NOT EXISTS idx_training_job_status_time
    ON governance.training_job(job_status, requested_at DESC);

CREATE OR REPLACE FUNCTION governance.enforce_dataset_item_approval()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    required_use_type varchar(20);
    approved boolean;
BEGIN
    SELECT use_type INTO required_use_type
    FROM governance.dataset
    WHERE dataset_id = NEW.dataset_id;

    SELECT EXISTS (
        SELECT 1
        FROM governance.learning_decision decision
        WHERE decision.report_version_id = NEW.report_version_id
          AND decision.use_type = required_use_type
          AND decision.decision = 'APPROVED'
          AND (required_use_type <> 'TRAINING' OR decision.anonymized)
    ) INTO approved;

    IF NOT approved THEN
        RAISE EXCEPTION
            'Report version % is not approved for % use',
            NEW.report_version_id,
            required_use_type;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_dataset_item_requires_approval ON governance.dataset_item;
CREATE TRIGGER trg_dataset_item_requires_approval
BEFORE INSERT OR UPDATE ON governance.dataset_item
FOR EACH ROW EXECUTE FUNCTION governance.enforce_dataset_item_approval();

COMMIT;
