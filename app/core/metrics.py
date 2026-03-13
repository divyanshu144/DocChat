"""Prometheus metrics for DocChat.

Exposes counters and histograms for the key pipeline stages.
Served at GET /metrics by the FastAPI app.
"""

from prometheus_client import Counter, Histogram

ingestion_duration = Histogram(
    "docchat_ingestion_duration_seconds",
    "Wall-clock time to ingest a document (extract + chunk + embed + persist)",
)

retrieval_duration = Histogram(
    "docchat_retrieval_duration_seconds",
    "Wall-clock time for the full retrieval step (BM25 + semantic + RRF)",
)

rerank_duration = Histogram(
    "docchat_rerank_duration_seconds",
    "Wall-clock time for cross-encoder re-ranking",
)

llm_duration = Histogram(
    "docchat_llm_duration_seconds",
    "Wall-clock time for a complete (non-streaming) LLM reply",
)

llm_stream_duration = Histogram(
    "docchat_llm_stream_duration_seconds",
    "Wall-clock time for a streaming LLM reply to complete",
)

ingestion_chunks = Counter(
    "docchat_ingestion_chunks_total",
    "Total chunks created across all ingestion jobs",
)

semantic_cache_hits = Counter(
    "docchat_semantic_cache_hits_total",
    "Queries answered directly from the semantic cache",
)

semantic_cache_misses = Counter(
    "docchat_semantic_cache_misses_total",
    "Queries that missed the semantic cache and ran the full pipeline",
)

hyde_expansions = Counter(
    "docchat_hyde_expansions_total",
    "Number of HyDE query expansions performed",
)
