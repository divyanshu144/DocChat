"""
Embedding service using fastembed (BAAI/bge-small-en-v1.5, 384-dim).

Provides a unified interface used by all three ingestion services and the
retriever node. Returns None gracefully if fastembed is unavailable so the
rest of the app can still start in degraded mode.
"""

from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None  # type: ignore[assignment,misc]

_embedder_instance: "_Embedder | None" = None


def get_embedder() -> "_Embedder | None":
    """Lazy-init singleton. Returns None if fastembed fails to load."""
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance
    try:
        from app.core.config import settings
        _embedder_instance = _Embedder(settings.embedding_model)
    except Exception:
        logger.exception("embedder_init_failed — running without embeddings")
    return _embedder_instance


class _Embedder:
    """Thin fastembed wrapper with a stable public API."""

    def __init__(self, model_name: str) -> None:
        if TextEmbedding is None:
            raise ImportError("fastembed is not installed")
        self._fe = TextEmbedding(model_name=model_name)
        list(self._fe.embed(["warmup"]))

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single string. Returns float32 ndarray shape (dim,)."""
        return next(self._fe.embed([text])).astype(np.float32)

    def embed_independently(self, texts: list[str]) -> list[np.ndarray]:
        """Embed each text independently."""
        return [e.astype(np.float32) for e in self._fe.embed(texts)]

    def embed_late(
        self,
        segment_text: str,
        chunk_texts: list[str],
        chunk_char_starts: list[int],
    ) -> list[np.ndarray]:
        """Embed chunks. Degrades to independent embedding in v1."""
        return self.embed_independently(chunk_texts)
