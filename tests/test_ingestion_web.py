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
    mock_client = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    fake_scraped = {"content": "Article content about AI.", "title": "AI News"}

    with (
        patch("app.services.ingestion.web.get_qdrant_collection"),
        patch("app.services.ingestion.web.get_qdrant_client", return_value=mock_client),
        patch("app.services.ingestion.web.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.web._scrape", return_value=fake_scraped),
    ):
        from app.services.ingestion.web import ingest_web
        source_id = await ingest_web("https://example.com/article")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_client.upsert.assert_called_once()
    call_kwargs = mock_client.upsert.call_args[1]
    points = call_kwargs["points"]
    assert len(points) == 1
    payload = points[0].payload
    assert payload["url"] == "https://example.com/article"
    assert payload["title"] == "AI News"
    assert payload["domain"] == "example.com"
    assert payload["source_id"] == source_id


@pytest.mark.asyncio
async def test_ingest_web_reupload_uses_same_source_and_point_ids_for_normalized_url():
    mock_client = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")
    fake_scraped = {"content": "Article content about AI.", "title": "AI News"}

    with (
        patch("app.services.ingestion.web.get_qdrant_collection"),
        patch("app.services.ingestion.web.get_qdrant_client", return_value=mock_client),
        patch("app.services.ingestion.web.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.web._scrape", return_value=fake_scraped),
    ):
        from app.services.ingestion.web import ingest_web
        source_id_1 = await ingest_web("https://EXAMPLE.com/article?b=2&a=1#frag")
        point_id_1 = mock_client.upsert.call_args_list[0].kwargs["points"][0].id
        source_id_2 = await ingest_web("https://example.com/article?a=1&b=2")
        point_id_2 = mock_client.upsert.call_args_list[1].kwargs["points"][0].id

    assert source_id_1 == source_id_2
    assert point_id_1 == point_id_2
