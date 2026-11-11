import json
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from app.agent.nodes import retriever
from app.agent.nodes.retriever import fuse_hybrid, retriever_node
from app.services.embedder import SparseVec


def hit(point_id, text, score, **payload):
    return {"id": point_id, "score": score,
            "payload": {"text": text, "source_type": "pdf", "filename": "doc.pdf", **payload}}


def fuse(dense, sparse, **overrides):
    args = dict(min_score=0.3, bm25_min_score=0.0, rrf_k=60, limit=12)
    return fuse_hybrid(dense, sparse, **{**args, **overrides})


# ---- fusion policy -------------------------------------------------------------------------------------------

def test_chunk_found_by_both_rankings_leads():
    dense = [hit("a", "alpha", 0.9), hit("b", "beta", 0.8)]
    sparse = [hit("b", "beta", 7.0), hit("c", "gamma", 3.0)]
    assert [c["text"] for c in fuse(dense, sparse)] == ["beta", "alpha", "gamma"]


def test_exact_term_match_below_the_dense_floor_is_kept():
    dense = [hit("a", "general text", 0.6)]
    sparse = [hit("code", "error E1234 on boot", 9.0)]  # embedding score for it was below the floor: not in dense
    assert "error E1234 on boot" in [c["text"] for c in fuse(dense, sparse)]


def test_bm25_min_score_rejects_weak_lexical_only_matches_but_not_dense_backed_ones():
    dense = [hit("a", "backed by dense", 0.6)]
    sparse = [hit("a", "backed by dense", 0.2), hit("noise", "common word only", 0.4)]
    texts = [c["text"] for c in fuse(dense, sparse, bm25_min_score=1.0)]
    assert texts == ["backed by dense"]


def test_dense_hits_below_the_cosine_floor_are_dropped():
    assert fuse([hit("a", "weak", 0.29)], []) == []
    assert [c["text"] for c in fuse([hit("a", "edge", 0.3)], [])] == ["edge"]


def test_nonpositive_bm25_scores_are_ignored():
    assert fuse([], [hit("a", "zero", 0.0)]) == []


def test_identical_text_from_two_points_appears_once_at_its_best_rank():
    dense = [hit("a", "same text", 0.9), hit("b", "same text", 0.8), hit("c", "other", 0.7)]
    assert [c["text"] for c in fuse(dense, [])] == ["same text", "other"]


def test_result_is_cut_to_limit_and_carries_rrf_score_and_metadata():
    dense = [hit(str(i), f"chunk {i}", 0.9 - i * 0.01, page_number=i) for i in range(20)]
    chunks = fuse(dense, [], limit=5)
    assert len(chunks) == 5
    assert chunks[0]["score"] == pytest.approx(1 / 61)
    assert chunks[0]["metadata"]["filename"] == "doc.pdf" and "text" not in chunks[0]["metadata"]
    assert chunks[0]["source_type"] == "pdf"


# ---- node: hybrid path, fallbacks --------------------------------------------------------------------------

def state(**kw):
    base = {"query": "error E1234", "conversation_id": "c", "conversation_history": [], "sources_to_use": ["pdf"],
            "source_ids": [], "retrieved_chunks": []}
    return {**base, **kw}


def embedder(sparse="ok"):
    e = MagicMock()
    e.embed_query.return_value = np.array([0.1, 0.2], dtype="float32")
    e.embed_sparse_query.return_value = SparseVec([5, 9], [1.0, 1.0]) if sparse == "ok" else sparse
    return e


@pytest.fixture(autouse=True)
def _reset_state():
    retriever._hybrid_unsupported_since.clear()
    yield
    retriever._hybrid_unsupported_since.clear()


def run_with_transport(handler, emb, **settings_overrides):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    patches = [patch.object(retriever, "_get_http_client", return_value=client),
               patch("app.agent.nodes.retriever.get_embedder", return_value=emb)]
    patches += [patch.object(retriever.settings, k, v) for k, v in settings_overrides.items()]
    return client, patches


async def call(handler, emb, st=None, **settings_overrides):
    client, patches = run_with_transport(handler, emb, **{"retrieval_mode": "hybrid", **settings_overrides})
    for p in patches:
        p.start()
    try:
        return await retriever_node(st or state())
    finally:
        for p in reversed(patches):
            p.stop()
        await client.aclose()


