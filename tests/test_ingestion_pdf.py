import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


@dataclass
class FakeSegment:
    text: str
    page_number: int = 1
    section_heading: str = "Intro"


@pytest.mark.asyncio
async def test_ingest_pdf_stores_chunks_in_qdrant():
    mock_client = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_late.return_value = [np.array([0.1] * 384, dtype="float32")]
    mock_embedder.embed_independently.return_value = [np.array([0.1] * 384, dtype="float32")]

    fake_segments = [FakeSegment(text="Sample text", page_number=1, section_heading="Intro")]
    fake_chunks = [{"text": "Sample text", "page_number": 1, "section_heading": "Intro",
                    "seg_idx": 0, "char_start": 0}]

    with (
        patch("app.services.ingestion.pdf.get_qdrant_collection"),
        patch("app.services.ingestion.pdf.get_qdrant_client", return_value=mock_client),
        patch("app.services.ingestion.pdf.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.pdf._extract_segments", return_value=fake_segments),
        patch("app.services.ingestion.pdf._chunk_segments", return_value=fake_chunks),
        patch("app.services.ingestion.pdf._file_sha256", return_value="abc123"),
        patch("app.services.ingestion.pdf._embed_chunks_late",
              return_value=[np.array([0.1] * 384, dtype="float32")]),
    ):
        from app.services.ingestion.pdf import ingest_pdf
        source_id = await ingest_pdf("/fake/path.pdf", "test.pdf", "application/pdf")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_client.upsert.assert_called_once()
    call_kwargs = mock_client.upsert.call_args[1]
    points = call_kwargs["points"]
    assert len(points) == 1
    assert points[0].payload["text"] == "Sample text"
    assert points[0].payload["filename"] == "test.pdf"
    assert points[0].payload["source_id"] == source_id


@pytest.mark.asyncio
async def test_ingest_pdf_reupload_uses_same_source_and_point_ids():
    mock_client = MagicMock()
    mock_embedder = MagicMock()
    fake_segments = [FakeSegment(text="Sample text", page_number=1, section_heading="Intro")]
    fake_chunks = [{"text": "Sample text", "page_number": 1, "section_heading": "Intro",
                    "seg_idx": 0, "char_start": 0}]
    embedding = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.services.ingestion.pdf.get_qdrant_collection"),
        patch("app.services.ingestion.pdf.get_qdrant_client", return_value=mock_client),
        patch("app.services.ingestion.pdf.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.pdf._extract_segments", return_value=fake_segments),
        patch("app.services.ingestion.pdf._chunk_segments", return_value=fake_chunks),
        patch("app.services.ingestion.pdf._file_sha256", return_value="same-content"),
        patch("app.services.ingestion.pdf._embed_chunks_late", return_value=[embedding]),
    ):
        from app.services.ingestion.pdf import ingest_pdf
        source_id_1 = await ingest_pdf("/fake/path.pdf", "test.pdf", "application/pdf")
        point_id_1 = mock_client.upsert.call_args_list[0].kwargs["points"][0].id
        source_id_2 = await ingest_pdf("/fake/path.pdf", "test.pdf", "application/pdf")
        point_id_2 = mock_client.upsert.call_args_list[1].kwargs["points"][0].id

    assert source_id_1 == source_id_2
    assert point_id_1 == point_id_2
