import shutil
import tempfile
import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core.qdrant import get_qdrant_client, get_qdrant_collection
from qdrant_client.models import Filter, FieldCondition, MatchValue
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
    status: str
    phase: str
    message: str
    source_id: str | None = None
    error: str | None = None


_INGEST_JOBS: dict[str, dict] = {}


def _set_job(
    job_id: str,
    *,
    status: str,
    phase: str,
    message: str,
    source_id: str | None = None,
    error: str | None = None,
) -> None:
    _INGEST_JOBS[job_id] = {
        "job_id": job_id,
        "status": status,
        "phase": phase,
        "message": message,
        "source_id": source_id,
        "error": error,
    }


async def _run_pdf_ingest_job(
    job_id: str,
    tmp_path: str,
    filename: str,
    content_type: str,
) -> None:
    def progress(phase: str, message: str) -> None:
        _set_job(job_id, status="running", phase=phase, message=message)

    try:
        progress("queued", "Starting ingest")
        source_id = await ingest_pdf(tmp_path, filename, content_type, progress=progress)
        _set_job(
            job_id,
            status="done",
            phase="done",
            message=f"Ingested {filename}",
            source_id=source_id,
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            phase="error",
            message="Ingest failed",
            error=str(exc),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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
):
    if file.content_type not in SUPPORTED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    suffix = Path(file.filename or "upload").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    job_id = str(_uuid.uuid4())
    filename = file.filename or "upload"
    _set_job(job_id, status="queued", phase="queued", message=f"Queued {filename}")
    background_tasks.add_task(_run_pdf_ingest_job, job_id, tmp_path, filename, file.content_type)

    return IngestJobResponse(
        job_id=job_id,
        status="queued",
        phase="queued",
        message=f"Queued {filename}",
    )


@router.get("/ingest/jobs/{job_id}", response_model=IngestJobStatus)
async def get_ingest_job(job_id: str):
    job = _INGEST_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Ingest job {job_id} not found")
    return IngestJobStatus(**job)


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
    for name in ("pdf_chunks", "youtube_chunks", "web_chunks"):
        try:
            get_qdrant_collection(name)
            seen_ids: set[str] = set()
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
                        sources.append({
                            "source_id": sid,
                            "source_type": name.replace("_chunks", ""),
                            **{k: v for k, v in payload.items()
                               if k in ("filename", "title", "url", "ingested_at", "scraped_at")},
                        })
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
    for name in ("pdf_chunks", "youtube_chunks", "web_chunks"):
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
