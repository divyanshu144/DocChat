---
source_file: "app/services/retrieval.py"
type: "rationale"
community: "benchmark.py / ingest_document()"
location: "L191"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/benchmark.py_/_ingest_document()
---

# Evict a document's entry from L1 LRU, Redis L2, and the semantic cache.

## Connections
- [[Chunk]] - `uses` [INFERRED]
- [[invalidate_bm25()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/benchmark.py_/_ingest_document()