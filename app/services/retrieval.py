import asyncio

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk

# ---------------------------------------------------------------------------
# Embedder singleton (fastembed ONNX, no PyTorch required)
# ---------------------------------------------------------------------------

try:
    from fastembed import TextEmbedding as _TextEmbedding
    _fastembed_available = True
except ImportError:
    _fastembed_available = False

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None and _fastembed_available:
        from app.core.config import settings
        _embedder = _TextEmbedding(settings.embedding_model)
    return _embedder


# ---------------------------------------------------------------------------
# BM25 module-level cache: document_id → (BM25Okapi, list[Chunk])
# ---------------------------------------------------------------------------

_bm25_cache: dict[str, tuple[BM25Okapi, list]] = {}


def invalidate_bm25(document_id: str) -> None:
    """Remove cached BM25 index for a document (call after re-ingestion)."""
    _bm25_cache.pop(document_id, None)


def _get_bm25(document_id: str, chunks: list) -> tuple[BM25Okapi, list]:
    if document_id not in _bm25_cache:
        tokenized = [c.text.lower().split() for c in chunks]
        _bm25_cache[document_id] = (BM25Okapi(tokenized), list(chunks))
    return _bm25_cache[document_id]


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------

def _cosine_similarities(query_emb: np.ndarray, chunk_embs: np.ndarray) -> np.ndarray:
    query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)
    chunk_norms = chunk_embs / (np.linalg.norm(chunk_embs, axis=1, keepdims=True) + 1e-10)
    return chunk_norms @ query_norm


def _rrf(rank_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion across multiple ranked lists of chunk indices."""
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, idx in enumerate(ranks):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def retrieve_chunks(
    query: str, document_id: str, db: AsyncSession, top_k: int
) -> list[str]:
    """Return top-k relevant chunk texts using hybrid BM25 + semantic RRF."""
    result = await db.execute(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        return []

    # BM25 ranking (always available)
    bm25, cached_chunks = _get_bm25(document_id, chunks)
    tokenized_query = query.lower().split()
    bm25_scores = bm25.get_scores(tokenized_query)
    bm25_ranks: list[int] = list(np.argsort(bm25_scores)[::-1])

    rank_lists = [bm25_ranks]

    # Semantic ranking (only if embedder is available and chunks have embeddings)
    embedder = _get_embedder()
    embedded_pairs = [(i, c) for i, c in enumerate(cached_chunks) if c.embedding]

    if embedder is not None and embedded_pairs:
        loop = asyncio.get_running_loop()
        query_emb = await loop.run_in_executor(
            None, lambda: np.array(next(embedder.embed([query])), dtype=np.float32)
        )

        emb_indices = [i for i, _ in embedded_pairs]
        chunk_embs = np.stack([
            np.frombuffer(c.embedding, dtype=np.float32)
            for _, c in embedded_pairs
        ])

        cos_sims = _cosine_similarities(query_emb, chunk_embs)
        # Ranked within the embedded subset, then map back to full indices
        semantic_order = list(np.argsort(cos_sims)[::-1])
        semantic_ranks = [emb_indices[j] for j in semantic_order]

        # Append un-embedded chunks at the end so they can still be fused
        embedded_set = set(emb_indices)
        non_embedded = [i for i in range(len(cached_chunks)) if i not in embedded_set]
        semantic_ranks = semantic_ranks + non_embedded

        rank_lists.append(semantic_ranks)

    rrf_scores = _rrf(rank_lists)
    top_indices = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:top_k]
    return [cached_chunks[i].text for i in top_indices]
