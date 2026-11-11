import pytest

from eval.retrieval_eval import recall_at_k, reciprocal_rank


@pytest.mark.parametrize("ranked,relevant,k,expected", [
    (["a", "b", "c"], ["a", "c"], 1, 0.5),
    (["a", "b", "c"], ["a", "c"], 3, 1.0),
    (["a", "a"], ["a", "b"], 2, 0.5),
    (["a"], [], 3, 0.0),
    ([], ["a"], 3, 0.0),
    (["a"], ["a"], 0, 0.0),
])
def test_recall_at_k(ranked, relevant, k, expected):
    assert recall_at_k(ranked, relevant, k) == expected


@pytest.mark.parametrize("ranked,relevant,expected", [
    (["a", "b", "c"], ["b", "c"], 0.5),
    (["a", "b"], ["a"], 1.0),
    (["a"], ["b"], 0.0),
    ([], ["a"], 0.0),
    (["a"], [], 0.0),
])
def test_reciprocal_rank(ranked, relevant, expected):
    assert reciprocal_rank(ranked, relevant) == expected


def test_hybrid_rrf_arm_fuses_dense_and_bm25_with_the_production_policy():
    from eval.retrieval_eval import hybrid_rrf

    corpus = [{"id": f"p{i}", "payload": {"text": f"text {i}"}} for i in range(3)]
    candidates = [{"id": "p0", "text": "text 0", "score": 0.9}, {"id": "p1", "text": "text 1", "score": 0.8}]
    # BM25 ranks p1 first and also finds p2, which the embedding missed.
    bm25_values = [0.5, 3.0, 2.0]
    bm25_order = [1, 2, 0]
    fused = hybrid_rrf(candidates, bm25_order, bm25_values, corpus, candidate_limit=24)
    assert [row["id"] for row in fused] == ["p1", "p0", "p2"]
    assert fused[0]["score"] > fused[1]["score"] > fused[2]["score"]


def test_dense_vector_reads_plain_and_hybrid_point_vectors():
    from eval.retrieval_eval import dense_vector

    assert dense_vector([0.1, 0.2]) == [0.1, 0.2]
    assert dense_vector({"": [0.1, 0.2], "bm25": {"indices": [1], "values": [1.0]}}) == [0.1, 0.2]
