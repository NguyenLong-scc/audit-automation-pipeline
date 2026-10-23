# PostgreSQL warehouse

This directory contains the provider-independent physical model for the audit-report warehouse.

## Apply locally or to a managed provider

```bash
createdb audit_warehouse
psql -v ON_ERROR_STOP=1 -d audit_warehouse -f database/migrations/001_audit_warehouse.sql
psql -v ON_ERROR_STOP=1 -d audit_warehouse -f database/migrations/002_report_codes.sql
psql -v ON_ERROR_STOP=1 -d audit_warehouse -f database/migrations/003_ingestion_gateway.sql
psql -v ON_ERROR_STOP=1 -d audit_warehouse -f database/seeds/001_report_categories.sql
psql -v ON_ERROR_STOP=1 -d audit_warehouse -f database/migrations/004_analytics_warehouse.sql
psql -v ON_ERROR_STOP=1 -d audit_warehouse -f database/migrations/005_engagement_platform.sql
```

For a managed database, replace `-d audit_warehouse` with the provider connection string.

## Design rules

- A report receives one permanent UUID and one human-readable report code.
- Every revision receives a new immutable version record.
- Client-release approval and AI-learning approval are separate events.
- Training approval requires an anonymized copy.
- Word and PDF binaries stay in controlled document storage; PostgreSQL stores their URI, checksum, and metadata.
- Pipeline failures are recorded and quarantined instead of silently discarded.
- Inbound files enter through `ingestion.upload_batch`, `source_document`, and `validation_result`.
- Only canonical report versions with an approved purpose-specific learning decision can enter a dataset.
- Retrieval, evaluation, and training datasets are immutable versioned snapshots.
- Provider file IDs and fine-tuning jobs are tracked so retention and deletion can be governed later.

The application reads `DATABASE_URL` and defaults locally to `postgresql:///audit_warehouse`.
Every generation appends a new `core.report_version`; it never rewrites an earlier version.

The Streamlit gateway currently uses a separate local SQLite implementation so the presentation
works without PostgreSQL or an external AI connection. Migration `003` is the production-oriented
target structure; external synchronization remains disabled in the prototype.

## Migration 005: engagement platform foundation

Adds the first real callers for the `ingestion.upload_batch`/`source_document` tables from
migration `003` (previously unused by any application code), plus two new registries:

- `core.entity` / `core.entity_verification` — a verified business-entity registry with an
  append-only verification log (source, fields confirmed, verified by/at). Written by
  `audit_agent/entity_registry.py`. `core.client.entity_id` optionally links a client to a
  verified entity.
- `core.legal_reference` / `core.legal_reference_category` — tracks which law/decree/circular
  citations have been verified as currently in force, when, and against what source, plus a
  `core.v_legal_reference_needs_review` view for references overdue for re-verification. Written
  by `audit_agent/legal_reference.py`.
- `ingestion.upload_batch.report_id` — ties a client's upload batch to the engagement
  (`core.report`) it belongs to from the moment files start arriving, before any report version
  exists. `ingestion.source_document.report_version_id` (already nullable in migration `003`) is
  set later, once a specific version is approved, via `audit_agent/client_intake.py`'s
  `link_document_to_report_version`. Together these give the "one shared ID groups the whole
  bundle" behaviour: `report_id` groups every file ever submitted for an engagement;
  `report_version_id` narrows to the exact files behind one approved output.

Actual file bytes are written through `audit_agent/document_storage.py`, which stores them
locally by default (`DOCUMENT_STORAGE_BACKEND=local`) or in any S3-compatible object store
(`DOCUMENT_STORAGE_BACKEND=s3` — Viettel Cloud Storage, VNG Cloud, AWS S3, MinIO) via environment
variables only, so a real cloud account can be plugged in later without code changes.
