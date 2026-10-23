from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from .postgres_warehouse import database_url


VERIFICATION_SOURCES = (
    "OFFICIAL_BUSINESS_REGISTRY",
    "SECONDARY_AGGREGATOR",
    "CLIENT_PROVIDED",
    "OTHER",
)
OPERATING_STATUSES = ("ACTIVE", "SUSPENDED", "DISSOLVED", "UNKNOWN")


@dataclass(frozen=True)
class EntityRecord:
    entity_id: uuid.UUID
    legal_name: str
    tax_code: str | None
    international_name: str | None
    short_name: str | None
    address: str | None
    legal_representative: str | None
    operating_status: str
    established_date: date | None


def _connect(url: str | None = None):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install psycopg to use the entity registry.") from exc
    return psycopg.connect(url or database_url())


def _row_to_record(row: tuple[Any, ...]) -> EntityRecord:
    (
        entity_id, legal_name, tax_code, international_name, short_name,
        address, legal_representative, operating_status, established_date,
    ) = row
    return EntityRecord(
        entity_id=entity_id,
        legal_name=legal_name,
        tax_code=tax_code,
        international_name=international_name,
        short_name=short_name,
        address=address,
        legal_representative=legal_representative,
        operating_status=operating_status,
        established_date=established_date,
    )


_ENTITY_COLUMNS = """
    entity_id, legal_name, tax_code, international_name, short_name,
    address, legal_representative, operating_status, established_date
"""


def record_entity_verification(
    legal_name: str,
    *,
    tax_code: str | None = None,
    international_name: str | None = None,
    short_name: str | None = None,
    address: str | None = None,
    legal_representative: str | None = None,
    operating_status: str | None = None,
    established_date: date | None = None,
    source: str,
    source_url: str | None = None,
    fields_confirmed: tuple[str, ...] | list[str] = (),
    verified_by: str,
    notes: str | None = None,
    url: str | None = None,
) -> EntityRecord:
    """Record a verified (or re-verified) business entity.

    Upserts `core.entity` (keyed on `tax_code` when known, else on `legal_name`) and
    always appends one immutable row to `core.entity_verification` — this is the
    structured counterpart of the "Bước 1 cụ thể hóa" lookup procedure: search, then cross-check against the official business
    registration portal, then record the source and verification date instead of
    leaving it only in chat history.
    """

    clean_name = legal_name.strip()
    if not clean_name:
        raise ValueError("legal_name is required.")
    if source not in VERIFICATION_SOURCES:
        raise ValueError(f"source must be one of {VERIFICATION_SOURCES}.")
    if operating_status is not None and operating_status not in OPERATING_STATUSES:
        raise ValueError(f"operating_status must be one of {OPERATING_STATUSES}.")
    if not verified_by.strip():
        raise ValueError("verified_by is required.")

    clean_tax_code = tax_code.strip() if tax_code else None
    resolved_status = operating_status or "UNKNOWN"

    with _connect(url) as connection:
        with connection.cursor() as cursor:
            if clean_tax_code:
                cursor.execute(
                    f"""
                    INSERT INTO core.entity (
                        entity_id, tax_code, legal_name, international_name, short_name,
                        address, legal_representative, operating_status, established_date
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tax_code) DO UPDATE SET
                        legal_name = EXCLUDED.legal_name,
                        international_name = COALESCE(EXCLUDED.international_name, core.entity.international_name),
                        short_name = COALESCE(EXCLUDED.short_name, core.entity.short_name),
                        address = COALESCE(EXCLUDED.address, core.entity.address),
                        legal_representative = COALESCE(EXCLUDED.legal_representative, core.entity.legal_representative),
                        operating_status = EXCLUDED.operating_status,
                        established_date = COALESCE(EXCLUDED.established_date, core.entity.established_date),
                        updated_at = now()
                    RETURNING {_ENTITY_COLUMNS}
                    """,
                    (
                        uuid.uuid4(), clean_tax_code, clean_name, international_name, short_name,
                        address, legal_representative, resolved_status, established_date,
                    ),
                )
            else:
                cursor.execute(
                    "SELECT entity_id FROM core.entity WHERE tax_code IS NULL AND legal_name = %s",
                    (clean_name,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    cursor.execute(
                        f"""
                        INSERT INTO core.entity (
                            entity_id, legal_name, international_name, short_name,
                            address, legal_representative, operating_status, established_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {_ENTITY_COLUMNS}
                        """,
                        (
                            uuid.uuid4(), clean_name, international_name, short_name,
                            address, legal_representative, resolved_status, established_date,
                        ),
                    )
                else:
                    cursor.execute(
                        f"""
                        UPDATE core.entity SET
                            international_name = COALESCE(%s, international_name),
                            short_name = COALESCE(%s, short_name),
                            address = COALESCE(%s, address),
                            legal_representative = COALESCE(%s, legal_representative),
                            operating_status = %s,
                            established_date = COALESCE(%s, established_date),
                            updated_at = now()
                        WHERE entity_id = %s
                        RETURNING {_ENTITY_COLUMNS}
                        """,
                        (
                            international_name, short_name, address, legal_representative,
                            resolved_status, established_date, existing[0],
                        ),
                    )
            row = cursor.fetchone()
            record = _row_to_record(row)

            cursor.execute(
                """
                INSERT INTO core.entity_verification (
                    entity_id, verification_source, source_url, fields_confirmed,
                    verified_by, notes
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    record.entity_id, source, source_url, list(fields_confirmed),
                    verified_by.strip(), notes,
                ),
            )
    return record


def get_entity(
    *, tax_code: str | None = None, legal_name: str | None = None, url: str | None = None
) -> EntityRecord | None:
    if not tax_code and not legal_name:
        raise ValueError("Supply tax_code or legal_name.")
    with _connect(url) as connection:
        with connection.cursor() as cursor:
            if tax_code:
                cursor.execute(
                    f"SELECT {_ENTITY_COLUMNS} FROM core.entity WHERE tax_code = %s",
                    (tax_code.strip(),),
                )
            else:
                cursor.execute(
                    f"SELECT {_ENTITY_COLUMNS} FROM core.entity WHERE legal_name = %s",
                    (legal_name.strip(),),
                )
            row = cursor.fetchone()
            return _row_to_record(row) if row else None


def list_verification_history(
    entity_id: uuid.UUID | str, *, url: str | None = None
) -> list[dict[str, Any]]:
    with _connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT verification_source, source_url, fields_confirmed, verified_by,
                       verified_at, notes
                FROM core.entity_verification
                WHERE entity_id = %s
                ORDER BY verified_at DESC
                """,
                (uuid.UUID(str(entity_id)),),
            )
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
