import asyncio
import logging

import numpy as np
from cachetools import LRUCache
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk

logger = logging.getLogger(__name__)

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
# NLTK tokenizer — stemming + stopword filtering
# Falls back to plain .lower().split() if NLTK is not installed.
# ---------------------------------------------------------------------------

try:
    import nltk
    from nltk.corpus import stopwords
    from nltk.stem import PorterStemmer
    nltk.download("stopwords", quiet=True)
    _stemmer = PorterStemmer()
    _stopwords = set(stopwords.words("english"))
    _nltk_available = True
except Exception:
    _nltk_available = False


def _tokenize(text: str) -> list[str]:
    tokens = text.lower().split()
    if _nltk_available:
        return [_stemmer.stem(t) for t in tokens if t.isalpha() and t not in _stopwords]
    return tokens


# ---------------------------------------------------------------------------
# Embedding blob loader — auto-detects float16 vs float32 by byte length
# ---------------------------------------------------------------------------

def _load_embedding_blob(blob: bytes) -> np.ndarray:
    from app.core.config import settings
    if len(blob) == settings.embedding_dim * 2:
        return np.frombuffer(blob, dtype=np.float16).astype(np.float32)
    return np.frombuffer(blob, dtype=np.float32)


# ---------------------------------------------------------------------------
# LRU retrieval cache — document_id → (BM25Okapi, chunks, emb_matrix, emb_indices)
#
# maxsize=50: at ~10 MB per doc this caps RAM at ~500 MB.
# ---------------------------------------------------------------------------

_retrieval_cache: LRUCache = LRUCache(maxsize=50)


def invalidate_bm25(document_id: str) -> None:
    """Evict a document's cache entry — call this after re-ingestion."""
    _retrieval_cache.pop(document_id, None)


def _build_cache_entry(chunks: list) -> tuple:
    tokenized = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(tokenized)

    embedded_pairs = [(i, c) for i, c in enumerate(chunks) if c.embedding]
    if embedded_pairs:
        # Deserialise once and build a contiguous matrix — all future queries
        # just do a single matrix-vector multiply (no repeated frombuffer calls).
        emb_matrix = np.stack([_load_embedding_blob(c.embedding) for _, c in embedded_pairs])
        emb_indices = [i for i, _ in embedded_pairs]
    else:
        emb_matrix, emb_indices = None, []

    return bm25, list(chunks), emb_matrix, emb_indices


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------

def _cosine_similarities(query_emb: np.ndarray, chunk_embs: np.ndarray) -> np.ndarray:
    query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)
    chunk_norms = chunk_embs / (np.linalg.norm(chunk_embs, axis=1, keepdims=True) + 1e-10)
    return chunk_norms @ query_norm


def _rrf(rank_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, idx in enumerate(ranks):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _format_chunk(chunk) -> str:
    """Prefix chunk text with page / section metadata for LLM grounding."""
    parts: list[str] = []
    if chunk.page_number is not None:
        parts.append(f"Page {chunk.page_number}")
    if chunk.section_heading:
        parts.append(f'Section "{chunk.section_heading}"')
    prefix = f"[{', '.join(parts)}] " if parts else ""
    return prefix + chunk.text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def embed_query(query: str) -> np.ndarray | None:
    """Embed a single query string; returns None if fastembed is unavailable."""
    embedder = _get_embedder()
    if embedder is None:
        return None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: np.array(next(embedder.embed([query])), dtype=np.float32)
    )


async def retrieve_chunks(
    query: str,
    document_id: str,
    db: AsyncSession,
    top_k: int,
    expanded_query: str | None = None,
    query_emb: np.ndarray | None = None,
) -> list[str]:
    """Return top-k chunk texts (with metadata prefix) using hybrid BM25 + semantic RRF.

    Args:
        expanded_query: HyDE-generated hypothetical answer; used for the semantic
                        embedding instead of the raw query when provided.
        query_emb:      Pre-computed query embedding (avoids re-embedding when the
                        caller already has it, e.g. for semantic cache lookup).
    """
    if document_id not in _retrieval_cache:
        result = await db.execute(
            select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
        )
        chunks = result.scalars().all()
        if not chunks:
            return []
        _retrieval_cache[document_id] = _build_cache_entry(chunks)

    bm25, cached_chunks, emb_matrix, emb_indices = _retrieval_cache[document_id]
    if not cached_chunks:
        return []

    # BM25 (always available)
    bm25_ranks: list[int] = list(np.argsort(bm25.get_scores(_tokenize(query)))[::-1])
    rank_lists = [bm25_ranks]

    # Semantic (requires embedder + pre-built matrix)
    embedder = _get_embedder()
    if embedder is not None and emb_matrix is not None:
        # Use pre-computed embedding when available; re-embed HyDE text or raw query otherwise
        if query_emb is None:
            search_text = expanded_query if expanded_query else query
            loop = asyncio.get_running_loop()
            query_emb = await loop.run_in_executor(
                None, lambda: np.array(next(embedder.embed([search_text])), dtype=np.float32)
            )

        cos_sims = _cosine_similarities(query_emb, emb_matrix)
        semantic_order = list(np.argsort(cos_sims)[::-1])
        semantic_ranks = [emb_indices[j] for j in semantic_order]

        embedded_set = set(emb_indices)
        semantic_ranks += [i for i in range(len(cached_chunks)) if i not in embedded_set]
        rank_lists.append(semantic_ranks)

    rrf_scores = _rrf(rank_lists)
    top_indices = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:top_k]
    return [_format_chunk(cached_chunks[i]) for i in top_indices]
