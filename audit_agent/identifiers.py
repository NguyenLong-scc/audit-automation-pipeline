from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def report_code(sequence: int, *, year: int | None = None) -> str:
    if sequence < 1:
        raise ValueError("Report sequence must be positive.")
    selected_year = year or datetime.now(timezone.utc).year
    return f"RPT-{selected_year}-{sequence:06d}"


def version_code(report_label: str, version_number: int) -> str:
    if version_number < 1:
        raise ValueError("Version number must be positive.")
    return f"{report_label}-V{version_number:02d}"
