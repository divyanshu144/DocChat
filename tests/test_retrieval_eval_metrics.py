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
