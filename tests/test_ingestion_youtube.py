import pytest
import numpy as np
from unittest.mock import MagicMock, patch


def test_extract_video_id_from_watch_url():
    from app.services.ingestion.youtube import _extract_video_id
    assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_from_short_url():
    from app.services.ingestion.youtube import _extract_video_id
    assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_chunk_transcript_groups_by_duration():
    from app.services.ingestion.youtube import _chunk_transcript
    transcript = [
        {"text": "Hello", "start": 0.0, "duration": 5.0},
        {"text": "world", "start": 5.0, "duration": 5.0},
        {"text": "end", "start": 65.0, "duration": 5.0},
    ]
    chunks = _chunk_transcript(transcript)
    assert len(chunks) == 2
    assert "Hello" in chunks[0]["text"]
    assert "end" in chunks[1]["text"]


@pytest.mark.asyncio
async def test_ingest_youtube_stores_chunks():
    mock_collection = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    fake_transcript = [{"text": "attention is all you need", "start": 0.0, "duration": 30.0}]
    fake_meta = {"title": "Lecture 1", "channel": "MIT OCW", "video_id": "abc123"}

    with (
        patch("app.services.ingestion.youtube.get_collection", return_value=mock_collection),
        patch("app.services.ingestion.youtube.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.youtube._fetch_transcript", return_value=fake_transcript),
        patch("app.services.ingestion.youtube._get_video_metadata", return_value=fake_meta),
        patch("app.services.ingestion.youtube._extract_video_id", return_value="abc123"),
    ):
        from app.services.ingestion.youtube import ingest_youtube
        source_id = await ingest_youtube("https://youtube.com/watch?v=abc123")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_collection.add.assert_called_once()
    meta = mock_collection.add.call_args[1]["metadatas"][0]
    assert meta["title"] == "Lecture 1"
    assert meta["channel"] == "MIT OCW"
    assert meta["source_id"] == source_id
