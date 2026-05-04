---
source_file: "app/services/retrieval.py"
type: "code"
community: "retrieve_chunks / ingest_document"
location: "line 127"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/retrieve_chunks_/_ingest_document
---

# LRU retrieval cache (L1)

## Connections
- [[SemanticCache class]] - `semantically_similar_to` [INFERRED]
- [[invalidate_bm25]] - `shares_data_with` [EXTRACTED]
- [[retrieve_chunks]] - `shares_data_with` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/retrieve_chunks_/_ingest_document