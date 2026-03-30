import asyncio
import io
import json
import logging
import struct
from dataclasses import dataclass

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
# CachedChunk — plain dataclass; safe to serialize with JSON (no pickle)
# ---------------------------------------------------------------------------

@dataclass
class CachedChunk:
    id: str
    text: str
    page_number: int | None
    section_heading: str | None


# ---------------------------------------------------------------------------
# Safe serialization for Redis — JSON + numpy binary (no pickle)
#
# Format: [4-byte big-endian meta_len][meta JSON bytes][numpy .npy bytes]
# BM25 is NOT stored — it is rebuilt cheaply from chunk text on load.
# This eliminates the RCE risk that pickle.loads() on untrusted Redis data
# would create if Redis were ever compromised or misconfigured.
# ---------------------------------------------------------------------------

def _serialize_for_redis(
    chunks: list[CachedChunk],
    emb_matrix,
    emb_indices: list,
) -> bytes:
    meta = {
        "chunks": [
            {
                "id": c.id,
                "text": c.text,
                "page_number": c.page_number,
                "section_heading": c.section_heading,
            }
            for c in chunks
        ],
        "emb_indices": emb_indices,
    }
    meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    buf = io.BytesIO()
    buf.write(struct.pack(">I", len(meta_bytes)))
    buf.write(meta_bytes)
    if emb_matrix is not None:
        np.save(buf, emb_matrix)
    return buf.getvalue()


def _deserialize_from_redis(data: bytes) -> tuple:
    buf = io.BytesIO(data)
    meta_len = struct.unpack(">I", buf.read(4))[0]
    meta = json.loads(buf.read(meta_len).decode("utf-8"))
    chunks = [CachedChunk(**d) for d in meta["chunks"]]
    emb_indices = meta["emb_indices"]
    rest = buf.read()
    emb_matrix = np.load(io.BytesIO(rest)) if rest else None
    # Rebuild BM25 from plain text — data-only, no code execution possible
    bm25 = BM25Okapi([_tokenize(c.text) for c in chunks])
    return bm25, chunks, emb_matrix, emb_indices


# ---------------------------------------------------------------------------
# L1: in-process LRU cache — document_id → (BM25Okapi, chunks, emb_matrix, emb_indices)
# ---------------------------------------------------------------------------

_retrieval_cache: LRUCache = LRUCache(maxsize=50)

# ---------------------------------------------------------------------------
# L2: Redis cache — serialized with JSON + numpy (TTL=1h)
# ---------------------------------------------------------------------------

_REDIS_TTL = 3600
_redis_client = None


def _get_redis_client():
    global _redis_client
    from app.core.config import settings
    if _redis_client is None and settings.redis_url:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    return _redis_client


async def _redis_cache_get(key: str) -> tuple | None:
    client = _get_redis_client()
    if client is None:
        return None
    try:
        data = await client.get(key)
        if data is None:
            return None
        return _deserialize_from_redis(data)
    except Exception:
        logger.exception("redis_cache_get_error")
        return None


async def _redis_cache_set(
    key: str,
    chunks: list[CachedChunk],
    emb_matrix,
    emb_indices: list,
) -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        data = _serialize_for_redis(chunks, emb_matrix, emb_indices)
        await client.setex(key, _REDIS_TTL, data)
    except Exception:
        logger.exception("redis_cache_set_error")


async def _redis_cache_delete(key: str) -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cache invalidation — evicts both L1 and L2 (+ semantic cache)
# ---------------------------------------------------------------------------

def invalidate_bm25(document_id: str) -> None:
    """Evict a document's entry from L1 LRU, Redis L2, and the semantic cache."""
    _retrieval_cache.pop(document_id, None)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_redis_cache_delete(f"retrieval:{document_id}"))
        # Also clear semantic cache so stale answers aren't served after re-ingestion
        from app.services.semantic_cache import invalidate_semantic_cache
        loop.create_task(invalidate_semantic_cache(document_id))
    except RuntimeError:
        pass  # No running event loop (e.g. tests)


# ---------------------------------------------------------------------------
# Cache builder — converts ORM Chunk objects to CachedChunk (JSON-serializable)
# ---------------------------------------------------------------------------

def _build_cache_entry(orm_chunks: list) -> tuple:
    cached_chunks = [
        CachedChunk(
            id=c.id,
            text=c.text,
            page_number=c.page_number,
            section_heading=c.section_heading,
        )
        for c in orm_chunks
    ]

    tokenized = [_tokenize(c.text) for c in cached_chunks]
    bm25 = BM25Okapi(tokenized)

    embedded_pairs = [(i, c) for i, c in enumerate(orm_chunks) if c.embedding]
    if embedded_pairs:
        emb_matrix = np.stack([_load_embedding_blob(c.embedding) for _, c in embedded_pairs])
        emb_indices = [i for i, _ in embedded_pairs]
    else:
        emb_matrix, emb_indices = None, []

    return bm25, cached_chunks, emb_matrix, emb_indices


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

    Cache hierarchy:
      L1 — in-process LRU (fastest; per-instance)
      L2 — Redis (shared across instances; TTL=1h; serialized as JSON+numpy — no pickle)
      L3 — PostgreSQL/SQLite (source of truth; slowest)
    """
    redis_key = f"retrieval:{document_id}"

    if document_id not in _retrieval_cache:
        # L2: check Redis
        redis_entry = await _redis_cache_get(redis_key)
        if redis_entry is not None:
            _retrieval_cache[document_id] = redis_entry
        else:
            # L3: rebuild from DB
            result = await db.execute(
                select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
            )
            orm_chunks = result.scalars().all()
            if not orm_chunks:
                return []
            entry = _build_cache_entry(orm_chunks)
            _retrieval_cache[document_id] = entry
            _, cached_chunks, emb_matrix, emb_indices = entry
            asyncio.get_running_loop().create_task(
                _redis_cache_set(redis_key, cached_chunks, emb_matrix, emb_indices)
            )

    bm25, cached_chunks, emb_matrix, emb_indices = _retrieval_cache[document_id]
    if not cached_chunks:
        return []

    # BM25 (always available)
    bm25_ranks: list[int] = list(np.argsort(bm25.get_scores(_tokenize(query)))[::-1])
    rank_lists = [bm25_ranks]

    # Semantic (requires embedder + pre-built matrix)
    embedder = _get_embedder()
    if embedder is not None and emb_matrix is not None:
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
