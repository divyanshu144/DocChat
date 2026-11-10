from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from qdrant_client.models import Distance, Modifier, SparseVector, SparseVectorParams, VectorParams

from app.services import hybrid_migration
from app.services.embedder import SparseVec


class FakeQdrant:
    """The slice of QdrantClient the migration uses, over dicts."""

    def __init__(self):
        self.collections: dict[str, dict] = {}
        self.points: dict[str, dict] = {}

    def add_collection(self, name, vectors, sparse=None):
        self.collections[name] = SimpleNamespace(config=SimpleNamespace(
            params=SimpleNamespace(vectors=vectors, sparse_vectors=sparse)))
        self.points.setdefault(name, {})

    def collection_exists(self, name):
        return name in self.collections

    def get_collection(self, name):
        return self.collections[name]

    def create_collection(self, collection_name, vectors_config, sparse_vectors_config=None):
        self.add_collection(collection_name, vectors_config, sparse_vectors_config)

    def upsert(self, collection_name, points, wait=True):
        for p in points:
            self.points[collection_name][p.id] = p

    def scroll(self, collection, limit, offset, with_payload, with_vectors):
        ids = sorted(self.points[collection], key=str)
        start = ids.index(offset) if offset is not None else 0
        page = ids[start:start + limit]
        nxt = ids[start + limit] if start + limit < len(ids) else None
        rows = [SimpleNamespace(id=i, payload=self.points[collection][i].payload if with_payload else None,
                                vector=self.points[collection][i].vector if with_vectors else None) for i in page]
        return rows, nxt


def seeded(n=5, *, empty_text_at=None):
    client = FakeQdrant()
    client.add_collection("src", VectorParams(size=3, distance=Distance.COSINE))
    for i in range(n):
        text = "" if i == empty_text_at else f"chunk number {i}"
        client.points["src"][f"id-{i}"] = SimpleNamespace(
            id=f"id-{i}", payload={"text": text, "source_id": "s"}, vector=[float(i), 1.0, 0.0])
    return client


def embedder(has_sparse=True):
    e = MagicMock()
    e.has_sparse = has_sparse
    e.embed_sparse_documents.side_effect = lambda texts: [SparseVec([len(t)], [1.0]) for t in texts]
    return e


def test_copies_dense_vectors_and_payloads_and_adds_bm25_vectors():
    client = seeded(5)
    report = hybrid_migration.migrate(client, embedder(), "src", "dst", batch_size=2)

    assert (report.source_points, report.copied, report.created_target, report.consistent) == (5, 5, True, True)
    created = client.collections["dst"].config.params
    assert created.vectors == VectorParams(size=3, distance=Distance.COSINE)
    assert created.sparse_vectors["bm25"] == SparseVectorParams(modifier=Modifier.IDF)
    copied = client.points["dst"]["id-3"]
    assert copied.vector[""] == [3.0, 1.0, 0.0]
    assert copied.vector["bm25"] == SparseVector(indices=[len("chunk number 3")], values=[1.0])
    assert copied.payload == {"text": "chunk number 3", "source_id": "s"}


def test_rerun_is_idempotent_and_picks_up_newly_ingested_points():
    client = seeded(3)
    hybrid_migration.migrate(client, embedder(), "src", "dst")
    client.points["src"]["id-new"] = SimpleNamespace(id="id-new", payload={"text": "later"}, vector=[9.0, 9.0, 9.0])

    report = hybrid_migration.migrate(client, embedder(), "src", "dst")

    assert report.created_target is False and report.consistent and len(client.points["dst"]) == 4


def test_dry_run_writes_nothing_and_does_not_create_the_target():
    client = seeded(3)
    report = hybrid_migration.migrate(client, embedder(), "src", "dst", dry_run=True)
    assert report.copied == 3 and "dst" not in client.collections


def test_points_without_text_are_copied_dense_only():
    client = seeded(3, empty_text_at=1)
    report = hybrid_migration.migrate(client, embedder(), "src", "dst")
    assert report.without_text == 1 and report.consistent
    assert isinstance(client.points["dst"]["id-1"].vector, list)
    assert isinstance(client.points["dst"]["id-0"].vector, dict)


def test_points_deleted_from_source_since_a_prior_run_are_reported_not_silently_kept():
    client = seeded(3)
    hybrid_migration.migrate(client, embedder(), "src", "dst")
    del client.points["src"]["id-1"]
    report = hybrid_migration.migrate(client, embedder(), "src", "dst")
    assert report.extra_in_target == ["id-1"] and not report.consistent


def test_refuses_when_the_bm25_model_is_unavailable_before_creating_anything():
    client = seeded(2)
    with pytest.raises(RuntimeError, match="BM25 model"):
        hybrid_migration.migrate(client, embedder(has_sparse=False), "src", "dst")
    assert "dst" not in client.collections


def test_refuses_an_existing_target_that_has_no_bm25_field():
    client = seeded(2)
    client.add_collection("dst", VectorParams(size=3, distance=Distance.COSINE))
    with pytest.raises(RuntimeError, match="without a 'bm25' field"):
        hybrid_migration.migrate(client, embedder(), "src", "dst")


def test_refuses_to_copy_a_point_that_has_no_dense_vector():
    client = seeded(2)
    client.points["src"]["id-0"].vector = None
    with pytest.raises(RuntimeError, match="no dense vector"):
        hybrid_migration.migrate(client, embedder(), "src", "dst")


def test_source_and_target_must_differ():
    with pytest.raises(ValueError):
        hybrid_migration.migrate(seeded(1), embedder(), "src", "src")