@pytest.mark.asyncio
async def test_hybrid_uses_one_batch_request_with_dense_and_bm25_queries_and_the_filter():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"result": [
            {"points": [hit("a", "dense chunk", 0.8)]},
            {"points": [hit("code", "error E1234 on boot", 6.0), hit("a", "dense chunk", 2.0)]},
        ]})

    out = await call(handler, embedder(), st=state(source_ids=["s1"]))

    assert len(seen) == 1 and seen[0][0].endswith("/points/query/batch")
    dense_q, sparse_q = seen[0][1]["searches"]
    assert dense_q["query"] == pytest.approx([0.1, 0.2]) and "using" not in dense_q
    assert sparse_q["using"] == "bm25" and sparse_q["query"] == {"indices": [5, 9], "values": [1.0, 1.0]}
    for q in (dense_q, sparse_q):
        assert q["limit"] == retriever.settings.retrieval_candidates and q["with_payload"] is True
        assert q["filter"]["must"][0]["key"] == "source_id"
    assert [c["text"] for c in out["retrieved_chunks"]] == ["dense chunk", "error E1234 on boot"]


@pytest.mark.asyncio
async def test_collection_without_sparse_field_falls_back_to_dense_and_is_not_reprobed():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/points/query/batch"):
            return httpx.Response(400, json={"status": {"error": "Wrong input: Not existing vector name error: bm25"}})
        return httpx.Response(200, json={"result": [hit("a", "error E1234 explained", 0.8)]})

    first = await call(handler, embedder())
    second = await call(handler, embedder())

    assert [c["text"] for c in first["retrieved_chunks"]] == ["error E1234 explained"]
    assert [c["text"] for c in second["retrieved_chunks"]] == ["error E1234 explained"]
    assert [p.rsplit("/points/", 1)[1] for p in paths] == ["query/batch", "search", "search"]  # probed once


@pytest.mark.asyncio
async def test_unsupported_collection_is_rechecked_after_the_ttl():
    retriever._hybrid_unsupported_since["source_chunks"] = 0.0  # monotonic origin: long expired
    assert retriever._hybrid_known_unsupported("source_chunks") is False
    assert "source_chunks" not in retriever._hybrid_unsupported_since


@pytest.mark.asyncio
async def test_dense_mode_never_touches_the_sparse_path():
    paths = []
    emb = embedder()

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"result": [hit("a", "error E1234 explained", 0.8)]})

    out = await call(handler, emb, retrieval_mode="dense")

    assert [p.rsplit("/points/", 1)[1] for p in paths] == ["search"]
    emb.embed_sparse_query.assert_not_called()
    assert len(out["retrieved_chunks"]) == 1


@pytest.mark.parametrize("sparse", [None, SparseVec([], []), "not-a-vector"])
@pytest.mark.asyncio
async def test_missing_or_empty_sparse_query_uses_dense(sparse):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"result": [hit("a", "some text", 0.8)]})

    out = await call(handler, embedder(sparse))

    assert [p.rsplit("/points/", 1)[1] for p in paths] == ["search"]
    assert len(out["retrieved_chunks"]) == 1


@pytest.mark.asyncio
async def test_server_error_returns_no_chunks_without_masking_it_as_unsupported():
    def handler(request):
        return httpx.Response(503, text="overloaded")

    out = await call(handler, embedder())

    assert out == {"retrieved_chunks": []}
    assert retriever._hybrid_unsupported_since == {}  # an outage must not disable hybrid for the TTL


@pytest.mark.asyncio
async def test_hybrid_still_applies_the_cosine_floor_to_dense_candidates():
    def handler(request):
        return httpx.Response(200, json={"result": [{"points": [hit("a", "unrelated", 0.1)]}, {"points": []}]})

    out = await call(handler, embedder())

    assert out["retrieved_chunks"] == []


def test_hybrid_is_opt_in_by_default():
    from app.core.config import Settings
    assert Settings.model_fields["retrieval_mode"].default == "dense"


@pytest.mark.asyncio
async def test_default_mode_never_loads_or_queries_the_sparse_model():
    emb = embedder()
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"result": [hit("a", "some text", 0.8)]})

    out = await call(handler, emb, retrieval_mode="dense")
    assert [p.rsplit("/points/", 1)[1] for p in paths] == ["search"] and len(out["retrieved_chunks"]) == 1
    emb.embed_sparse_query.assert_not_called()
