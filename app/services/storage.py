import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.core.config import settings


class FileTooLargeError(Exception):
    """Raised when an upload exceeds max_upload_bytes during streaming."""


def _safe_extension(filename: str) -> str:
    """Extract and validate file extension — only allow simple alphanum suffixes."""
    ext = Path(filename).suffix.lower()
    # Reject anything that isn't a plain extension like .pdf / .docx / .txt
    if re.match(r"^\.[a-z0-9]{1,10}$", ext):
        return ext
    return ""


async def save_upload(file: UploadFile) -> str:
    """Save an uploaded file and return its path (local path or s3://bucket/key).

    Raises FileTooLargeError if the content exceeds settings.max_upload_bytes.
    The size check happens during streaming so disk/memory is never over-committed.
    """
    ext = _safe_extension(file.filename or "")
    key = f"uploads/{uuid.uuid4()}{ext}"

    if settings.use_s3:
        import aioboto3
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise FileTooLargeError(
                f"File exceeds maximum size of {settings.max_upload_bytes} bytes."
            )
        session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        async with session.client("s3") as s3:
            await s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=content)
        return f"s3://{settings.s3_bucket}/{key}"

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid.uuid4()}{ext}"
    written = 0
    try:
        async with aiofiles.open(dest, "wb") as out:
            while chunk := await file.read(1024 * 64):  # 64 KB chunks
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise FileTooLargeError(
                        f"File exceeds maximum size of {settings.max_upload_bytes} bytes."
                    )
                await out.write(chunk)
    except FileTooLargeError:
        dest.unlink(missing_ok=True)
        raise

    return str(dest)


def delete_file(file_path: str) -> None:
    """Remove a file from local disk or S3, ignoring errors if it doesn't exist."""
    if file_path.startswith("s3://"):
        try:
            import boto3
            path_part = file_path[5:]  # strip "s3://"
            bucket, key = path_part.split("/", 1)
            client = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            pass
    else:
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            pass


@asynccontextmanager
async def download_for_processing(file_path: str):
    """Yield a local Path ready for extraction. Downloads from S3 to a temp file if needed."""
    if file_path.startswith("s3://"):
        import aioboto3
        path_part = file_path[5:]  # strip "s3://"
        bucket, key = path_part.split("/", 1)
        ext = _safe_extension(Path(key).name)
        session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            async with session.client("s3") as s3:
                await s3.download_file(bucket, key, str(tmp_path))
            yield tmp_path
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        yield Path(file_path)
