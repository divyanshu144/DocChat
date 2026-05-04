---
source_file: "app/services/retrieval.py"
type: "code"
community: "retrieve_chunks / ingest_document"
location: "line 190"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/retrieve_chunks_/_ingest_document
---

# invalidate_bm25

## Connections
- [[LRU retrieval cache (L1)]] - `shares_data_with` [EXTRACTED]
- [[ingest_document]] - `calls` [EXTRACTED]
- [[invalidate_semantic_cache]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/retrieve_chunks_/_ingest_document