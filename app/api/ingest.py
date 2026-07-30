import shutil
import tempfile
import uuid as _uuid
from pathlib import Path

import asyncio
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.core.sources import LEGACY_SOURCE_COLLECTIONS, source_collection, source_metadata
from app.core.qdrant import get_qdrant_client, get_qdrant_collection
from qdrant_client.models import Filter, FieldCondition, MatchValue
from app.models.ingest_job import IngestJob, IngestJobStatusValue
from app.services.ingestion.pdf import ingest_pdf, SUPPORTED_TYPES
from app.services.ingestion.youtube import ingest_youtube
from app.services.ingestion.web import ingest_web

router = APIRouter()


class UrlRequest(BaseModel):
    url: str


class IngestResponse(BaseModel):
    source_id: str
    message: str


class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    phase: str
    message: str


class IngestJobStatus(BaseModel):
    job_id: str
    source_type: str
    status: str
    phase: str
    message: str
    source_id: str | None = None
    error: str | None = None


async def _set_job(
    job_id: str,
    *,
    source_type: str | None = None,
    status: str,
    phase: str,
    message: str,
    source_id: str | None = None,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(IngestJob, job_id)
        if job is None:
            job = IngestJob(
                id=job_id,
                source_type=source_type or "unknown",
                status=IngestJobStatusValue(status),
                phase=phase,
                message=message,
                source_id=source_id,
                error=error,
            )
            session.add(job)
        else:
            if source_type is not None:
                job.source_type = source_type
            job.status = IngestJobStatusValue(status)
            job.phase = phase
            job.message = message
            job.source_id = source_id
            job.error = error
        await session.commit()


def _job_response(job: IngestJob) -> IngestJobStatus:
    return IngestJobStatus(
        job_id=job.id,
        source_type=job.source_type,
        status=job.status.value,
        phase=job.phase,
        message=job.message,
        source_id=job.source_id,
        error=job.error,
    )


async def _run_pdf_ingest_job(
    job_id: str,
    tmp_path: str,
    filename: str,
    content_type: str,
) -> None:
    def progress(phase: str, message: str) -> None:
        asyncio.create_task(_set_job(job_id, status="running", phase=phase, message=message))

    try:
        await _set_job(job_id, status="running", phase="starting", message="Starting ingest")
        source_id = await ingest_pdf(tmp_path, filename, content_type, progress=progress)
        await _set_job(
            job_id,
            status="done",
            phase="done",
            message=f"Ingested {filename}",
            source_id=source_id,
        )
    except Exception as exc:
        await _set_job(
            job_id,
            status="error",
            phase="error",
            message="Ingest failed",
            error=str(exc),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def _run_url_ingest_job(job_id: str, source_type: str, url: str) -> None:
    try:
        await _set_job(job_id, status="running", phase="fetching", message=f"Fetching {source_type} source")
        if source_type == "youtube":
            source_id = await ingest_youtube(url)
        elif source_type == "web":
            source_id = await ingest_web(url)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")
        await _set_job(
            job_id,
            status="done",
            phase="done",
            message=f"Ingested {source_type}: {url}",
            source_id=source_id,
        )
    except Exception as exc:
        await _set_job(
            job_id,
            status="error",
            phase="error",
            message="Ingest failed",
            error=str(exc),
        )


@router.post("/ingest/pdf", response_model=IngestResponse)
async def ingest_pdf_endpoint(file: UploadFile = File(...)):
    if file.content_type not in SUPPORTED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    suffix = Path(file.filename or "upload").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        source_id = await ingest_pdf(tmp_path, file.filename or "upload", file.content_type)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return IngestResponse(source_id=source_id, message=f"Ingested {file.filename}")


@router.post(
    "/ingest/pdf/jobs",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_pdf_ingest_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in SUPPORTED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    suffix = Path(file.filename or "upload").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    job_id = str(_uuid.uuid4())
    filename = file.filename or "upload"
    db.add(IngestJob(
        id=job_id,
        source_type="pdf",
        status=IngestJobStatusValue.queued,
        phase="queued",
        message=f"Queued {filename}",
    ))
    await db.commit()
    background_tasks.add_task(_run_pdf_ingest_job, job_id, tmp_path, filename, file.content_type)

    return IngestJobResponse(
        job_id=job_id,
        status="queued",
        phase="queued",
        message=f"Queued {filename}",
    )


@router.get("/ingest/jobs/{job_id}", response_model=IngestJobStatus)
async def get_ingest_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(IngestJob, job_id)
    if not job:
        raise HTTPException(404, f"Ingest job {job_id} not found")
    return _job_response(job)


@router.post(
    "/ingest/youtube/jobs",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_youtube_ingest_job(
    req: UrlRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    job_id = str(_uuid.uuid4())
    db.add(IngestJob(
        id=job_id,
        source_type="youtube",
        status=IngestJobStatusValue.queued,
        phase="queued",
        message=f"Queued YouTube: {req.url}",
    ))
    await db.commit()
    background_tasks.add_task(_run_url_ingest_job, job_id, "youtube", req.url)
    return IngestJobResponse(job_id=job_id, status="queued", phase="queued", message=f"Queued YouTube: {req.url}")


@router.post(
    "/ingest/web/jobs",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_web_ingest_job(
    req: UrlRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    job_id = str(_uuid.uuid4())
    db.add(IngestJob(
        id=job_id,
        source_type="web",
        status=IngestJobStatusValue.queued,
        phase="queued",
        message=f"Queued web: {req.url}",
    ))
    await db.commit()
    background_tasks.add_task(_run_url_ingest_job, job_id, "web", req.url)
    return IngestJobResponse(job_id=job_id, status="queued", phase="queued", message=f"Queued web: {req.url}")


@router.post("/ingest/youtube", response_model=IngestResponse)
async def ingest_youtube_endpoint(req: UrlRequest):
    try:
        source_id = await ingest_youtube(req.url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return IngestResponse(source_id=source_id, message=f"Ingested YouTube: {req.url}")


@router.post("/ingest/web", response_model=IngestResponse)
async def ingest_web_endpoint(req: UrlRequest):
    try:
        source_id = await ingest_web(req.url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return IngestResponse(source_id=source_id, message=f"Ingested web: {req.url}")


@router.get("/sources")
async def list_sources():
    client = get_qdrant_client()
    sources = []
    seen_ids: set[str] = set()
    collections = [source_collection(), *LEGACY_SOURCE_COLLECTIONS.values()]
    for name in collections:
        try:
            get_qdrant_collection(name)
            offset = None
            while True:
                records, offset = client.scroll(
                    collection_name=name,
                    with_payload=True,
                    with_vectors=False,
                    limit=100,
                    offset=offset,
                )
                for rec in records:
                    payload = rec.payload or {}
                    sid = payload.get("source_id")
                    if sid and sid not in seen_ids:
                        seen_ids.add(sid)
                        source_type = payload.get("source_type") or name.replace("_chunks", "")
                        sources.append({"source_id": sid, "source_type": source_type, **source_metadata(payload)})
                if offset is None:
                    break
        except Exception:
            pass
    return {"sources": sources}


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    client = get_qdrant_client()
    deleted = False
    source_filter = Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
    for name in [source_collection(), *LEGACY_SOURCE_COLLECTIONS.values()]:
        try:
            get_qdrant_collection(name)
            count = client.count(collection_name=name, count_filter=source_filter, exact=True).count
            if count > 0:
                client.delete(collection_name=name, points_selector=source_filter)
                deleted = True
        except Exception:
            pass
    if not deleted:
        raise HTTPException(404, f"Source {source_id} not found")
    return {"message": f"Deleted source {source_id}"}
