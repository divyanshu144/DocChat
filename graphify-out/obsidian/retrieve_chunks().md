---
source_file: "app/services/retrieval.py"
type: "code"
community: "retrieval.py / retrieve_chunks()"
location: "L273"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/retrieval.py_/_retrieve_chunks()
---

# retrieve_chunks()

## Connections
- [[.set()]] - `calls` [INFERRED]
- [[Return top-k chunk texts (with metadata prefix) using hybrid BM25 + semantic RRF]] - `rationale_for` [EXTRACTED]
- [[_build_cache_entry()]] - `calls` [EXTRACTED]
- [[_cosine_similarities()]] - `calls` [EXTRACTED]
- [[_format_chunk()]] - `calls` [EXTRACTED]
- [[_get_embedder()]] - `calls` [EXTRACTED]
- [[_redis_cache_get()]] - `calls` [EXTRACTED]
- [[_redis_cache_set()]] - `calls` [EXTRACTED]
- [[_rrf()]] - `calls` [EXTRACTED]
- [[_run_retrieval_pipeline()]] - `calls` [INFERRED]
- [[_tokenize()]] - `calls` [EXTRACTED]
- [[retrieval.py]] - `contains` [EXTRACTED]
- [[run_rerank_benchmark()]] - `calls` [INFERRED]
- [[run_retrieval_benchmark()]] - `calls` [INFERRED]
- [[run_scale_benchmark()]] - `calls` [INFERRED]

#graphify/code #graphify/EXTRACTED #community/retrieval.py_/_retrieve_chunks()