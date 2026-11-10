from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from qdrant_client.models import Distance, Modifier, PointStruct, SparseVector, VectorParams

from app.services.embedder import SparseVec, _Embedder
from app.services.ingestion import storage


def dense(value=0.1):
    return np.array([value] * 4, dtype="float32")


def embedder_with(sparse):
    e = MagicMock()
    e.embed_independently.side_effect = lambda texts: [dense() for _ in texts]
    e.embed_sparse_documents.return_value = sparse
    return e


# ---- point construction ----------------------------------------------------------------------------------

def test_point_vector_is_a_plain_list_without_sparse():
    assert storage.point_vector(dense(0.5)) == pytest.approx([0.5] * 4)


def test_point_vector_names_the_sparse_vector_next_to_the_unnamed_dense_one():
    vector = storage.point_vector(dense(0.5), SparseVec([3, 8], [1.5, 2.5]))
    assert vector[""] == pytest.approx([0.5] * 4)
    assert vector["bm25"] == SparseVector(indices=[3, 8], values=[1.5, 2.5])


def test_build_points_attaches_a_sparse_vector_per_chunk():
    points = storage.build_points(
        "src", [{"text": "alpha beta"}, {"text": "gamma"}],
        embedder_with([SparseVec([1], [1.0]), SparseVec([2], [3.0])]), {"source_type": "web"},
    )
    assert [p.vector["bm25"].indices for p in points] == [[1], [2]]
    assert all(p.vector[""] == pytest.approx([0.1] * 4) for p in points)


def test_build_points_degrades_to_dense_only_when_sparse_model_is_unavailable():
    points = storage.build_points("src", [{"text": "alpha"}], embedder_with(None), {"source_type": "web"})
    assert isinstance(points[0].vector, list)


def test_sparse_count_mismatch_fails_loudly_rather_than_misaligning_vectors():
    with pytest.raises(ValueError, match="Sparse embedding count"):
        storage.build_points("src", [{"text": "a"}, {"text": "b"}], embedder_with([SparseVec([1], [1.0])]), {})


# ---- writing to old and new collections ----------------------------------------------------------------

def hybrid_point():
    return PointStruct(id="11111111-1111-5111-8111-111111111111", payload={"text": "t"},
                       vector=storage.point_vector(dense(), SparseVec([1], [1.0])))


def test_hybrid_points_are_written_unchanged_to_a_collection_with_the_sparse_field():
    client = MagicMock()
    with patch.object(storage, "collection_has_sparse", return_value=True):
        storage.replace_source_points(client, "c", "src", [hybrid_point()])
    written = client.upsert.call_args.kwargs["points"][0]
    assert isinstance(written.vector, dict) and "bm25" in written.vector


def test_sparse_vectors_are_stripped_for_a_collection_that_predates_the_field():
    client = MagicMock()
    with patch.object(storage, "collection_has_sparse", return_value=False):
        storage.replace_source_points(client, "legacy", "src", [hybrid_point()])
    written = client.upsert.call_args.kwargs["points"][0]
    assert written.vector == pytest.approx([0.1] * 4) and written.payload == {"text": "t"}


def test_dense_only_points_do_not_trigger_a_collection_lookup():
    client = MagicMock()
    with patch.object(storage, "collection_has_sparse") as lookup:
        storage.replace_source_points(client, "c", "src",
                                      [PointStruct(id="11111111-1111-5111-8111-111111111111", vector=[0.1], payload={})])
    lookup.assert_not_called()


# ---- collection creation --------------------------------------------------------------------------------

def test_new_source_collection_is_created_with_a_bm25_idf_sparse_field():
    client = MagicMock()
    client.get_collection.side_effect = Exception("not found")
    with patch("app.core.qdrant.get_qdrant_client", return_value=client):
        from app.core.qdrant import get_qdrant_collection
        get_qdrant_collection("source_chunks", sparse=True)
    kwargs = client.create_collection.call_args.kwargs
    assert kwargs["vectors_config"] == VectorParams(size=384, distance=Distance.COSINE)
    assert kwargs["sparse_vectors_config"]["bm25"].modifier == Modifier.IDF


def test_collection_has_sparse_reads_the_collection_config():
    client = MagicMock()
    client.get_collection.return_value.config.params.sparse_vectors = {"bm25": object()}
    with patch("app.core.qdrant.get_qdrant_client", return_value=client):
        from app.core.qdrant import collection_has_sparse
        assert collection_has_sparse("c") is True
    client.get_collection.return_value.config.params.sparse_vectors = None
    with patch("app.core.qdrant.get_qdrant_client", return_value=client):
        assert collection_has_sparse("c") is False


# ---- embedder -------------------------------------------------------------------------------------------

def make_embedder():
    with patch("app.services.embedder.TextEmbedding", return_value=MagicMock(embed=MagicMock(return_value=iter([])))):
        return _Embedder("dense-model")


def fake_sparse_embedding(indices, values):
    return MagicMock(indices=np.array(indices), values=np.array(values, dtype="float32"))


def test_sparse_documents_and_queries_use_the_configured_model_lazily():
    embedder = make_embedder()
    model = MagicMock()
    model.embed.return_value = iter([fake_sparse_embedding([1, 2], [0.5, 1.5])])
    model.query_embed.return_value = iter([fake_sparse_embedding([2], [1])])
    with patch("app.services.embedder.SparseTextEmbedding", return_value=model) as factory:
        assert embedder.embed_sparse_documents(["doc"]) == [SparseVec([1, 2], [0.5, 1.5])]
        assert embedder.embed_sparse_query("q") == SparseVec([2], [1.0])
        assert embedder.has_sparse is True
    factory.assert_called_once_with(model_name="Qdrant/bm25")  # loaded once, on first use


def test_sparse_model_failure_disables_sparse_only_and_is_not_retried_every_call():
    embedder = make_embedder()
    with patch("app.services.embedder.SparseTextEmbedding", side_effect=RuntimeError("download failed")) as factory:
        assert embedder.embed_sparse_documents(["doc"]) is None
        assert embedder.embed_sparse_query("q") is None
        assert embedder.has_sparse is False
    assert factory.call_count == 1
    assert embedder.embed_query is not None  # dense path untouched
