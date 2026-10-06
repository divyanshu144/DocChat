import json

from eval.audit_answer_citations import audit


def test_citation_audit_checks_exact_markers_against_captured_context(tmp_path):
    path = tmp_path / "answers.jsonl"
    rows = [
        {"case_id": "qa-1", "model": "private-model", "split": "held_out", "status": "ok",
         "messages": [{"role": "system", "content": "Source marker: [PDF — p.1]\nText"}],
         "answer": "Claim.\nSources:\n[PDF — p.1]"},
        {"case_id": "qa-2", "model": "private-model", "split": "held_out", "status": "ok",
         "messages": [{"role": "system", "content": "Source marker: [PDF — p.1]\nText"}],
         "answer": "Claim.\nSources:\n[PDF — fabricated.pdf p.4]"},
        {"case_id": "qa-3", "model": "private-model", "split": "held_out", "status": "error",
         "messages": [], "answer": ""},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows))

    report = audit([path])["groups"][0]

    assert report["successful_answers"] == 2
    assert report["failed_answers"] == 1
    assert report["answer_citation_coverage"] == 0.5
    assert report["citation_precision"] == 0.5
