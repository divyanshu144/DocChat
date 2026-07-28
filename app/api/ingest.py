import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
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
