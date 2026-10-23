from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOCAL_DIR = Path("data/documents")
SUPPORTED_BACKENDS = ("local", "s3")


@dataclass(frozen=True)
class StoredDocument:
    storage_uri: str
    content_checksum: str
    file_size_bytes: int


def storage_backend() -> str:
    return os.getenv("DOCUMENT_STORAGE_BACKEND", "local").strip().lower()


def _checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def upload_document(
    filename: str, content: bytes, *, content_type: str | None = None
) -> StoredDocument:
    """Store raw document bytes and return a URI + checksum to persist in Postgres.

    Backend is chosen via `DOCUMENT_STORAGE_BACKEND` (`local` by default, `s3` for any
    S3-compatible object store — Viettel Cloud Storage, VNG Cloud, AWS S3, MinIO...).
    This mirrors how `DATABASE_URL` already defaults to a local Postgres and gets
    replaced with a managed provider URL in production (see `database/README.md`):
    swapping backends here only requires changing environment variables, not code.
    """

    backend = storage_backend()
    if backend == "local":
        return _upload_local(filename, content)
    if backend == "s3":
        return _upload_s3(filename, content, content_type=content_type)
    raise ValueError(
        f"Unknown DOCUMENT_STORAGE_BACKEND: {backend!r} (expected one of {SUPPORTED_BACKENDS})."
    )


def fetch_document(storage_uri: str) -> bytes:
    if storage_uri.startswith("file://"):
        return _fetch_local(storage_uri)
    if storage_uri.startswith("s3://"):
        return _fetch_s3(storage_uri)
    raise ValueError(f"Unsupported storage_uri scheme: {storage_uri!r}")


def _local_dir() -> Path:
    return Path(os.getenv("DOCUMENT_STORAGE_LOCAL_DIR", str(DEFAULT_LOCAL_DIR)))


def _upload_local(filename: str, content: bytes) -> StoredDocument:
    checksum = _checksum(content)
    directory = _local_dir()
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "document"
    path = directory / f"{checksum}-{safe_name}"
    path.write_bytes(content)
    return StoredDocument(
        storage_uri=f"file://{path.resolve()}",
        content_checksum=checksum,
        file_size_bytes=len(content),
    )


def _fetch_local(storage_uri: str) -> bytes:
    path = Path(storage_uri[len("file://"):])
    return path.read_bytes()


def _s3_client():
    endpoint_url = os.getenv("DOCUMENT_STORAGE_ENDPOINT_URL")
    if not endpoint_url:
        raise RuntimeError(
            "DOCUMENT_STORAGE_ENDPOINT_URL is required for DOCUMENT_STORAGE_BACKEND=s3 "
            "(point it at your S3-compatible provider, e.g. Viettel Cloud Storage or VNG Cloud)."
        )
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Install boto3 to use DOCUMENT_STORAGE_BACKEND=s3."
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.getenv("DOCUMENT_STORAGE_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("DOCUMENT_STORAGE_SECRET_KEY"),
    )


def _s3_bucket() -> str:
    bucket = os.getenv("DOCUMENT_STORAGE_BUCKET")
    if not bucket:
        raise RuntimeError("DOCUMENT_STORAGE_BUCKET is required for DOCUMENT_STORAGE_BACKEND=s3.")
    return bucket


def _upload_s3(
    filename: str, content: bytes, *, content_type: str | None = None
) -> StoredDocument:
    checksum = _checksum(content)
    bucket = _s3_bucket()
    safe_name = Path(filename).name or "document"
    key = f"{checksum}/{safe_name}"
    extra_args = {"ContentType": content_type} if content_type else {}
    _s3_client().put_object(Bucket=bucket, Key=key, Body=content, **extra_args)
    return StoredDocument(
        storage_uri=f"s3://{bucket}/{key}",
        content_checksum=checksum,
        file_size_bytes=len(content),
    )


def _fetch_s3(storage_uri: str) -> bytes:
    bucket, _, key = storage_uri[len("s3://"):].partition("/")
    response = _s3_client().get_object(Bucket=bucket, Key=key)
    return response["Body"].read()
