from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document, DocumentStatus
from app.services import ingestion, storage

router = APIRouter()

ALLOWED_CONTENT_TYPES = ingestion.SUPPORTED_TYPES


class DocumentResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    status: DocumentStatus
    chunk_count: int
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


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
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("ingest_document_task", document_id)
    else:
        background_tasks.add_task(_run_ingestion_bg, document_id)


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    # Save first, then check size — avoids buffering entire file in RAM
    file_path = await storage.save_upload(file)
    file_size = Path(file_path).stat().st_size
    if file_size > settings.max_upload_bytes:
        storage.delete_file(file_path)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_bytes} bytes.",
        )

    document = Document(
        filename=file.filename or "unknown",
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
