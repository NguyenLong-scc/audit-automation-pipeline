from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import document_storage
from .postgres_warehouse import database_url


@dataclass(frozen=True)
class SourceDocumentRecord:
    source_document_id: uuid.UUID
    upload_batch_id: uuid.UUID
    report_version_id: uuid.UUID | None
    original_filename: str
    media_type: str | None
    file_extension: str
    byte_size: int
    content_checksum: str
    storage_uri: str
    document_status: str
    uploaded_at: datetime


def _connect(url: str | None = None):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install psycopg to use client intake.") from exc
    return psycopg.connect(url or database_url())


def open_upload_batch(
    report_id: uuid.UUID | str,
    *,
    uploaded_by: str,
    authorization_confirmed: bool = False,
    url: str | None = None,
) -> uuid.UUID:
    """Open a new client upload batch tied to an engagement (`core.report`) from the start.

    `report_id` is the shared grouping key: every file a client submits for this
    engagement lands in a batch pointing at the same `report_id`, so a later retrieval
    can pull the whole bundle together. When a specific `report_version` produced from
    these files is approved, call `link_document_to_report_version` to narrow the
    lineage down to exactly the files that fed that approved output.
    """

    if not uploaded_by.strip():
        raise ValueError("uploaded_by is required.")
    batch_id = uuid.uuid4()
    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM core.report WHERE report_id = %s",
                (uuid.UUID(str(report_id)),),
            )
            if cursor.fetchone() is None:
                raise ValueError("The supplied report_id does not exist.")
            cursor.execute(
                """
                INSERT INTO ingestion.upload_batch (
                    upload_batch_id, report_id, uploaded_by, authorization_confirmed
                ) VALUES (%s, %s, %s, %s)
                """,
                (batch_id, uuid.UUID(str(report_id)), uploaded_by.strip(), authorization_confirmed),
            )
    return batch_id


def add_source_document(
    upload_batch_id: uuid.UUID | str,
    filename: str,
    content: bytes,
    *,
    media_type: str | None = None,
    url: str | None = None,
) -> SourceDocumentRecord:
    """Store a client-submitted file and record its metadata against the batch.

    Bytes go through `document_storage.upload_document` (backend chosen via
    `DOCUMENT_STORAGE_BACKEND`); only the resulting `storage_uri` + checksum + size are
    written to Postgres, matching the design intent already documented in
    `database/README.md` ("Word and PDF binaries stay in controlled document storage;
    PostgreSQL stores their URI, checksum, and metadata").
    """

    batch_id = uuid.UUID(str(upload_batch_id))
    stored = document_storage.upload_document(filename, content, content_type=media_type)
    extension = Path(filename).suffix.lower() or ".bin"
    document_id = uuid.uuid4()

    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT batch_status FROM ingestion.upload_batch WHERE upload_batch_id = %s",
                (batch_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("The supplied upload_batch_id does not exist.")
            if row[0] == "CLOSED":
                raise ValueError("This upload batch is closed; open a new batch instead.")
            try:
                cursor.execute(
                    """
                    INSERT INTO ingestion.source_document (
                        source_document_id, upload_batch_id, original_filename, media_type,
                        file_extension, byte_size, content_checksum, storage_uri
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING document_status, uploaded_at
                    """,
                    (
                        document_id, batch_id, Path(filename).name, media_type, extension,
                        stored.file_size_bytes, stored.content_checksum, stored.storage_uri,
                    ),
                )
            except Exception as exc:  # pragma: no cover - exact exception type is driver-specific
                if "content_checksum" in str(exc).lower():
                    raise ValueError("This exact file has already been submitted.") from exc
                raise
            document_status, uploaded_at = cursor.fetchone()

    return SourceDocumentRecord(
        source_document_id=document_id,
        upload_batch_id=batch_id,
        report_version_id=None,
        original_filename=Path(filename).name,
        media_type=media_type,
        file_extension=extension,
        byte_size=stored.file_size_bytes,
        content_checksum=stored.content_checksum,
        storage_uri=stored.storage_uri,
        document_status=document_status,
        uploaded_at=uploaded_at,
    )


def close_upload_batch(upload_batch_id: uuid.UUID | str, *, url: str | None = None) -> None:
    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ingestion.upload_batch
                SET batch_status = 'CLOSED', closed_at = now()
                WHERE upload_batch_id = %s AND batch_status <> 'CLOSED'
                RETURNING upload_batch_id
                """,
                (uuid.UUID(str(upload_batch_id)),),
            )
            if cursor.fetchone() is None:
                raise ValueError("This upload batch does not exist or is already closed.")


def list_batch_documents(
    upload_batch_id: uuid.UUID | str, *, url: str | None = None
) -> list[dict[str, Any]]:
    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_document_id, original_filename, media_type, file_extension,
                       byte_size, content_checksum, storage_uri, document_status,
                       report_version_id, uploaded_at
                FROM ingestion.source_document
                WHERE upload_batch_id = %s
                ORDER BY uploaded_at ASC
                """,
                (uuid.UUID(str(upload_batch_id)),),
            )
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def link_document_to_report_version(
    source_document_id: uuid.UUID | str,
    report_version_id: uuid.UUID | str,
    *,
    url: str | None = None,
) -> None:
    """Mark exactly which source document fed a specific, now-relevant report version.

    Call this once a `report_version` produced from a batch's files is approved, to
    narrow the lineage from "every file ever submitted for this engagement"
    (`upload_batch.report_id`) down to "the exact inputs behind this approved output."
    """

    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ingestion.source_document
                SET report_version_id = %s
                WHERE source_document_id = %s
                RETURNING source_document_id
                """,
                (uuid.UUID(str(report_version_id)), uuid.UUID(str(source_document_id))),
            )
            if cursor.fetchone() is None:
                raise ValueError("The supplied source_document_id does not exist.")
