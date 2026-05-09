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
async def test_ingest_pdf_stores_chunks_in_chromadb():
    mock_collection = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_late.return_value = [np.array([0.1] * 384, dtype="float32")]
    mock_embedder.embed_independently.return_value = [np.array([0.1] * 384, dtype="float32")]

    fake_segments = [FakeSegment(text="Sample text", page_number=1, section_heading="Intro")]
    fake_chunks = [{"text": "Sample text", "page_number": 1, "section_heading": "Intro",
                    "seg_idx": 0, "char_start": 0}]

    with (
        patch("app.services.ingestion.pdf.get_collection", return_value=mock_collection),
        patch("app.services.ingestion.pdf.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.pdf._extract_segments", return_value=fake_segments),
        patch("app.services.ingestion.pdf._chunk_segments", return_value=fake_chunks),
        patch("app.services.ingestion.pdf._embed_chunks_late",
              return_value=[np.array([0.1] * 384, dtype="float32")]),
    ):
        from app.services.ingestion.pdf import ingest_pdf
        source_id = await ingest_pdf("/fake/path.pdf", "test.pdf", "application/pdf")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_collection.add.assert_called_once()
    call_kwargs = mock_collection.add.call_args[1]
    assert len(call_kwargs["ids"]) == 1
    assert call_kwargs["documents"] == ["Sample text"]
    assert call_kwargs["metadatas"][0]["filename"] == "test.pdf"
    assert call_kwargs["metadatas"][0]["source_id"] == source_id
