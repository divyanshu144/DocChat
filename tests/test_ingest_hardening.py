import asyncio
import io
import threading
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


def test_shorter_reingest_removes_orphan_chunks(monkeypatch):
    from app.services.ingestion.storage import replace_source_points

    monkeypatch.setattr(settings, "ingest_batch_size", 1)
    client = QdrantClient(":memory:")
    client.create_collection("test", vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    def points(source, count):
        return [PointStruct(id=index + (100 if source == "other" else 0), vector=[0.1, 0.2],
                            payload={"source_id": source}) for index in range(count)]
    replace_source_points(client, "test", "source", points("source", 3))
    replace_source_points(client, "test", "other", points("other", 1))
    replace_source_points(client, "test", "source", points("source", 1))
    rows, _ = client.scroll("test", limit=20)
    assert sorted(row.payload["source_id"] for row in rows) == ["other", "source"]
    client.close()



@pytest.mark.asyncio
async def test_web_embedding_and_indexing_run_off_event_loop(monkeypatch):
    from app.services.ingestion.web import ingest_web

    loop_thread = threading.get_ident()
    threads = []
    batches = []
    class Embedder:
        def embed_independently(self, texts):
            threads.append(threading.get_ident())
            batches.append(texts)
            return [np.array([0.1] * 384) for _ in texts]
    client = MagicMock()
    client.delete.side_effect = lambda **kwargs: threads.append(threading.get_ident())
    client.upsert.side_effect = lambda **kwargs: threads.append(threading.get_ident())
    monkeypatch.setattr(settings, "ingest_batch_size", 2)
    with (
        patch("app.services.ingestion.web._scrape", return_value={"content": "text", "title": "test"}),
        patch("app.services.ingestion.web._splitter.split_text", return_value=["a", "b", "c"]),
        patch("app.services.ingestion.web.get_embedder", return_value=Embedder()),
        patch("app.services.ingestion.web.get_qdrant_client", return_value=client),
        patch("app.services.ingestion.web.get_qdrant_collection"),
    ):
        await ingest_web("https://example.com")
    assert batches == [["a", "b"], ["c"]]
    assert all(thread != loop_thread for thread in threads)
    assert client.upsert.call_count == 2
    assert client.mock_calls[0][0] == "delete"



@pytest.mark.asyncio
async def test_pdf_progress_updates_complete_before_done(tmp_path):
    from app.api.ingest import _run_pdf_ingest_job

    source = tmp_path / "upload.pdf"
    source.write_bytes(b"pdf")
    states = []
    async def set_job(job_id, **kwargs):
        await asyncio.sleep(0)
        states.append(kwargs["status"] + ":" + kwargs["phase"])
    async def ingest(*args, progress):
        await progress("embedding", "Embedding")
        await progress("indexing", "Indexing")
        return "source"
    with patch("app.api.ingest._set_job", set_job), patch("app.api.ingest.ingest_pdf", ingest):
        await _run_pdf_ingest_job("job", str(source), "upload.pdf", "application/pdf")
    await asyncio.sleep(0)
    assert states == ["running:starting", "running:embedding", "running:indexing", "done:done"]
    assert not source.exists()



@pytest.mark.asyncio
async def test_startup_recovers_only_interrupted_jobs():
    from app.core.database import Base
    from app.api.ingest import recover_interrupted_ingest_jobs
    from app.models.ingest_job import IngestJob, IngestJobStatusValue as Status

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:
        for state in Status:
            session.add(IngestJob(id=state.value, source_type="pdf", status=state, phase=state.value))
        await session.commit()
    with patch("app.api.ingest.AsyncSessionLocal", sessions):
        await recover_interrupted_ingest_jobs()
        await recover_interrupted_ingest_jobs()
    async with sessions() as session:
        for state in Status:
            job = await session.get(IngestJob, state.value)
            assert job.status == (Status.error if state in (Status.queued, Status.running) else state)
    await engine.dispose()



@pytest.mark.parametrize("path", ["/api/v1/ingest/pdf", "/api/v1/ingest/pdf/jobs"])
def test_upload_limit_returns_413_and_removes_partial_file(path, monkeypatch, tmp_path):
    from app.main import app
    from app.core.deps import get_current_user
    from app.core.database import get_db

    monkeypatch.setattr(settings, "upload_max_bytes", 4)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    app.dependency_overrides[get_current_user] = lambda: MagicMock()
    async def db():
        yield MagicMock()
    app.dependency_overrides[get_db] = db
    try:
        response = TestClient(app).post(path, files={"file": ("test.pdf", io.BytesIO(b"12345"), "application/pdf")})
        assert response.status_code == 413
        assert list(tmp_path.iterdir()) == []
    finally:
        app.dependency_overrides.clear()



@pytest.mark.asyncio
async def test_embedding_failure_never_deletes_existing_source():
    from app.services.ingestion.youtube import ingest_youtube

    embedder = MagicMock()
    embedder.embed_independently.side_effect = RuntimeError("embedding failed")
    client = MagicMock()
    with (
        patch("app.services.ingestion.youtube._fetch_transcript", return_value=[{"text": "text", "start": 0, "duration": 5}]),
        patch("app.services.ingestion.youtube._get_video_metadata", return_value={"video_id": "abc", "title": "test", "channel": "test"}),
        patch("app.services.ingestion.youtube.get_embedder", return_value=embedder),
        patch("app.services.ingestion.youtube.get_qdrant_client", return_value=client),
    ):
        with pytest.raises(RuntimeError, match="embedding failed"):
            await ingest_youtube("https://youtu.be/abc")
    client.delete.assert_not_called()
    client.upsert.assert_not_called()



@pytest.mark.asyncio
async def test_api_startup_runs_job_recovery():
    from app.main import lifespan

    with (
        patch("app.main._refuse_default_secret_in_production"),
        patch("app.main.create_all_tables", AsyncMock()),
        patch("app.main.ingest.recover_interrupted_ingest_jobs", AsyncMock()) as recover,
    ):
        async with lifespan(None):
            recover.assert_awaited_once()
