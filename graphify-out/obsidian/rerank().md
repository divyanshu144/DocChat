---
source_file: "app/services/reranker.py"
type: "code"
community: "benchmark.py / ingest_document()"
location: "L30"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/benchmark.py_/_ingest_document()
---

# rerank()

## Connections
- [[Exception]] - `calls` [INFERRED]
- [[Re-rank chunks by relevance to query; return the top_k highest-scoring ones.]] - `rationale_for` [EXTRACTED]
- [[_get_ranker()]] - `calls` [EXTRACTED]
- [[_run_retrieval_pipeline()]] - `calls` [INFERRED]
- [[reranker.py]] - `contains` [EXTRACTED]
- [[run_rerank_benchmark()]] - `calls` [INFERRED]

#graphify/code #graphify/EXTRACTED #community/benchmark.py_/_ingest_document()