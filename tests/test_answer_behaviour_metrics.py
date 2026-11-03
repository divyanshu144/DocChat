"""Judge-free answer behaviour metrics: each mechanical check, the denominators, and the paired test."""
import pytest

from eval.answer_behaviour_metrics import FORMAT_CHECKS, analyse, mcnemar_exact, paired, summarise
from tests.test_finetune_validation import ABSTAIN, GOOD, M1, system


def row(answer, *, case_id="c1", category="document_qa", status="ok", finish="stop"):
    return {"case_id": case_id, "category": category, "status": status, "answer": answer, "finish_reason": finish,
            "messages": [{"role": "system", "content": system()}, {"role": "user", "content": "q?"}]}


def test_a_well_formed_answer_passes_every_check():
    result = analyse(row(GOOD))
    assert all(result[c] for c in FORMAT_CHECKS) and result["well_formed_answer"] and not result["abstained"]


@pytest.mark.parametrize("answer,failing", [
    ("Statutory pay lasts 39 weeks.", "has_sources"),
    ("Statutory pay lasts 39 weeks.\n\nSources:\n\n[Web - Not in the context]", "citations_valid"),
    (f"Statutory pay lasts 39 weeks {M1}.\n\nSources:\n\n{M1}", "no_body_citations"),
    (f"**Statutory pay** lasts 39 weeks.\n\nSources:\n\n{M1}", "no_markdown"),
    (f"Statutory pay lasts 39 weeks.\n\nSources:\n\n{M1}\n{M1}", "no_duplicate_sources"),
])
def test_each_format_rule_is_checked_on_its_own(answer, failing):
    result = analyse(row(answer))
    assert result[failing] is False and result["well_formed_answer"] is False
    expected_ok = [c for c in FORMAT_CHECKS if c != failing and not (failing == "has_sources" and c == "citations_valid")]
    assert all(result[c] for c in expected_ok), result  # no sources section also means no valid citations, by definition


def test_an_abstention_is_not_a_well_formed_answer_and_needs_no_citation():
    result = analyse(row(ABSTAIN, category="negative_control"))
    assert result["abstained"] and not result["well_formed_answer"]
    assert not analyse(row(f"{ABSTAIN}\n\nSources:\n\n{M1}"))["abstained"]  # an abstention that cites a source is not one


def test_a_failed_or_empty_answer_fails_everything_and_stays_in_the_denominator():
    for bad in (row("", status="ok"), row("Answer.\n\nSources:\n\n" + M1, status="error")):
        result = analyse(bad)
        assert result["failed"] and not result["well_formed_answer"] and not any(result[c] for c in FORMAT_CHECKS)
    summary = summarise([row(GOOD, case_id="a"), row("", case_id="b"), row(ABSTAIN, case_id="n", category="negative_control")])
    assert summary["cases"] == 3 and summary["failed_or_empty"] == 1
    assert summary["answerable"]["well_formed_answer"]["n"] == 2 and summary["answerable"]["well_formed_answer"]["k"] == 1
    assert summary["negative_control"]["correct_abstention"]["rate"] == 1.0


def test_answerable_and_negative_cases_are_reported_separately_with_intervals():
    rows = [row(GOOD, case_id=f"a{i}") for i in range(8)] + [row(ABSTAIN, case_id="a-refuse", category="document_qa")]
    rows += [row(ABSTAIN, case_id="n1", category="negative_control"), row(GOOD, case_id="n2", category="negative_control")]
    s = summarise(rows)
    assert s["answerable"]["false_refusal"]["k"] == 1 and s["answerable"]["false_refusal"]["n"] == 9
    assert s["negative_control"]["unsupported_answer"]["k"] == 1 and s["negative_control"]["unsupported_answer"]["n"] == 2
    low, high = s["answerable"]["well_formed_answer"]["wilson95"]
    assert 0 < low < s["answerable"]["well_formed_answer"]["rate"] < high < 1


def test_the_exact_paired_test():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(0.0625)
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(10, 0) < 0.01 and mcnemar_exact(2, 8) == pytest.approx(mcnemar_exact(8, 2))


def test_paired_comparison_counts_only_cases_both_arms_answered_and_where_they_differ():
    a = [row(GOOD, case_id="1"), row(GOOD, case_id="2"), row("no sources", case_id="3"), row(GOOD, case_id="only-a")]
    b = [row("no sources", case_id="1"), row(GOOD, case_id="2"), row(GOOD, case_id="3")]
    result = paired(a, b, "answerable", "well_formed_answer")
    assert result == {"shared_cases": 3, "only_first": 1, "only_second": 1, "p_exact": 1.0}


def test_a_long_answer_that_notes_a_gap_is_not_a_short_abstention():
    long_answer = ("Statutory pay lasts 39 weeks and is paid monthly. " * 12) + "The context does not specify the exact rate."
    result = analyse(row(long_answer))
    assert result["abstained"] and not result["abstained_short"]  # the loose measure counts it, the strict one does not
    assert analyse(row(ABSTAIN))["abstained_short"]
    summary = summarise([row(long_answer, case_id="a"), row(GOOD, case_id="b")])
    assert summary["answerable"]["false_refusal"]["k"] == 1 and summary["answerable"]["false_refusal_short"]["k"] == 0
