from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .postgres_warehouse import database_url


DOCUMENT_TYPES = ("LUAT", "NGHI_DINH", "THONG_TU", "QUYET_DINH", "CONG_DIEN", "KHAC")
EFFECTIVENESS_STATUSES = ("CON_HIEU_LUC", "DA_THAY_THE", "HET_HIEU_LUC", "CHUA_XAC_DINH")


@dataclass(frozen=True)
class LegalReferenceRecord:
    legal_reference_id: uuid.UUID
    document_type: str
    document_number: str
    title: str
    issuing_body: str | None
    issued_date: date | None
    effective_date: date | None
    effectiveness_status: str
    superseded_document_number: str | None
    source_url: str
    last_verified_at: datetime
    verified_by: str


def _connect(url: str | None = None):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install psycopg to use legal-reference tracking.") from exc
    return psycopg.connect(url or database_url())


_REFERENCE_COLUMNS = """
    legal_reference_id, document_type, document_number, title, issuing_body,
    issued_date, effective_date, effectiveness_status, superseded_document_number,
    source_url, last_verified_at, verified_by
"""


def _row_to_record(row: tuple[Any, ...]) -> LegalReferenceRecord:
    (
        legal_reference_id, document_type, document_number, title, issuing_body,
        issued_date, effective_date, effectiveness_status, superseded_document_number,
        source_url, last_verified_at, verified_by,
    ) = row
    return LegalReferenceRecord(
        legal_reference_id=legal_reference_id,
        document_type=document_type,
        document_number=document_number,
        title=title,
        issuing_body=issuing_body,
        issued_date=issued_date,
        effective_date=effective_date,
        effectiveness_status=effectiveness_status,
        superseded_document_number=superseded_document_number,
        source_url=source_url,
        last_verified_at=last_verified_at,
        verified_by=verified_by,
    )


def record_legal_reference(
    document_type: str,
    document_number: str,
    title: str,
    *,
    issuing_body: str | None = None,
    issued_date: date | None = None,
    effective_date: date | None = None,
    effectiveness_status: str = "CON_HIEU_LUC",
    superseded_document_number: str | None = None,
    source_url: str,
    verified_by: str,
    category_codes: tuple[str, ...] | list[str] = (),
    url: str | None = None,
) -> LegalReferenceRecord:
    """Record (or re-verify) one legal document's currency status.

    Upserts on `(document_type, document_number)` and always refreshes
    `last_verified_at` — this is the queryable counterpart of the "luôn dùng luật hiện
    hành" principle: before citing a law, call `check_legal_reference` first; only after
    actually reading the source document, call this to persist the result instead of
    re-deriving it from scratch next time.
    """

    clean_number = document_number.strip()
    clean_title = title.strip()
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"document_type must be one of {DOCUMENT_TYPES}.")
    if not clean_number:
        raise ValueError("document_number is required.")
    if not clean_title:
        raise ValueError("title is required.")
    if effectiveness_status not in EFFECTIVENESS_STATUSES:
        raise ValueError(f"effectiveness_status must be one of {EFFECTIVENESS_STATUSES}.")
    if not source_url.strip():
        raise ValueError("source_url is required — never record a legal reference without a source.")
    if not verified_by.strip():
        raise ValueError("verified_by is required.")

    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO core.legal_reference (
                    legal_reference_id, document_type, document_number, title,
                    issuing_body, issued_date, effective_date, effectiveness_status,
                    superseded_document_number, source_url, last_verified_at, verified_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
                ON CONFLICT (document_type, document_number) DO UPDATE SET
                    title = EXCLUDED.title,
                    issuing_body = COALESCE(EXCLUDED.issuing_body, core.legal_reference.issuing_body),
                    issued_date = COALESCE(EXCLUDED.issued_date, core.legal_reference.issued_date),
                    effective_date = COALESCE(EXCLUDED.effective_date, core.legal_reference.effective_date),
                    effectiveness_status = EXCLUDED.effectiveness_status,
                    superseded_document_number = COALESCE(
                        EXCLUDED.superseded_document_number,
                        core.legal_reference.superseded_document_number
                    ),
                    source_url = EXCLUDED.source_url,
                    last_verified_at = now(),
                    verified_by = EXCLUDED.verified_by
                RETURNING {_REFERENCE_COLUMNS}
                """,
                (
                    uuid.uuid4(), document_type, clean_number, clean_title, issuing_body,
                    issued_date, effective_date, effectiveness_status,
                    superseded_document_number, source_url.strip(), verified_by.strip(),
                ),
            )
            row = cursor.fetchone()
            record = _row_to_record(row)

            for category_code in category_codes:
                cursor.execute(
                    """
                    INSERT INTO core.legal_reference_category (legal_reference_id, category_id)
                    SELECT %s, category_id FROM core.report_category WHERE category_code = %s
                    ON CONFLICT DO NOTHING
                    """,
                    (record.legal_reference_id, category_code),
                )
    return record


def check_legal_reference(
    document_type: str, document_number: str, *, url: str | None = None
) -> LegalReferenceRecord | None:
    """Look up a previously-recorded legal reference before citing it.

    Returns `None` when nothing has been recorded yet — per the no-fabrication rule,
    that means the document must be re-verified against a primary source before use,
    not assumed.
    """

    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {_REFERENCE_COLUMNS} FROM core.legal_reference
                WHERE document_type = %s AND document_number = %s
                """,
                (document_type, document_number.strip()),
            )
            row = cursor.fetchone()
            return _row_to_record(row) if row else None


def list_stale_references(
    *, older_than_days: int = 180, url: str | None = None
) -> list[dict[str, Any]]:
    """List CON_HIEU_LUC references not re-verified within `older_than_days`."""

    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT document_type, document_number, title, effectiveness_status,
                       last_verified_at
                FROM core.legal_reference
                WHERE effectiveness_status = 'CON_HIEU_LUC'
                  AND last_verified_at < now() - (%s || ' days')::interval
                ORDER BY last_verified_at ASC
                """,
                (older_than_days,),
            )
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
