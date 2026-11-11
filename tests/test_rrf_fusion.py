import pytest

from app.services.hybrid import reciprocal_rank_fusion


def test_rrf_scores_follow_the_formula():
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)


def test_item_in_both_rankings_beats_a_single_ranking_leader():
    # "b" is second in both lists; "a" and "c" each lead one list only.
    fused = reciprocal_rank_fusion([["a", "b"], ["c", "b"]], k=60)
    assert [item for item, _ in fused] == ["b", "a", "c"]  # agreement outranks a lone first place at k=60
    assert dict(fused)["b"] == pytest.approx(2 / 62)


def test_ties_break_by_best_rank_then_first_appearance_deterministically():
    # a and c tie on score; both best-rank 1. "a" appears first in list order.
    first = reciprocal_rank_fusion([["a"], ["c"]], k=60)
    assert [item for item, _ in first] == ["a", "c"]
    # Same inputs, same output, every time.
    assert reciprocal_rank_fusion([["a"], ["c"]], k=60) == first


def test_empty_rankings_and_single_ranking():
    assert reciprocal_rank_fusion([], k=60) == []
    assert reciprocal_rank_fusion([[], []], k=60) == []
    assert [i for i, _ in reciprocal_rank_fusion([["x", "y", "z"]], k=60)] == ["x", "y", "z"]


def test_duplicate_ids_inside_one_ranking_count_once_at_their_best_rank():
    fused = dict(reciprocal_rank_fusion([["a", "b", "a"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62)


def test_weights_scale_each_ranking():
    fused = dict(reciprocal_rank_fusion([["a"], ["b"]], k=60, weights=[2.0, 1.0]))
    assert fused["a"] == pytest.approx(2 / 61)
    assert fused["b"] == pytest.approx(1 / 61)


def test_invalid_arguments_are_rejected():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"], ["b"]], k=60, weights=[1.0])
