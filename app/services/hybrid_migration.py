"""Copy a dense-only collection into a hybrid (dense + BM25) one. Synchronous; run it from a script.

Qdrant cannot add a sparse vector field to an existing collection, so enabling hybrid retrieval means writing
the points into a new collection. Dense vectors and payloads are copied as stored (no re-embedding); only the
BM25 vectors are computed, from each point's ``text`` payload. Point ids are deterministic, so the copy is
idempotent: re-running it after more sources were ingested into the source collection adds what is missing.
The source collection is never modified.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from qdrant_client.models import Modifier, PointStruct, SparseVectorParams, VectorParams

from app.core.qdrant import SPARSE_VECTOR_NAME
from app.services.ingestion.storage import point_vector

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    source_points: int = 0
    copied: int = 0
    without_text: int = 0
    missing_in_target: list = field(default_factory=list)
    extra_in_target: list = field(default_factory=list)
    created_target: bool = False

    @property
    def consistent(self) -> bool:
        return not self.missing_in_target and not self.extra_in_target


def _scroll(client, collection: str, *, with_payload: bool, with_vectors: bool, batch_size: int):
    offset = None
    while True:
        points, offset = client.scroll(collection, limit=batch_size, offset=offset,
                                       with_payload=with_payload, with_vectors=with_vectors)
        yield from points
        if offset is None:
            return


def _dense_of(point) -> list[float] | None:
    vector = point.vector
    if isinstance(vector, dict):  # already a named-vector point: the unnamed dense vector sits under ""
        vector = vector.get("")
    return list(vector) if vector else None


def ensure_target(client, source: str, target: str) -> bool:
    """Create the hybrid target with the source's dense settings. True if it was created here."""
    if client.collection_exists(target):
        sparse = client.get_collection(target).config.params.sparse_vectors or {}
        if SPARSE_VECTOR_NAME not in sparse:
            raise RuntimeError(f"Target collection {target!r} exists without a {SPARSE_VECTOR_NAME!r} field; "
                               "choose another --target or delete it")
        return False
    dense = client.get_collection(source).config.params.vectors
    if not isinstance(dense, VectorParams):
        raise RuntimeError(f"Source collection {source!r} does not use a single unnamed dense vector")
    client.create_collection(
        collection_name=target,
        vectors_config=VectorParams(size=dense.size, distance=dense.distance),
        sparse_vectors_config={SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)},
    )
    return True


def migrate(
    client,
    embedder,
    source: str,
    target: str,
    *,
    batch_size: int = 64,
    dry_run: bool = False,
    progress: Callable[[int], None] | None = None,
) -> MigrationReport:
    if source == target:
        raise ValueError("source and target must differ")
    if not embedder.has_sparse:
        raise RuntimeError("The BM25 model could not be loaded; nothing was written")
    report = MigrationReport()
    if not dry_run:
        report.created_target = ensure_target(client, source, target)

    batch: list = []

    def flush() -> None:
        if not batch:
            return
        texts = [(p.payload or {}).get("text", "") for p in batch]
        indexable = [i for i, text in enumerate(texts) if text.strip()]
        sparse = dict(zip(indexable, embedder.embed_sparse_documents([texts[i] for i in indexable]) or [], strict=False))
        points = []
        for i, point in enumerate(batch):
            dense = _dense_of(point)
            if dense is None:
                raise RuntimeError(f"Point {point.id} has no dense vector; refusing to copy a partial point")
            if i not in sparse:
                report.without_text += 1
            points.append(PointStruct(id=point.id, payload=point.payload, vector=point_vector(dense, sparse.get(i))))
        if not dry_run:
            client.upsert(collection_name=target, points=points, wait=True)
        report.copied += len(points)
        if progress:
            progress(report.copied)
        batch.clear()

    for point in _scroll(client, source, with_payload=True, with_vectors=True, batch_size=batch_size):
        report.source_points += 1
        batch.append(point)
        if len(batch) >= batch_size:
            flush()
    flush()

    if not dry_run:
        source_ids = {p.id for p in _scroll(client, source, with_payload=False, with_vectors=False, batch_size=512)}
        target_ids = {p.id for p in _scroll(client, target, with_payload=False, with_vectors=False, batch_size=512)}
        report.missing_in_target = sorted(source_ids - target_ids, key=str)
        report.extra_in_target = sorted(target_ids - source_ids, key=str)
    return report
