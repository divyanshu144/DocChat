import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key
from app.models.document import Document, DocumentStatus
from app.services import ingestion, storage
from app.services.storage import FileTooLargeError

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])

ALLOWED_CONTENT_TYPES = ingestion.SUPPORTED_TYPES

# Lazy import — python-magic requires libmagic system library
try:
    import magic as _magic
    _MAGIC_AVAILABLE = True
except ImportError:
    _MAGIC_AVAILABLE = False
    logger.warning(
        "python-magic not installed or libmagic missing — "
        "file content MIME verification is disabled"
    )


class DocumentResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    status: DocumentStatus
    chunk_count: int
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _sanitize_filename(name: str) -> str:
    """Strip path components and limit to safe characters."""
    name = Path(name).name  # drop any directory traversal
    name = re.sub(r"[^\w.\-]", "_", name)  # allow only word chars, dots, hyphens
    return name[:255] or "unknown"


async def _run_ingestion_bg(document_id: str) -> None:
    """Run ingestion in a background task (non-ARQ path)."""
    from app.core.database import AsyncSessionLocal
    from app.models.document import Document

    async with AsyncSessionLocal() as db:
        document = await db.get(Document, document_id)
        if document:
            try:
                await ingestion.ingest_document(document, db)
            except Exception:
                pass  # Status already set to error inside ingest_document


async def _enqueue_ingestion(document_id: str, background_tasks: BackgroundTasks) -> None:
    if settings.redis_url:
        from arq import create_pool
        from arq.connections import RedisSettings
        async with create_pool(RedisSettings.from_dsn(settings.redis_url)) as pool:
            await pool.enqueue_job("ingest_document_task", document_id)
    else:
        background_tasks.add_task(_run_ingestion_bg, document_id)


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # 1. Validate declared content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    # 2. Verify actual file content via magic bytes (prevents content-type spoofing)
    if _MAGIC_AVAILABLE:
        header = await file.read(2048)
        await file.seek(0)
        actual_mime = _magic.from_buffer(header, mime=True)
        if actual_mime not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File content does not match declared type. Detected: {actual_mime}",
            )

    # 3. Save (size limit enforced during streaming — no full disk write before check)
    try:
        file_path = await storage.save_upload(file)
    except FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_bytes} bytes.",
        )

    # 4. Sanitize filename before persisting
    safe_filename = _sanitize_filename(file.filename or "unknown")

    document = Document(
        filename=safe_filename,
        content_type=file.content_type,
        file_path=file_path,
        status=DocumentStatus.pending,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await _enqueue_ingestion(document.id, background_tasks)

    return document


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return result.scalars().all()


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    return document
