from __future__ import annotations

import hashlib
import uuid

import pytest

from audit_agent import client_intake, document_storage, entity_registry, legal_reference
from audit_agent.postgres_warehouse import database_url


# --- document_storage: pure local-disk backend, no database required ---


def test_local_backend_roundtrip_and_checksum(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DOCUMENT_STORAGE_LOCAL_DIR", str(tmp_path))
    content = b"noi dung du toan gia lap"

    stored = document_storage.upload_document("du-toan.xlsx", content)

    assert stored.storage_uri.startswith("file://")
    assert stored.content_checksum == hashlib.sha256(content).hexdigest()
    assert stored.file_size_bytes == len(content)
    assert document_storage.fetch_document(stored.storage_uri) == content


def test_unknown_backend_raises(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "azure")

    with pytest.raises(ValueError, match="DOCUMENT_STORAGE_BACKEND"):
        document_storage.upload_document("f.txt", b"data")


def test_s3_backend_requires_endpoint_url(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("DOCUMENT_STORAGE_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("DOCUMENT_STORAGE_BUCKET", "test-bucket")

    with pytest.raises(RuntimeError, match="DOCUMENT_STORAGE_ENDPOINT_URL"):
        document_storage.upload_document("f.txt", b"data")


# --- Postgres-backed modules: this repo has no existing local-Postgres test
# convention (tests/test_core.py only exercises the SQLite warehouse/gateway). These
# tests are the first to touch Postgres directly; they skip (not fail) when a reachable
# Postgres with migration 005 applied isn't available, so `pytest -q` stays green in
# environments without a local database.


def _postgres_ready() -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(database_url(), connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('core.entity')")
                return cursor.fetchone()[0] is not None
    except Exception:
        return False


def _require_postgres() -> None:
    if not _postgres_ready():
        pytest.skip(
            "No local Postgres with migration 005 applied; skipping engagement-platform "
            "integration test. Apply database/migrations/001..005 against DATABASE_URL to run it."
        )


def _create_test_report(cursor) -> uuid.UUID:
    client_id = uuid.uuid4()
    report_id = uuid.uuid4()
    cursor.execute(
        """
        INSERT INTO core.client (client_id, client_code, legal_name, industry_code)
        VALUES (%s, %s, %s, %s)
        """,
        (client_id, f"CLI-TEST-{client_id.hex[:8]}", "Test Client", "TEST"),
    )
    cursor.execute(
        """
        INSERT INTO core.report (report_id, report_code, category_id, client_id, created_by)
        SELECT %s, %s, category_id, %s, %s FROM core.report_category LIMIT 1
        """,
        (report_id, f"RPT-TEST-{report_id.hex[:8]}", client_id, "pytest"),
    )
    return report_id


def test_record_and_get_entity_verification() -> None:
    _require_postgres()
    tax_code = f"TEST{uuid.uuid4().hex[:10]}"

    record = entity_registry.record_entity_verification(
        "Công ty Cổ phần Kiểm thử",
        tax_code=tax_code,
        address="Hà Nội",
        legal_representative="Nguyễn Văn A",
        operating_status="ACTIVE",
        source="OFFICIAL_BUSINESS_REGISTRY",
        source_url="https://dangkykinhdoanh.gov.vn/",
        fields_confirmed=["legal_name", "tax_code"],
        verified_by="pytest",
    )

    assert record.tax_code == tax_code
    fetched = entity_registry.get_entity(tax_code=tax_code)
    assert fetched is not None
    assert fetched.entity_id == record.entity_id
    history = entity_registry.list_verification_history(record.entity_id)
    assert history[0]["verification_source"] == "OFFICIAL_BUSINESS_REGISTRY"


def test_record_entity_verification_rejects_unknown_source() -> None:
    _require_postgres()

    with pytest.raises(ValueError, match="source"):
        entity_registry.record_entity_verification(
            "Công ty Test",
            source="RANDOM_GUESS",
            source_url="https://example.com",
            verified_by="pytest",
        )


def test_record_and_check_legal_reference() -> None:
    _require_postgres()
    document_number = f"TEST-{uuid.uuid4().hex[:6]}/2026/NĐ-CP"

    record = legal_reference.record_legal_reference(
        "NGHI_DINH",
        document_number,
        "Nghị định thử nghiệm",
        source_url="https://thuvienphapluat.vn/",
        verified_by="pytest",
    )

    assert record.document_number == document_number
    fetched = legal_reference.check_legal_reference("NGHI_DINH", document_number)
    assert fetched is not None
    assert fetched.effectiveness_status == "CON_HIEU_LUC"
    assert legal_reference.check_legal_reference("NGHI_DINH", "khong-ton-tai") is None


def test_legal_reference_requires_source_url() -> None:
    _require_postgres()

    with pytest.raises(ValueError, match="source_url"):
        legal_reference.record_legal_reference(
            "THONG_TU", "999/2026/TT-BXD", "Thông tư thử", source_url="", verified_by="pytest",
        )


def test_client_intake_batch_and_document_lifecycle(tmp_path, monkeypatch) -> None:
    _require_postgres()
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DOCUMENT_STORAGE_LOCAL_DIR", str(tmp_path))

    import psycopg

    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            report_id = _create_test_report(cursor)

    batch_id = client_intake.open_upload_batch(report_id, uploaded_by="pytest")
    document = client_intake.add_source_document(batch_id, "du_toan.xlsx", b"noi dung du toan")

    assert document.document_status == "RECEIVED"
    assert document.upload_batch_id == batch_id

    with pytest.raises(ValueError, match="already been submitted"):
        client_intake.add_source_document(batch_id, "du_toan_ban_sao.xlsx", b"noi dung du toan")

    documents = client_intake.list_batch_documents(batch_id)
    assert len(documents) == 1
    assert documents[0]["source_document_id"] == document.source_document_id

    client_intake.close_upload_batch(batch_id)
    with pytest.raises(ValueError, match="closed"):
        client_intake.add_source_document(batch_id, "muon.xlsx", b"noi dung khac")
