---
source_file: "app/services/retrieval.py"
type: "code"
community: "benchmark.py / ingest_document()"
location: "L190"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/benchmark.py_/_ingest_document()
---

# invalidate_bm25()

## Connections
- [[Evict a document's entry from L1 LRU, Redis L2, and the semantic cache.]] - `rationale_for` [EXTRACTED]
- [[_redis_cache_delete()]] - `calls` [EXTRACTED]
- [[ingest_document()]] - `calls` [INFERRED]
- [[invalidate_semantic_cache()]] - `calls` [INFERRED]
- [[retrieval.py]] - `contains` [EXTRACTED]
- [[run_rerank_benchmark()]] - `calls` [INFERRED]
- [[run_retrieval_benchmark()]] - `calls` [INFERRED]
- [[run_scale_benchmark()]] - `calls` [INFERRED]

#graphify/code #graphify/INFERRED #community/benchmark.py_/_ingest_document()