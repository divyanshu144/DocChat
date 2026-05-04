---
source_file: "app/services/ingestion.py"
type: "code"
community: "_Segment / _chunk_segments()"
location: "L31"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/_Segment_/__chunk_segments()
---

# _Segment

## Connections
- [[Chunk]] - `uses` [INFERRED]
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[LateChunkingEmbedder]] - `uses` [INFERRED]
- [[_extract_docx_segments()]] - `calls` [EXTRACTED]
- [[_extract_pdf_segments()]] - `calls` [EXTRACTED]
- [[_extract_segments()]] - `calls` [EXTRACTED]
- [[ingestion.py]] - `contains` [EXTRACTED]
- [[test_chunk_segments_basic()]] - `calls` [INFERRED]
- [[test_chunk_segments_chunk_dict_keys()]] - `calls` [INFERRED]
- [[test_chunk_segments_no_empty_text()]] - `calls` [INFERRED]
- [[test_chunk_segments_preserves_metadata()]] - `calls` [INFERRED]
- [[test_chunk_segments_whitespace_only_skipped()]] - `calls` [INFERRED]

#graphify/code #graphify/INFERRED #community/_Segment_/__chunk_segments()