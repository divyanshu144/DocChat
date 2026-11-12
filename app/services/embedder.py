"""
Embedding service using fastembed (BAAI/bge-small-en-v1.5, 384-dim).

Provides a unified interface used by all three ingestion services and the
retriever node. Returns None gracefully if fastembed is unavailable so the
rest of the app can still start in degraded mode.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)

# After a failed BM25 model load, wait this long before trying again (a transient failure must not
# disable hybrid retrieval until the process restarts).
SPARSE_RETRY_S = 300.0

try:
    from fastembed import SparseTextEmbedding, TextEmbedding
except ImportError:
    SparseTextEmbedding = None  # type: ignore[assignment,misc]
    TextEmbedding = None  # type: ignore[assignment,misc]


class SparseVec(NamedTuple):
    """One BM25 vector: hashed token ids and their weights, parallel lists."""

    indices: list[int]
    values: list[float]

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
        self._sparse = None
        self._sparse_failed_at: float | None = None
        self._sparse_lock = threading.Lock()

    def _in_cooldown(self) -> bool:
        return self._sparse_failed_at is not None and time.monotonic() - self._sparse_failed_at < SPARSE_RETRY_S

    def _sparse_model(self):
        """Lazy BM25 model. A load failure disables sparse only, for SPARSE_RETRY_S, then loading is tried again;
        dense embedding keeps working throughout."""
        if self._sparse is not None or self._in_cooldown():
            return self._sparse
        with self._sparse_lock:
            if self._sparse is None and not self._in_cooldown():
                try:
                    from app.core.config import settings
                    if SparseTextEmbedding is None:
                        raise ImportError("fastembed sparse models are not available")
                    self._sparse = SparseTextEmbedding(model_name=settings.sparse_embedding_model)
                    self._sparse_failed_at = None
                except Exception:
                    self._sparse_failed_at = time.monotonic()
                    logger.exception("sparse_embedder_init_failed — hybrid retrieval degraded to dense; "
                                     "retrying after %ss", SPARSE_RETRY_S)
        return self._sparse

    @property
    def has_sparse(self) -> bool:
        return self._sparse_model() is not None

    def embed_sparse_documents(self, texts: list[str]) -> list[SparseVec] | None:
        """BM25 term-frequency vectors for chunks (length-normalised); IDF is applied by Qdrant. None if unavailable."""
        model = self._sparse_model()
        if model is None:
            return None
        return [SparseVec(e.indices.tolist(), e.values.tolist()) for e in model.embed(texts)]

    def embed_sparse_query(self, text: str) -> SparseVec | None:
        """BM25 query vector. None if the sparse model is unavailable."""
        model = self._sparse_model()
        if model is None:
            return None
        e = next(iter(model.query_embed(text)))
        return SparseVec(e.indices.tolist(), [float(v) for v in e.values])

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single string. Returns float32 ndarray shape (dim,)."""
        return next(self._fe.embed([text])).astype(np.float32)

    def embed_independently(self, texts: list[str]) -> list[np.ndarray]:
        """Embed each text independently."""
        return [e.astype(np.float32) for e in self._fe.embed(texts)]
