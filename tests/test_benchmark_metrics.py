"""Unit tests for eval/benchmark.py metric computation.

Pure logic — no LLM, no `eval` marker, runs in the normal suite.
"""

import pytest

from eval.benchmark import _compute_metrics, _fmt
from eval.cases import BENCHMARK_CASES


def _r(expected: str, got: str) -> dict:
    return {"expected": expected, "got": got}


def test_matches_spec_worked_example():
    """The spec's documented example: TP=1 FP=2 FN=0 TN=2 -> P=0.33 R=1.00 F1=0.50."""
    results = [
        _r("good", "good"),
        _r("good", "poor"),
        _r("poor", "poor"),
        _r("good", "good"),
        _r("good", "poor"),
    ]
    m = _compute_metrics(results)

    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 2, 0, 2)
    assert _fmt(m["precision"]) == "0.33"
    assert _fmt(m["recall"]) == "1.00"
    assert _fmt(m["f1"]) == "0.50"


def test_poor_is_the_positive_class():
    """A missed poor answer is a false negative, not a false positive."""
    m = _compute_metrics([_r("poor", "good")])
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (0, 0, 1, 0)


def test_nothing_flagged_poor_leaves_precision_undefined():
    """Zero denominator is undefined, not zero — must not report 0.00."""
    m = _compute_metrics([_r("good", "good"), _r("good", "good")])
    assert m["precision"] is None
    assert m["recall"] is None
    assert m["f1"] is None
    assert _fmt(m["precision"]).strip() == "N/A"


def test_no_poor_cases_leaves_recall_undefined():
    m = _compute_metrics([_r("good", "poor")])
    assert m["precision"] == 0.0   # flagged one, none were poor
    assert m["recall"] is None     # there were no poor cases to catch
    assert m["f1"] is None


def test_total_failure_reports_zero_f1_not_undefined():
    """P=0 and R=0 is a defined zero score, not N/A."""
    m = _compute_metrics([
        _r("good", "poor"),
        _r("good", "poor"),
        _r("poor", "good"),
    ])
    assert (m["precision"], m["recall"], m["f1"]) == (0.0, 0.0, 0.0)
    assert _fmt(m["f1"]).strip() == "0.00"


def test_perfect_agreement():
    m = _compute_metrics([_r("poor", "poor"), _r("good", "good")])
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0


def test_empty_results_do_not_raise():
    m = _compute_metrics([])
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (0, 0, 0, 0)
    assert m["precision"] is None and m["recall"] is None and m["f1"] is None


def test_error_results_are_excluded_from_confusion_matrix():
    m = _compute_metrics([_r("poor", "poor"), _r("good", "error")])
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 0, 0, 0)
    assert m["errors"] == 1
    assert m["precision"] == 1.0


@pytest.mark.parametrize("value,expected", [(None, "N/A"), (0.0, "0.00"), (1.0, "1.00"), (1 / 3, "0.33")])
def test_fmt(value, expected):
    assert _fmt(value).strip() == expected


def test_benchmark_dataset_shape():
    """Spec fixes the seed dataset at 5 cases, skewed 4 good / 1 poor."""
    assert len(BENCHMARK_CASES) == 5
    assert sum(1 for c in BENCHMARK_CASES if c.expected == "good") == 4
    assert sum(1 for c in BENCHMARK_CASES if c.expected == "poor") == 1
    assert len({c.label for c in BENCHMARK_CASES}) == 5


def test_benchmark_cases_are_independent_of_regression_guard():
    """The two lists must not overlap — borderline cases would flap in the guard."""
    from eval.cases import CASES

    assert {c.label for c in BENCHMARK_CASES}.isdisjoint({c.label for c in CASES})
