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
    mock_col = MagicMock()
    mock_col.get.return_value = {"metadatas": []}
    with patch("app.api.ingest.get_collection", return_value=mock_col):
        response = client.get("/api/v1/sources")
    assert response.status_code == 200
    assert response.json()["sources"] == []
