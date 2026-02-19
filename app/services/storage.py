import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.core.config import settings


async def save_upload(file: UploadFile) -> str:
    """Save an uploaded file to disk and return its path."""
    
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "file").suffix
    dest = upload_dir / f"{uuid.uuid4()}{ext}"

    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(1024 * 64):  # 64 KB chunks
            await out.write(chunk)

    return str(dest)


def delete_file(file_path: str) -> None:
    """Remove a file from disk, ignoring errors if it doesn't exist."""
    try:
        Path(file_path).unlink(missing_ok=True)
    except OSError:
        pass
