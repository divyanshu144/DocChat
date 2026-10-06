import json

from eval.build_spot_check_sheet import build, select_rows

CONTEXT = "rules\n\nContext:\nSource marker: [PDF - a p.1]\nevidence text"


def pack_row(i, answer="a", negative=False):
    return {"blind_id": f"r{i}", "query": "q", "context": CONTEXT, "answer": answer,
            "expected_facts": [{"id": "fact-01", "text": "f"}], "expected_abstention": negative,
            "emitted_citations": [], "split": "SECRET-SPLIT", "workload_case_id": "SECRET-CASE"}


def label_row(i, correct="yes", supported="yes", unsupported=0, citation="not_applicable", status="ok"):
    labels = None if status != "ok" else {
        "answer_correct": correct, "fully_supported": supported, "unsupported_claim_count": unsupported,
        "citation_correct": citation, "abstention_correct": "not_applicable",
        "claims": [{"text": "c", "supported": False}] * unsupported, "notes": "n"}
    return {"blind_id": f"r{i}", "parse_status": status, "labels": labels, "judge": {}}


def test_selection_covers_risky_rows_and_random_clean_ones():
    pack = [pack_row(i) for i in range(12)] + [pack_row(12, answer="see [PDF p.1-2]")]
    labels = [label_row(0, correct="partial"), label_row(1, status="schema_error"),
              label_row(2, supported="partial", unsupported=3), label_row(12, citation="yes")]
    labels += [label_row(i) for i in range(3, 12)]
    reasons = select_rows(pack, labels, top_unsupported=1, random_supported=3)
    assert "answer_correct=partial" in reasons["r0"] and "parse_failure" in reasons["r1"]
    assert "highest_unsupported_claims" in reasons["r2"]
    assert "page_range_citation_marked_yes" in reasons["r12"]
    assert sum("random_fully_supported" in r for r in reasons.values()) == 3
    assert select_rows(pack, labels, top_unsupported=1, random_supported=3) == reasons


def test_sheet_is_blinded_and_template_is_empty(tmp_path):
    pack = [pack_row(i) for i in range(3)]
    labels = [label_row(0, correct="no"), label_row(1, status="invalid_json"), label_row(2)]
    (tmp_path / "p.jsonl").write_text("\n".join(map(json.dumps, pack)))
    (tmp_path / "l.jsonl").write_text("\n".join(map(json.dumps, labels)))
    sheet, template, selection = build(tmp_path / "p.jsonl", tmp_path / "l.jsonl")
    assert "SECRET" not in sheet and "random_fully_supported" not in sheet
    assert "evidence text" in sheet and "answer_correct: no" in sheet
    assert {row["blind_id"] for row in template} == set(selection)
    assert all(v is None for row in template for k, v in row.items() if k.endswith("_agree"))
