---
type: community
cohesion: 0.25
members: 8
---

# Ingestion Test Suite / Bug #3 (High): _chunk_segments

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[Bug 3 (High) _chunk_segments blocks event loop]] - document - reports/docchat-audit.md
- [[Ingestion Test Suite]] - code - tests/test_ingestion.py
- [[test_chunk_segments_basic]] - code - tests/test_ingestion.py
- [[test_chunk_segments_chunk_dict_keys]] - code - tests/test_ingestion.py
- [[test_chunk_segments_empty_input]] - code - tests/test_ingestion.py
- [[test_chunk_segments_no_empty_text]] - code - tests/test_ingestion.py
- [[test_chunk_segments_preserves_metadata]] - code - tests/test_ingestion.py
- [[test_chunk_segments_whitespace_only_skipped]] - code - tests/test_ingestion.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Ingestion_Test_Suite_/_Bug_#3_(High):__chunk_segments
SORT file.name ASC
```
