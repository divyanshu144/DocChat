import json

from eval.build_disagreement_sheet import build

CONTEXT = "rules\n\nContext:\nSource marker: [PDF - a p.1]\nevidence text"


def lab(correct="yes", supported="yes", unsupported=0):
    return {"answer_correct": correct, "fully_supported": supported, "unsupported_claim_count": unsupported,
            "minor_imprecision_count": 0, "citation_correct": "not_applicable",
            "abstention_correct": "not_applicable",
            "claims": [{"text": "c", "status": "unsupported"}] * unsupported, "notes": "n"}


def row(i, model, labels):
    return {"blind_id": i, "parse_status": "ok", "judge": {"model": model, "prompt_version": "v2"}, "labels": labels}


def test_sheet_lists_only_disagreements_and_hides_judge_names_and_formats(tmp_path):
    pack = [{"blind_id": i, "query": "q", "context": CONTEXT, "answer": "a", "split": "SECRET-SPLIT",
             "workload_case_id": "SECRET-CASE", "expected_facts": [{"id": "f", "text": "t"}],
             "expected_abstention": False} for i in ("x", "y")]
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("\n".join(json.dumps(r) for r in [row("x", "OpusModel", lab()), row("y", "OpusModel", lab("yes", "partial", 1))]))
    b.write_text("\n".join(json.dumps(r) for r in [row("x", "AstraModel", lab()), row("y", "AstraModel", lab("partial", "partial", 2))]))
    p = tmp_path / "p.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in pack))
    sheet, template, selection = build(p, a, b)
    assert [t["blind_id"] for t in template] == ["y"]
    assert set(template[0]["preferred"]) == {"answer_correct", "unsupported_claims"}
    for hidden in ("OpusModel", "AstraModel", "SECRET"):
        assert hidden not in sheet
    assert "Judge A" in sheet and "evidence text" in sheet
    assert selection["judge_a"] == ["OpusModel/v2"] and selection["judge_b"] == ["AstraModel/v2"]
