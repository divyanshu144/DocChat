"""Redis-backed semantic cache for RAG answers.

Stores (query_embedding, answer) pairs per document.  On a new query, finds
the cached entry with the highest cosine similarity; if it exceeds the
configured threshold the cached answer is returned immediately, skipping
retrieval and LLM entirely.

Only active when both REDIS_URL and SEMANTIC_CACHE_ENABLED=true are set.
"""

import json
import logging
import uuid

import numpy as np

logger = logging.getLogger(__name__)

_MAX_ENTRIES_PER_DOC = 200   # FIFO eviction beyond this limit
_CACHE_TTL = 86400           # 24-hour TTL — prevents unbounded Redis growth and stale answers


class SemanticCache:
    def __init__(self, redis_url: str, threshold: float = 0.95) -> None:
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(redis_url, decode_responses=False)
        self._threshold = threshold

    @staticmethod
    def _key(document_id: str) -> str:
        return f"semantic_cache:{document_id}"

    async def get(self, query_emb: np.ndarray, document_id: str) -> str | None:
        """Return a cached answer if one exists within cosine threshold, else None."""
        raw = await self._client.hgetall(self._key(document_id))
        if not raw:
            return None

        best_score, best_answer = -1.0, None
        q = query_emb / (np.linalg.norm(query_emb) + 1e-10)

        for value_bytes in raw.values():
            try:
                entry = json.loads(value_bytes)
                cached_emb = np.array(entry["embedding"], dtype=np.float32)
                cached_emb /= np.linalg.norm(cached_emb) + 1e-10
                score = float(np.dot(q, cached_emb))
                if score > best_score:
                    best_score, best_answer = score, entry["answer"]
            except Exception:
                continue

        if best_score >= self._threshold and best_answer is not None:
            logger.info("semantic_cache_hit", extra={"score": round(best_score, 3)})
            return best_answer
        return None

    async def set(self, query_emb: np.ndarray, answer: str, document_id: str) -> None:
        """Store a (query_embedding, answer) pair for future cache lookups."""
        entry = json.dumps({"embedding": query_emb.tolist(), "answer": answer})
        key = self._key(document_id)
        await self._client.hset(key, str(uuid.uuid4()), entry)
        await self._client.expire(key, _CACHE_TTL)

        # Evict oldest entry when the hash grows beyond the cap
        length = await self._client.hlen(key)
        if length > _MAX_ENTRIES_PER_DOC:
            fields = await self._client.hkeys(key)
            if fields:
                await self._client.hdel(key, fields[0])

    async def invalidate(self, document_id: str) -> None:
        """Delete all cached answers for a document (call after re-ingestion)."""
        await self._client.delete(self._key(document_id))

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Module-level singleton — instantiated lazily on first use
# ---------------------------------------------------------------------------

_cache: SemanticCache | None = None


async def invalidate_semantic_cache(document_id: str) -> None:
    """Module-level helper — evicts cached answers for a document from Redis."""
    cache = get_semantic_cache()
    if cache is not None:
        await cache.invalidate(document_id)


def get_semantic_cache() -> SemanticCache | None:
    global _cache
    from app.core.config import settings
    if (
        _cache is None
        and settings.semantic_cache_enabled
        and settings.redis_url
    ):
        _cache = SemanticCache(settings.redis_url, settings.semantic_cache_threshold)
    return _cache
