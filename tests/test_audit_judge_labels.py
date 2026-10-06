import hashlib
import json
from pathlib import Path

import pytest

from eval.audit_judge_labels import (ANSWER_OVERRIDES, DECISIONS, audit_row, render_markdown,
                                      select_suffixes)
from eval.judge_prompt import validate_labels

PACK = Path("reports/quality-review-pack.jsonl")
LABELS = Path("reports/quality-judge-labels.jsonl")
needs_data = pytest.mark.skipif(not (PACK.exists() and LABELS.exists()), reason="review artifacts not present")


def row(claims, **labels):
    base = {"answer_correct": "yes", "fully_supported": "partial",
            "unsupported_claim_count": sum(not c[1] for c in claims), "citation_correct": "not_applicable",
            "abstention_correct": "not_applicable", "notes": "n",
            "claims": [{"text": t, "supported": s} for t, s in claims]}
    return {"blind_id": "review-aaaaaa", "parse_status": "ok", "labels": base | labels}


def test_reclassified_claims_are_not_counted_and_originals_untouched(monkeypatch):
    monkeypatch.setitem(DECISIONS, "aaaaaa", [("45-minute break", "wording_equivalent", "same", "high", None)])
    original = row([("A 45-minute break is required after 9 hours.", False), ("A real error.", False)])
    before = json.dumps(original)
    result = audit_row(original, "aaaaaa")
    assert json.dumps(original) == before
    assert result["suggested"]["unsupported_claim_count"] == 1
    assert result["retained_unsupported"] == ["A real error."]
    validate_labels(result["suggested_labels_full"])


def test_caveat_categories_keep_fully_supported_partial_and_clean_ones_upgrade(monkeypatch):
    monkeypatch.setitem(DECISIONS, "aaaaaa", [("knowingly", "omitted_qualifier", "q", "medium", None)])
    assert audit_row(row([("omits knowingly", False)]), "aaaaaa")["suggested"]["fully_supported"] == "partial"
    monkeypatch.setitem(DECISIONS, "aaaaaa", [("45-minute", "wording_equivalent", "w", "high", None)])
    assert audit_row(row([("45-minute", False)]), "aaaaaa")["suggested"]["fully_supported"] == "yes"


def test_strict_mode_skips_minor_imprecision(monkeypatch):
    monkeypatch.setitem(DECISIONS, "aaaaaa", [("gloss", "minor_imprecision", "g", "medium", None)])
    assert audit_row(row([("gloss", False)]), "aaaaaa", apply_minor=False)["suggested"]["unsupported_claim_count"] == 1
    assert audit_row(row([("gloss", False)]), "aaaaaa")["suggested"]["unsupported_claim_count"] == 0


def test_decision_must_match_exactly_one_claim(monkeypatch):
    monkeypatch.setitem(DECISIONS, "aaaaaa", [("dup", "duplicate_claim", "d", "high", None)])
    with pytest.raises(ValueError, match="matched 2"):
        audit_row(row([("dup one", False), ("dup two", False)]), "aaaaaa")
    with pytest.raises(ValueError, match="matched 0"):
        audit_row(row([("other", False)]), "aaaaaa")


@needs_data
def test_every_decision_applies_cleanly_to_the_real_labels_and_stays_valid():
    pack = {r["blind_id"]: r for r in map(json.loads, PACK.read_text().splitlines())}
    rows = [json.loads(line) for line in LABELS.read_text().splitlines()]
    digest = hashlib.sha256(LABELS.read_bytes()).hexdigest()
    selected = select_suffixes(pack, rows)
    results = [audit_row(r, suffix) for suffix, r in selected.items() if r["parse_status"] == "ok"]
    assert hashlib.sha256(LABELS.read_bytes()).hexdigest() == digest
    for result in results:
        assert result["human_verified"] is False and result["label_source"] == "llm_assisted_audit"
        validate_labels(result["suggested_labels_full"])
        assert result["suggested"]["unsupported_claim_count"] <= result["original"]["unsupported_claim_count"]
    covered = {r["blind_id"][-6:] for r in results}
    assert set(DECISIONS) <= covered and set(ANSWER_OVERRIDES) <= covered
    assert "audited" in render_markdown(results, rows, None, digest).lower()


@needs_data
def test_calibration_rules_hold_on_real_labels():
    pack = {r["blind_id"]: r for r in map(json.loads, PACK.read_text().splitlines())}
    rows = [json.loads(line) for line in LABELS.read_text().splitlines()]
    selected = select_suffixes(pack, rows)
    out = {s: audit_row(r, s) for s, r in selected.items() if r["parse_status"] == "ok"}
    # no audited row may still be answer_correct="no" when the central fact is present (rule 2)
    assert all(o["suggested"]["answer_correct"] != "no" for o in out.values())
    # every working-time row that mentioned 45 minutes after 9 hours has no remaining 45/9 unsupported claim
    for o in out.values():
        assert not any("45" in c and "9 hours" in c for c in o["retained_unsupported"])
    # negative-control abstention labels are unchanged
    for suffix, r in selected.items():
        if pack[r["blind_id"]]["expected_abstention"]:
            assert out[suffix]["suggested"]["abstention_correct"] == out[suffix]["original"]["abstention_correct"]
