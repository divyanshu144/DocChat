import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
import io


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_ingest_pdf_returns_source_id(client):
    with patch("app.api.ingest.ingest_pdf", new=AsyncMock(return_value="src-123")):
        response = client.post(
            "/api/v1/ingest/pdf",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json()["source_id"] == "src-123"


def test_ingest_youtube_returns_source_id(client):
    with patch("app.api.ingest.ingest_youtube", new=AsyncMock(return_value="src-456")):
        response = client.post(
            "/api/v1/ingest/youtube",
            json={"url": "https://youtube.com/watch?v=abc123"},
        )
    assert response.status_code == 200
    assert response.json()["source_id"] == "src-456"


def test_ingest_web_returns_source_id(client):
    with patch("app.api.ingest.ingest_web", new=AsyncMock(return_value="src-789")):
        response = client.post(
            "/api/v1/ingest/web",
            json={"url": "https://example.com/article"},
        )
    assert response.status_code == 200
    assert response.json()["source_id"] == "src-789"


def test_list_sources_returns_empty_on_no_data(client):
    mock_client = MagicMock()
    mock_client.scroll.return_value = ([], None)
    with (
        patch("app.api.ingest.get_qdrant_client", return_value=mock_client),
        patch("app.api.ingest.get_qdrant_collection"),
    ):
        response = client.get("/api/v1/sources")
    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_list_sources_reads_normalized_collection_and_future_source_type(client):
    mock_client = MagicMock()
    point = MagicMock()
    point.payload = {
        "source_id": "src-1",
        "source_type": "slack",
        "title": "Incident channel",
        "ingested_at": "2026-07-30T10:00:00+00:00",
    }
    mock_client.scroll.side_effect = [([point], None), ([], None), ([], None), ([], None)]

    with (
        patch("app.api.ingest.get_qdrant_client", return_value=mock_client),
        patch("app.api.ingest.get_qdrant_collection"),
    ):
        response = client.get("/api/v1/sources")

    assert response.status_code == 200
    assert response.json()["sources"] == [{
        "source_id": "src-1",
        "source_type": "slack",
        "title": "Incident channel",
        "ingested_at": "2026-07-30T10:00:00+00:00",
    }]
    assert mock_client.scroll.call_args_list[0].kwargs["collection_name"] == "source_chunks"


def test_get_ingest_job_reads_persisted_status():
    from app.core.database import get_db
    from app.main import app
    from app.models.ingest_job import IngestJobStatusValue

    job = MagicMock()
    job.id = "job-1"
    job.source_type = "web"
    job.status = IngestJobStatusValue.done
    job.phase = "done"
    job.message = "Ingested web"
    job.source_id = "src-1"
    job.error = None

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=job)
        yield session

    app.dependency_overrides[get_db] = mock_db
    c = TestClient(app)
    response = c.get("/api/v1/ingest/jobs/job-1")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-1",
        "source_type": "web",
        "status": "done",
        "phase": "done",
        "message": "Ingested web",
        "source_id": "src-1",
        "error": None,
    }


def test_start_web_ingest_job_persists_queued_job():
    from app.core.database import get_db
    from app.main import app

    async def mock_db():
        session = MagicMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_db] = mock_db
    c = TestClient(app)
    with patch("app.api.ingest._run_url_ingest_job", new=AsyncMock()):
        response = c.post("/api/v1/ingest/web/jobs", json={"url": "https://example.com"})
    app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
