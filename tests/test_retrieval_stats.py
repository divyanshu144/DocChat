"""Paired comparison statistics used to decide whether one retrieval arm really beats another."""
import pytest

from eval import retrieval_stats as rs


def _row(stratum, overlap, **arms):
    return {"stratum": stratum, "lexical_overlap": overlap,
            "rankings": {name: {m: v for m in rs.METRICS} for name, v in arms.items()}}


def test_identical_samples_have_zero_difference_and_are_not_significant():
    result = rs.paired_bootstrap([0.5, 1.0, 0.0], [0.5, 1.0, 0.0], resamples=500)
    assert result["mean_diff"] == 0
    assert result["ci_low"] == result["ci_high"] == 0
    assert result["significant"] is False


def test_a_consistent_gain_is_significant():
    a = [1.0] * 40
    b = [0.5] * 40
    result = rs.paired_bootstrap(a, b, resamples=500)
    assert result["mean_diff"] == pytest.approx(0.5)
    assert result["ci_low"] > 0 and result["significant"]


def test_a_noisy_mixed_difference_straddles_zero():
    a = [1.0, 0.0] * 10
    b = [0.0, 1.0] * 10
    result = rs.paired_bootstrap(a, b, resamples=1000, seed=3)
    assert result["ci_low"] < 0 < result["ci_high"]
    assert result["significant"] is False


def test_bootstrap_is_deterministic_for_a_seed():
    a, b = [1.0, 0.5, 0.0, 1.0], [0.5, 0.5, 0.5, 0.0]
    assert rs.paired_bootstrap(a, b, resamples=300, seed=9) == rs.paired_bootstrap(a, b, resamples=300, seed=9)


def test_unpaired_or_empty_samples_are_rejected():
    with pytest.raises(ValueError):
        rs.paired_bootstrap([1.0], [1.0, 0.0])
    with pytest.raises(ValueError):
        rs.paired_bootstrap([], [])


def test_win_loss_tie_counts():
    assert rs.win_loss_tie([1, 0.5, 0, 1], [0, 0.5, 1, 0]) == {"wins": 2, "losses": 1, "ties": 1}


def test_analysis_groups_by_stratum_and_overlap_thirds():
    rows = [_row("exact_term" if i % 2 else "paraphrase", i / 10, hybrid_rrf=1.0 if i % 2 else 0.0, dense=0.5)
            for i in range(9)]
    analysis = rs.analyse({"results": rows}, pairs=[("hybrid_rrf", "dense")], resamples=200)
    assert analysis["all"]["n"] == 9
    assert analysis["stratum:exact_term"]["n"] == 4 and analysis["stratum:paraphrase"]["n"] == 5
    assert [analysis[k]["n"] for k in ("overlap_low", "overlap_mid", "overlap_high")] == [3, 3, 3]
    exact = analysis["stratum:exact_term"]["comparisons"]["hybrid_rrf - dense"]["reciprocal_rank"]
    assert exact["mean_diff"] == pytest.approx(0.5) and exact["wins"] == 4


def test_pairs_with_a_missing_arm_are_skipped():
    analysis = rs.analyse({"results": [_row(None, None, dense=1.0)]}, pairs=[("hybrid_rrf", "dense")], resamples=50)
    assert analysis["all"]["comparisons"] == {}


def test_render_marks_significant_rows():
    rows = [_row(None, None, hybrid_rrf=1.0, dense=0.0) for _ in range(20)]
    text = rs.render(rs.analyse({"results": rows}, pairs=[("hybrid_rrf", "dense")], resamples=200))
    assert " *" in text and "W/L/T 20/0/0" in text
