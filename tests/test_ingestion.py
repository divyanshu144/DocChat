"""Tests for Bug #3 fix: _chunk_segments runs safely off the event loop.

_chunk_segments is a pure synchronous function — it holds no async state and
uses only CPU-bound langchain text splitting.  Running it in an executor
(loop.run_in_executor) is safe precisely because it is pure sync.  These tests
verify the function's contract so any future regression (e.g. re-introducing
an async call inside it) would break here first.
"""

from app.services.ingestion import _Segment, _chunk_segments


def test_chunk_segments_basic():
    """_chunk_segments returns at least one chunk for non-trivial input."""
    segments = [
        _Segment(
            text="This is a test document. " * 20,
            page_number=1,
            section_heading="Intro",
        )
    ]
    chunks = _chunk_segments(segments)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert "text" in chunk
        assert chunk["page_number"] == 1
        assert chunk["section_heading"] == "Intro"


def test_chunk_segments_preserves_metadata():
    """Each chunk carries the page_number and section_heading of its source segment."""
    segments = [
        _Segment(text="Hello world. " * 50, page_number=2, section_heading="Methods"),
        _Segment(text="Another segment. " * 30, page_number=3, section_heading=None),
    ]
    chunks = _chunk_segments(segments)

    page2_chunks = [c for c in chunks if c["page_number"] == 2]
    page3_chunks = [c for c in chunks if c["page_number"] == 3]

    assert len(page2_chunks) >= 1, "Expected chunks from page 2"
    assert len(page3_chunks) >= 1, "Expected chunks from page 3"

    assert all(c["section_heading"] == "Methods" for c in page2_chunks)
    assert all(c["section_heading"] is None for c in page3_chunks)


def test_chunk_segments_empty_input():
    """Empty segment list produces empty chunk list without error."""
    assert _chunk_segments([]) == []


def test_chunk_segments_whitespace_only_skipped():
    """Segments whose text is whitespace-only produce no chunks."""
    segments = [_Segment(text="   \n\n   ", page_number=1, section_heading=None)]
    chunks = _chunk_segments(segments)
    assert chunks == []


def test_chunk_segments_chunk_dict_keys():
    """Each chunk dict contains the required keys."""
    segments = [_Segment(text="Some content. " * 10, page_number=5, section_heading="Results")]
    chunks = _chunk_segments(segments)
    required_keys = {"text", "page_number", "section_heading"}
    for chunk in chunks:
        assert required_keys.issubset(chunk.keys()), f"Missing keys in chunk: {chunk.keys()}"


def test_chunk_segments_no_empty_text():
    """No chunk has an empty or whitespace-only text field."""
    segments = [_Segment(text="Word. " * 100, page_number=1, section_heading=None)]
    chunks = _chunk_segments(segments)
    for chunk in chunks:
        assert chunk["text"].strip(), "Chunk text must not be empty or whitespace-only"
