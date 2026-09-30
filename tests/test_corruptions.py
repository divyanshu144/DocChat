"""Corruption transforms — the generated labels are only worth as much as these tests.

Every generated case asserts "poor" without a human ever reading it. That is the whole
point (cheap ground truth) and the whole risk: a transform that silently no-ops emits a
*good* answer labelled poor, and the benchmark then measures the critic against a lie.
So the properties pinned here are mostly about what a transform must never do.
"""

import pytest

from eval.cases import BENCHMARK_CASES, CASES, CriticCase
from eval.corruptions import (
    SEEDS,
    TRANSFORMS,
    contradict_self,
    generate,
    strip_specifics,
    truncate_enumeration,
)


def _seed(label: str) -> CriticCase:
    return next(c for c in SEEDS if c.label == label)


# ---------------------------------------------------------------------------
# Dataset-level invariants
# ---------------------------------------------------------------------------

def test_every_generated_case_is_labelled_poor():
    assert all(c.expected == "poor" for c in generate())


def test_no_generated_case_is_identical_to_its_seed():
    """The poisoning guard. A no-op transform would emit a good answer labelled poor."""
    by_label = {c.label: c.answer for c in SEEDS}

    for case in generate():
        seed_answer = by_label[case.label.rsplit("__", 1)[0]]
        assert case.answer != seed_answer, f"{case.label} no-opped"


def test_only_good_seeds_are_corrupted():
    """Corrupting an already-poor answer yields a result nobody can label."""
    assert all(c.expected == "good" for c in SEEDS)

    poor = [c for c in (*BENCHMARK_CASES, *CASES) if c.expected == "poor"]
    generated_seeds = {c.label.rsplit("__", 1)[0] for c in generate()}
    assert generated_seeds.isdisjoint({c.label for c in poor})


def test_generation_is_deterministic():
    """Two unreproducible components would make a score change uninterpretable —
    you could not tell a prompt regression from a re-rolled dataset."""
    first = [(c.label, c.answer) for c in generate()]
    second = [(c.label, c.answer) for c in generate()]
    assert first == second


def test_generated_labels_are_unique_and_never_collide_with_the_guard():
    generated = generate()
    labels = [c.label for c in generated]

    assert len(labels) == len(set(labels))
    assert set(labels).isdisjoint({c.label for c in CASES})
    assert set(labels).isdisjoint({c.label for c in BENCHMARK_CASES})


def test_generated_cases_do_not_enter_the_regression_guard():
    """`eval/cases.py` requires Layer A and Layer B stay independent."""
    assert len(CASES) == 8
    assert len(BENCHMARK_CASES) == 5


def test_reason_records_that_the_label_came_from_a_transform():
    """A human auditing a case must not mistake an inherited label for a judged one."""
    for case in generate():
        assert "not a fresh human judgement" in case.reason


# ---------------------------------------------------------------------------
# Individual transforms
# ---------------------------------------------------------------------------

def test_contradict_self_appends_a_negation_of_the_opening_claim():
    corrupted = contradict_self(_seed("correct_but_terse"))

    assert corrupted is not None
    assert "DocChat uses the Groq API" in corrupted.answer
    assert "does not use the Groq API" in corrupted.answer


def test_contradict_self_declines_when_no_known_verb_is_present():
    """`correct_admits_gaps` opens on "does not contain" — negating a negation would
    produce an assertion, not a contradiction."""
    assert contradict_self(_seed("correct_admits_gaps")) is None


def test_strip_specifics_redacts_details_but_keeps_enumeration_structure():
    corrupted = strip_specifics(_seed("correct_multi_part_answer"))

    assert corrupted is not None
    assert "PyMuPDF" not in corrupted.answer
    assert "youtube-transcript-api" not in corrupted.answer
    # "(1)" is structure, not a detail the query asked for. Redacting it would turn a
    # vagueness corruption into a malformed-list one.
    assert "(1)" in corrupted.answer
    assert "(2)" in corrupted.answer


def test_strip_specifics_declines_on_a_lone_specific():
    """One redaction usually leaves the query still answered."""
    assert strip_specifics(_seed("admits_gaps_with_partial_answer")) is None


def test_truncate_enumeration_drops_the_final_promised_part():
    corrupted = truncate_enumeration(_seed("correct_multi_part_answer"))

    assert corrupted is not None
    assert "(1)" in corrupted.answer and "(2)" in corrupted.answer
    assert "(3)" not in corrupted.answer
    # Still promises three, now delivers two — detectable without the source.
    assert "three ingestion sources" in corrupted.answer


def test_truncate_enumeration_declines_without_an_enumeration():
    assert truncate_enumeration(_seed("correct_but_terse")) is None


def test_off_topic_swap_borrows_another_seeds_answer_verbatim():
    swapped = [c for c in generate() if c.label.endswith("__off_topic_swap")]
    seed_answers = {c.answer for c in SEEDS}

    assert len(swapped) == len(SEEDS)
    for case in swapped:
        assert case.answer in seed_answers


@pytest.mark.parametrize("transform", TRANSFORMS, ids=lambda t: t.__name__)
def test_body_transforms_preserve_the_citation_block(transform):
    """Dropping citations as a side effect would test two degradations at once."""
    seed = _seed("correct_well_grounded")
    corrupted = transform(seed)

    if corrupted is not None:
        assert "Sources:" in corrupted.answer
        assert "[PDF — architecture.pdf p.2]" in corrupted.answer


@pytest.mark.parametrize("transform", TRANSFORMS, ids=lambda t: t.__name__)
def test_transforms_never_return_their_input_unchanged(transform):
    for seed in SEEDS:
        corrupted = transform(seed)
        assert corrupted is None or corrupted.answer != seed.answer


@pytest.mark.parametrize("transform", TRANSFORMS, ids=lambda t: t.__name__)
def test_transforms_carry_the_query_and_context_through(transform):
    """The query must not drift — a corruption changes the answer, never the question."""
    for seed in SEEDS:
        corrupted = transform(seed)
        if corrupted is not None:
            assert corrupted.query == seed.query
            assert corrupted.context == seed.context
