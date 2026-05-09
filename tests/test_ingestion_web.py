import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.services.ingestion.web import _scrape


def test_scrape_extracts_content_and_title():
    fake_html = "<html><head><title>Test Page</title></head><body><p>Hello world content here.</p></body></html>"

    with (
        patch("app.services.ingestion.web.httpx.get") as mock_get,
        patch("app.services.ingestion.web.trafilatura.extract", return_value="Hello world content here."),
    ):
        mock_resp = MagicMock()
        mock_resp.text = fake_html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = _scrape("https://example.com")

    assert result["content"] == "Hello world content here."
    assert result["title"] == "Test Page"


@pytest.mark.asyncio
async def test_ingest_web_stores_chunks():
    mock_collection = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    fake_scraped = {"content": "Article content about AI.", "title": "AI News"}

    with (
        patch("app.services.ingestion.web.get_collection", return_value=mock_collection),
        patch("app.services.ingestion.web.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.web._scrape", return_value=fake_scraped),
    ):
        from app.services.ingestion.web import ingest_web
        source_id = await ingest_web("https://example.com/article")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_collection.add.assert_called_once()
    meta = mock_collection.add.call_args[1]["metadatas"][0]
    assert meta["url"] == "https://example.com/article"
    assert meta["title"] == "AI News"
    assert meta["domain"] == "example.com"
    assert meta["source_id"] == source_id
