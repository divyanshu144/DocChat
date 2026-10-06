import json
from pathlib import Path

import pytest

from eval.judge_prompt import build_messages, extract_evidence, parse_labels, validate_labels

PACK = Path("reports/quality-review-pack.jsonl")
CONTEXT = ("SYSTEM RULES: be helpful.\n\nConversation history:\nnone\n\nContext:\n"
           "Source marker: [PDF - a.pdf p.1]\nThe limit is 48 hours.\n\n---\n\n"
           "Source marker: [PDF - a.pdf p.2]\nSecond chunk.\n")


def _row(**extra):
    row = {"blind_id": "review-x", "workload_case_id": "SECRET-CASE", "split": "held_out",
           "model": "Qwen2.5-7B-Instruct-AWQ", "answer_file": "reports/heldout-answers-awq.jsonl",
           "query": "What is the limit?", "context": CONTEXT, "answer": "48 hours.",
           "expected_facts": [{"id": "fact-01", "text": "48 hours per week"}],
           "expected_abstention": False, "emitted_citations": []}
    return row | extra


def valid():
    return {"answer_correct": "yes", "fully_supported": "yes", "unsupported_claim_count": 1,
            "citation_correct": "not_applicable", "abstention_correct": "not_applicable",
            "claims": [{"text": "a", "supported": True}, {"text": "b", "supported": False}],
            "notes": "ok"}


def test_builder_does_not_leak_identifying_fields():
    text = json.dumps(build_messages(_row()))
    for leaked in ("SECRET-CASE", "held_out", "Qwen", "AWQ", "awq.jsonl", "heldout-answers", "review-x"):
        assert leaked not in text


def test_builder_strips_generation_prompt_and_keeps_only_chunks():
    text = build_messages(_row())[1]["content"]
    assert "SYSTEM RULES" not in text and "Conversation history" not in text
    assert "The limit is 48 hours." in text and "[PDF - a.pdf p.2]" in text


def test_extract_evidence_requires_context_section():
    with pytest.raises(ValueError):
        extract_evidence("no context here")
    assert len(extract_evidence(CONTEXT)) == 2


@pytest.mark.skipif(not PACK.exists(), reason="review pack not present")
def test_real_pack_builds_without_identifying_fields():
    for row in map(json.loads, PACK.read_text().splitlines()):
        text = json.dumps(build_messages(row))
        assert row["workload_case_id"] not in text and row["blind_id"] not in text
        assert "heldout-answers" not in text and "phase3-answers" not in text


def test_validation_accepts_valid_output():
    assert validate_labels(valid())["answer_correct"] == "yes"


@pytest.mark.parametrize("field,value", [("answer_correct", "maybe"), ("fully_supported", "n/a"),
                                         ("citation_correct", "yes!"), ("abstention_correct", "partial")])
def test_validation_rejects_bad_enums(field, value):
    with pytest.raises(ValueError, match="schema_error"):
        validate_labels(valid() | {field: value})


def test_validation_rejects_count_mismatch_without_fixing():
    labels = valid() | {"unsupported_claim_count": 0}
    with pytest.raises(ValueError, match="schema_error"):
        validate_labels(labels)
    assert labels["unsupported_claim_count"] == 0


def test_validation_rejects_missing_extra_keys_and_bad_claims():
    for bad in ({k: v for k, v in valid().items() if k != "notes"}, valid() | {"extra": 1},
                valid() | {"claims": [{"text": "a"}]}, valid() | {"unsupported_claim_count": True}):
        with pytest.raises(ValueError, match="schema_error"):
            validate_labels(bad)


def test_parse_labels_handles_fences_and_rejects_prose():
    assert parse_labels('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError, match="invalid_json"):
        parse_labels("The answer is correct.")


# --- v2 prompt ---------------------------------------------------------------------------

from eval.judge_prompt import PROMPT_SHA256, PROMPT_SHA256_V2, SYSTEM_PROMPT_V2, derive_fully_supported  # noqa: E402


def valid_v2(**extra):
    base = {"answer_correct": "yes", "fully_supported": "partial", "unsupported_claim_count": 1,
            "minor_imprecision_count": 1, "citation_correct": "not_applicable",
            "abstention_correct": "not_applicable",
            "claims": [{"text": "a", "status": "supported"}, {"text": "b", "status": "minor_imprecision"},
                       {"text": "c", "status": "unsupported"}], "notes": "ok"}
    return base | extra


def test_v2_prompt_differs_from_v1_and_has_no_dataset_specific_examples():
    assert PROMPT_SHA256_V2 != PROMPT_SHA256
    for audited_case in ("45", "9 hours", "knowingly makes a false record", "working-time", "RTWT"):
        assert audited_case not in SYSTEM_PROMPT_V2.replace('such as "knowingly"', "")


def test_v2_builder_does_not_leak_identifying_fields():
    text = json.dumps(build_messages(_row(), "v2"))
    for leaked in ("SECRET-CASE", "held_out", "Qwen", "AWQ", "awq.jsonl", "heldout-answers", "review-x"):
        assert leaked not in text
    assert build_messages(_row(), "v2")[0]["content"] == SYSTEM_PROMPT_V2


def test_v2_validation_accepts_consistent_output():
    assert validate_labels(valid_v2(), "v2")["fully_supported"] == "partial"
    assert validate_labels(valid_v2(fully_supported="yes", unsupported_claim_count=0, minor_imprecision_count=0,
                                    claims=[{"text": "a", "status": "supported"}]), "v2")


@pytest.mark.parametrize("bad", [
    valid_v2(fully_supported="yes"),                       # statuses imply partial
    valid_v2(unsupported_claim_count=0),                   # count mismatch
    valid_v2(minor_imprecision_count=2),                   # count mismatch
    valid_v2(claims=[{"text": "a", "supported": True}]),   # v1-shaped claim
    valid_v2(claims=[{"text": "a", "status": "maybe"}]),   # bad status
    valid_v2(answer_correct="maybe"),
    {k: v for k, v in valid_v2().items() if k != "minor_imprecision_count"},
])
def test_v2_validation_rejects_inconsistent_output(bad):
    with pytest.raises(ValueError, match="schema_error"):
        validate_labels(bad, "v2")


def test_v2_validation_rejects_v1_shaped_labels_and_vice_versa():
    with pytest.raises(ValueError, match="schema_error"):
        validate_labels(valid(), "v2")
    with pytest.raises(ValueError, match="schema_error"):
        validate_labels(valid_v2())


def test_derive_fully_supported():
    assert derive_fully_supported(0, 0, 5) == "yes"
    assert derive_fully_supported(0, 2, 5) == "partial"
    assert derive_fully_supported(2, 0, 5) == "partial"
    assert derive_fully_supported(3, 0, 5) == "no"
    assert derive_fully_supported(0, 0, 0) == "yes"   # abstention: no claims
