"""Shared synchronous indexing helpers; async callers run these in a worker."""
import logging
import uuid
from threading import RLock

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct, SparseVector

from app.core.config import settings
from app.core.qdrant import SPARSE_VECTOR_NAME, collection_has_sparse

logger = logging.getLogger(__name__)

_source_locks = [RLock() for _ in range(64)]


def _source_lock(source_id: str):
    # Fixed-size lock stripes bound memory while serializing same-source writes.
    return _source_locks[uuid.uuid5(uuid.NAMESPACE_URL, source_id).int % len(_source_locks)]


def source_filter(source_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])


def delete_source_points(client, collection: str, source_id: str) -> None:
    with _source_lock(source_id):
        client.delete(collection_name=collection, points_selector=source_filter(source_id), wait=True)


def point_vector(dense, sparse=None):
    """Vector payload for one point: the plain dense list, or dense plus the named BM25 vector."""
    dense = dense.tolist() if hasattr(dense, "tolist") else list(dense)
    if sparse is None:
        return dense
    return {"": dense, SPARSE_VECTOR_NAME: SparseVector(indices=list(sparse.indices), values=list(sparse.values))}


def embed_sparse(embedder, texts: list[str]) -> list:
    """BM25 vectors for chunk texts, or Nones when the sparse model is unavailable (dense-only indexing)."""
    vectors = embedder.embed_sparse_documents(texts) if hasattr(embedder, "embed_sparse_documents") else None
    if vectors is None:
        logger.warning("sparse embedder unavailable; indexing %d chunks dense-only", len(texts))
        return [None] * len(texts)
    if len(vectors) != len(texts):
        raise ValueError("Sparse embedding count does not match chunk count")
    return vectors


def _fit_to_collection(collection: str, points: list[PointStruct]) -> list[PointStruct]:
    """Drop sparse vectors when the collection predates the sparse field, so ingestion keeps working there."""
    if not any(isinstance(p.vector, dict) for p in points) or collection_has_sparse(collection):
        return points
    logger.warning("collection %s has no %s field; indexing dense-only. Run "
                   "scripts/migrate_to_hybrid_collection.py to enable hybrid retrieval.", collection, SPARSE_VECTOR_NAME)
    return [PointStruct(id=p.id, payload=p.payload, vector=p.vector[""] if isinstance(p.vector, dict) else p.vector)
            for p in points]


def replace_source_points(client, collection: str, source_id: str, points: list[PointStruct]) -> None:
    # Prepare all embeddings first so embedding failures leave the old index intact.
    # Qdrant does not offer a transaction spanning this delete and the batched upserts.
    points = _fit_to_collection(collection, points)
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
    texts = [chunk["text"] for chunk in chunks]
    embeddings = embed_chunks(embedder, texts)
    sparse = embed_sparse(embedder, texts)
    return [
        PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{source_id}_{index}")),
            vector=point_vector(embedding, sparse_vec),
            payload={**metadata, **chunk, "source_id": source_id, "chunk_index": index},
        )
        for index, (chunk, embedding, sparse_vec) in enumerate(zip(chunks, embeddings, sparse, strict=True))
    ]
