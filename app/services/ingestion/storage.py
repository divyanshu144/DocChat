"""Shared synchronous indexing helpers; async callers run these in a worker."""
import uuid
from threading import RLock

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from app.core.config import settings

_source_locks = [RLock() for _ in range(64)]


def _source_lock(source_id: str):
    # Fixed-size lock stripes bound memory while serializing same-source writes.
    return _source_locks[uuid.uuid5(uuid.NAMESPACE_URL, source_id).int % len(_source_locks)]


def source_filter(source_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])


def delete_source_points(client, collection: str, source_id: str) -> None:
    with _source_lock(source_id):
        client.delete(collection_name=collection, points_selector=source_filter(source_id), wait=True)


def replace_source_points(client, collection: str, source_id: str, points: list[PointStruct]) -> None:
    # Prepare all embeddings first so embedding failures leave the old index intact.
    # Qdrant does not offer a transaction spanning this delete and the batched upserts.
    with _source_lock(source_id):
        delete_source_points(client, collection, source_id)
        for start in range(0, len(points), settings.ingest_batch_size):
            client.upsert(
                collection_name=collection,
                points=points[start:start + settings.ingest_batch_size],
                wait=True,
            )


def embed_chunks(embedder, texts: list[str]) -> list:
    embeddings = []
    for start in range(0, len(texts), settings.ingest_batch_size):
        batch = texts[start:start + settings.ingest_batch_size]
        vectors = embedder.embed_independently(batch)
        if len(vectors) != len(batch):
            raise ValueError("Embedding count does not match chunk count")
        embeddings.extend(vectors)
    return embeddings


def build_points(source_id: str, chunks: list[dict], embedder, metadata: dict) -> list[PointStruct]:
    if embedder is None:
        raise RuntimeError("Embedding service unavailable; source was not indexed")
    chunks = [chunk for chunk in chunks if chunk["text"].strip()]
    if not chunks:
        raise ValueError("Source contains no readable chunks")
    embeddings = embed_chunks(embedder, [chunk["text"] for chunk in chunks])
    return [
        PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{source_id}_{index}")),
            vector=embedding.tolist(),
            payload={**metadata, **chunk, "source_id": source_id, "chunk_index": index},
        )
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
    ]
