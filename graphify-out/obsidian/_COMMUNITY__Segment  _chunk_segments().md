---
type: community
cohesion: 0.16
members: 22
---

# _Segment / _chunk_segments()

**Cohesion:** 0.16 - loosely connected
**Members:** 22 nodes

## Members
- [[Each chunk carries the page_number and section_heading of its source segment.]] - rationale - tests/test_ingestion.py
- [[Each chunk dict contains the required keys.]] - rationale - tests/test_ingestion.py
- [[Empty segment list produces empty chunk list without error.]] - rationale - tests/test_ingestion.py
- [[No chunk has an empty or whitespace-only text field.]] - rationale - tests/test_ingestion.py
- [[Segments whose text is whitespace-only produce no chunks.]] - rationale - tests/test_ingestion.py
- [[Tests for Bug 3 fix _chunk_segments runs safely off the event loop.  _chunk_se]] - rationale - tests/test_ingestion.py
- [[_Segment]] - code - app/services/ingestion.py
- [[_chunk_segments returns at least one chunk for non-trivial input.]] - rationale - tests/test_ingestion.py
- [[_chunk_segments()]] - code - app/services/ingestion.py
- [[_detect_pdf_heading()]] - code - app/services/ingestion.py
- [[_extract_docx_segments()]] - code - app/services/ingestion.py
- [[_extract_pdf_segments()]] - code - app/services/ingestion.py
- [[_extract_segments()]] - code - app/services/ingestion.py
- [[_get_splitter()]] - code - app/services/ingestion.py
- [[ingestion.py]] - code - app/services/ingestion.py
- [[test_chunk_segments_basic()]] - code - tests/test_ingestion.py
- [[test_chunk_segments_chunk_dict_keys()]] - code - tests/test_ingestion.py
- [[test_chunk_segments_empty_input()]] - code - tests/test_ingestion.py
- [[test_chunk_segments_no_empty_text()]] - code - tests/test_ingestion.py
- [[test_chunk_segments_preserves_metadata()]] - code - tests/test_ingestion.py
- [[test_chunk_segments_whitespace_only_skipped()]] - code - tests/test_ingestion.py
- [[test_ingestion.py]] - code - tests/test_ingestion.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/_Segment_/__chunk_segments()
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Document  DocumentStatus]]
- 4 edges to [[_COMMUNITY_benchmark.py  ingest_document()]]
- 2 edges to [[_COMMUNITY_LateChunkingEmbedder  .embed_query()]]
- 2 edges to [[_COMMUNITY_retrieval.py  retrieve_chunks()]]

## Top bridge nodes
- [[_Segment]] - degree 13, connects to 2 communities
- [[_chunk_segments()]] - degree 10, connects to 2 communities
- [[ingestion.py]] - degree 9, connects to 2 communities
- [[_detect_pdf_heading()]] - degree 4, connects to 2 communities
- [[_extract_pdf_segments()]] - degree 6, connects to 1 community