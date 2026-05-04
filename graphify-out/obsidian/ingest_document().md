---
source_file: "app/services/ingestion.py"
type: "code"
community: "benchmark.py / ingest_document()"
location: "L218"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/benchmark.py_/_ingest_document()
---

# ingest_document()

## Connections
- [[Chunk]] - `calls` [INFERRED]
- [[Exception]] - `calls` [INFERRED]
- [[Extract → chunk → late-chunk embed → persist; delete raw file on completion.]] - `rationale_for` [EXTRACTED]
- [[_run_ingestion_bg()]] - `calls` [INFERRED]
- [[delete_file()]] - `calls` [INFERRED]
- [[download_for_processing()]] - `calls` [INFERRED]
- [[get_embedder()]] - `calls` [INFERRED]
- [[ingest_document_task()]] - `calls` [INFERRED]
- [[ingestion.py]] - `contains` [EXTRACTED]
- [[invalidate_bm25()]] - `calls` [INFERRED]
- [[main()]] - `calls` [INFERRED]
- [[run_cache_benchmark()]] - `calls` [INFERRED]
- [[run_ingestion_benchmark()]] - `calls` [INFERRED]
- [[run_rerank_benchmark()]] - `calls` [INFERRED]
- [[run_retrieval_benchmark()]] - `calls` [INFERRED]
- [[run_scale_benchmark()]] - `calls` [INFERRED]
- [[str]] - `calls` [INFERRED]

#graphify/code #graphify/INFERRED #community/benchmark.py_/_ingest_document()