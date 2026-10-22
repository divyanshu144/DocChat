"""Document blob storage: local directory (default) or S3. Keys never contain filenames or content."""
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import settings

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,500}")


class BlobError(Exception):
    pass


class BlobStore(Protocol):
    def put_file(self, key: str, path: str | Path) -> None: ...
    def fetch_to_path(self, key: str, dest: str | Path) -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


def validate_key(key: str) -> str:
    if not _KEY.fullmatch(key) or ".." in key.split("/") or "//" in key:
        raise BlobError("Invalid storage key")
    return key


def upload_key(job_id: str, suffix: str = "") -> str:
    """Key derived from the job id only; the original filename travels in the queue message."""
    safe = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix) else ""
    return validate_key(f"{settings.s3_prefix.strip('/')}/{job_id}/source{safe}".lstrip("/"))


@lru_cache()
def get_blob_store() -> BlobStore:
    if settings.storage_backend == "s3":
        from app.services.blobs.s3 import S3BlobStore
        return S3BlobStore(settings.s3_bucket, region=settings.aws_region or None)
    from app.services.blobs.local import LocalBlobStore
    return LocalBlobStore(settings.local_storage_dir)
