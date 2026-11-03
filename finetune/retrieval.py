"""Retrieve context for a question the way the app does, over an in-memory index.

Mirrors `retriever_node`: cosine search filtered by source id, drop hits under `retrieval_min_score`, remove repeated
text, then the app's own `_rerank`. The prompt is built with the synthesizer's `_SYSTEM` and `_format_chunks`, so a
training prompt is byte-for-byte what serving would send for the same chunks.
"""
from __future__ import annotations

from typing import Callable

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchAny, PointStruct, VectorParams

from app.agent.nodes.retriever import MAX_RERANKED_CHUNKS, N_RESULTS_PER_SOURCE, _rerank
from app.agent.nodes.synthesizer import _SYSTEM, _format_chunks
from app.core.config import settings

COLLECTION = "finetune_chunks"


class CorpusIndex:
    def __init__(self, points: list[PointStruct], embed_query: Callable[[str], list[float]], dim: int = 384):
        self._embed = embed_query
        self._client = QdrantClient(":memory:")
        self._client.create_collection(COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        for start in range(0, len(points), 256):
            self._client.upsert(COLLECTION, points=points[start:start + 256])
        self._by_id = {str(p.id): p for p in points}

    def retrieve(self, query: str, source_ids: list[str]) -> list[dict]:
        types = {self._by_id[i].payload["source_type"] for i in self._by_id if self._by_id[i].payload["source_id"] in source_ids}
        limit = max(N_RESULTS_PER_SOURCE * max(len(types), 1), MAX_RERANKED_CHUNKS)
        vector = [float(x) for x in self._embed(query)]
        hits = self._client.query_points(
            COLLECTION, query=vector, limit=limit, with_payload=True,
            query_filter=Filter(must=[FieldCondition(key="source_id", match=MatchAny(any=source_ids))]),
        ).points
        chunks, seen = [], set()
        for hit in hits:
            if hit.score < settings.retrieval_min_score:
                continue
            payload = dict(hit.payload)
            text = payload.pop("text", "")
            if text in seen:
                continue
            seen.add(text)
            chunks.append({"id": str(hit.id), "text": text, "metadata": payload,
                           "source_type": payload.get("source_type") or "unknown", "score": hit.score})
        return _rerank(query, chunks)

    def chunk_ids_in_order(self, source_id: str) -> list[str]:
        rows = [p for p in self._by_id.values() if p.payload["source_id"] == source_id]
        return [str(p.id) for p in sorted(rows, key=lambda p: p.payload["chunk_index"])]

    def text(self, chunk_id: str) -> str:
        return self._by_id[chunk_id].payload["text"]


def build_messages(question: str, chunks: list[dict], history: str = "none") -> list[dict]:
    system = _SYSTEM.format(context=_format_chunks(chunks), conversation_history=history)
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]
