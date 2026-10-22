"""API side of the SQS path: store the upload, record the job, publish a reference message."""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.telemetry import request_id
from app.models.ingest_job import IngestJob, IngestJobStatusValue
from app.services.blobs import get_blob_store, upload_key
from app.services.ingestion.runner import _aware, source_key_for_file, source_key_for_url
from app.services.queueing import IngestMessage, get_queue

_ACTIVE = (IngestJobStatusValue.queued, IngestJobStatusValue.running)


async def _active_duplicate(db: AsyncSession, key: str) -> IngestJob | None:
    rows = (await db.execute(
        select(IngestJob).where(IngestJob.dedupe_key == key, IngestJob.status.in_(_ACTIVE))
        .order_by(IngestJob.created_at.desc())
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        updated = _aware(row.updated_at)
        if not updated:
            continue
        age = (now - updated).total_seconds()
        limit = settings.ingest_dedupe_window_s
        if row.status == IngestJobStatusValue.queued:
            limit = min(limit, settings.ingest_queued_stale_s)  # a dead "queued" row must not block resubmission
        if age <= limit:
            return row
    return None


async def _insert_job_row(db: AsyncSession, values: dict) -> None:
    """Insert the job row, doing nothing if it exists: the worker may have created it already."""
    dialect = (await db.connection()).dialect.name
    maker = postgresql.insert if dialect == "postgresql" else sqlite.insert
    await db.execute(maker(IngestJob).values(**values).on_conflict_do_nothing(index_elements=["id"]))
    await db.commit()


async def enqueue_ingest(
    db: AsyncSession, source_type: str, *, url: str | None = None, tmp_path: str | None = None,
    filename: str | None = None, content_type: str | None = None,
) -> tuple[str, str, str, str]:
    """Returns (job_id, status, phase, message). An identical active job is returned instead of a new one."""
    if source_type == "pdf":
        key = await asyncio.to_thread(source_key_for_file, tmp_path)
    else:
        key = source_key_for_url(source_type, url)

    existing = await _active_duplicate(db, key)
    if existing is not None:
        return existing.id, existing.status.value, existing.phase, existing.message

    job_id = str(uuid.uuid4())
    storage_key = None
    if source_type == "pdf":
        storage_key = upload_key(job_id, Path(filename or "").suffix)
        await asyncio.to_thread(get_blob_store().put_file, storage_key, tmp_path)

    message = f"Queued {source_type} ingest"
    # Order matters. Send first, then record the job. If the process dies between the two, the worker creates the
    # row itself when it claims the message (claim_job), so no job is ever left "queued" with no message behind it.
    # The cost is the opposite case (message sent, row not written), which is harmless: the work still runs.
    try:
        await asyncio.to_thread(get_queue().send, IngestMessage(
            job_id=job_id, source_type=source_type, storage_key=storage_key, url=url,
            filename=filename, content_type=content_type, correlation_id=request_id()))
    except Exception:
        raise HTTPException(503, "Could not queue ingestion; please retry") from None
    try:
        await _insert_job_row(db, dict(
            id=job_id, source_type=source_type, status=IngestJobStatusValue.queued, phase="queued",
            message=message, dedupe_key=key, attempts=0))
    except Exception:
        await db.rollback()
        # The message is already queued and will run; a retry is deduplicated and the source lock makes it safe.
        raise HTTPException(503, "Could not record the ingestion job; please retry") from None
    return job_id, "queued", "queued", message
