---
type: community
cohesion: 0.11
members: 41
---

# benchmark.py / ingest_document()

**Cohesion:** 0.11 - loosely connected
**Members:** 41 nodes

## Members
- [[.close()]] - code - app/services/semantic_cache.py
- [[.set()]] - code - app/services/semantic_cache.py
- [[Cross-encoder re-ranking via FlashRank (ONNX, no PyTorch required).  FlashRank d]] - rationale - app/services/reranker.py
- [[Evict a document's entry from L1 LRU, Redis L2, and the semantic cache.]] - rationale - app/services/retrieval.py
- [[Exception]] - code
- [[Lazy-init singleton; returns None if ONNXtokenizers unavailable.]] - rationale - app/services/embedder.py
- [[Re-rank chunks by relevance to query; return the top_k highest-scoring ones.]] - rationale - app/services/reranker.py
- [[Store a (query_embedding, answer) pair for future cache lookups.]] - rationale - app/services/semantic_cache.py
- [[Yield a local Path ready for extraction. Downloads from S3 to a temp file if nee]] - rationale - app/services/storage.py
- [[_create_doc_record()]] - code - scripts/benchmark.py
- [[_fmt_bytes()]] - code - scripts/benchmark.py
- [[_fmt_ms()]] - code - scripts/benchmark.py
- [[_generate_pdf()]] - code - scripts/benchmark.py
- [[_get_ranker()]] - code - app/services/reranker.py
- [[_hr()]] - code - scripts/benchmark.py
- [[_json_default()]] - code - scripts/benchmark.py
- [[_percentile()]] - code - scripts/benchmark.py
- [[_to_json()]] - code - scripts/benchmark.py
- [[benchmark.py]] - code - scripts/benchmark.py
- [[chunks_per_sec()]] - code - scripts/benchmark.py
- [[download_for_processing()]] - code - app/services/storage.py
- [[get_embedder()]] - code - app/services/embedder.py
- [[ingest_document()]] - code - app/services/ingestion.py
- [[invalidate_bm25()]] - code - app/services/retrieval.py
- [[log_requests()]] - code - app/main.py
- [[main()]] - code - scripts/benchmark.py
- [[mean()]] - code - scripts/benchmark.py
- [[p50()]] - code - scripts/benchmark.py
- [[p95()]] - code - scripts/benchmark.py
- [[p99()]] - code - scripts/benchmark.py
- [[print_report()]] - code - scripts/benchmark.py
- [[rerank()]] - code - app/services/reranker.py
- [[reranker.py]] - code - app/services/reranker.py
- [[run_cache_benchmark()]] - code - scripts/benchmark.py
- [[run_ingestion_benchmark()]] - code - scripts/benchmark.py
- [[run_rerank_benchmark()]] - code - scripts/benchmark.py
- [[run_retrieval_benchmark()]] - code - scripts/benchmark.py
- [[run_scale_benchmark()]] - code - scripts/benchmark.py
- [[setup_db()]] - code - scripts/benchmark.py
- [[str]] - code
- [[teardown_db()]] - code - scripts/benchmark.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/benchmark.py_/_ingest_document()
SORT file.name ASC
```

## Connections to other communities
- 23 edges to [[_COMMUNITY_Document  DocumentStatus]]
- 13 edges to [[_COMMUNITY_retrieval.py  retrieve_chunks()]]
- 6 edges to [[_COMMUNITY_documents.py  FileTooLargeError]]
- 5 edges to [[_COMMUNITY_SemanticCache  get_semantic_cache()]]
- 4 edges to [[_COMMUNITY__Segment  _chunk_segments()]]
- 4 edges to [[_COMMUNITY_LateChunkingEmbedder  .embed_query()]]
- 2 edges to [[_COMMUNITY_database.py  main.py]]

## Top bridge nodes
- [[ingest_document()]] - degree 17, connects to 4 communities
- [[str]] - degree 15, connects to 4 communities
- [[run_cache_benchmark()]] - degree 12, connects to 3 communities
- [[Exception]] - degree 8, connects to 3 communities
- [[.set()]] - degree 7, connects to 3 communities