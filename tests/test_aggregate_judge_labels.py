import json

import pytest

from eval.aggregate_judge_labels import aggregate, model_format, wilson

JUDGE = {"provider": "openai", "model": "j", "prompt_version": "v1", "prompt_sha256": "h", "temperature": 0}


def labels(correct="yes", citation="not_applicable", abstain="not_applicable", unsupported=0):
    return {"answer_correct": correct, "fully_supported": "yes" if not unsupported else "partial",
            "unsupported_claim_count": unsupported, "citation_correct": citation,
            "abstention_correct": abstain,
            "claims": [{"text": "c", "supported": False}] * unsupported, "notes": ""}


def setup(tmp_path, specs):
    """specs: (blind_id, format, split, expected_abstention, labels | None)"""
    pack, key, judged = [], [], []
    for blind_id, fmt, split, negative, lab in specs:
        pack.append({"blind_id": blind_id, "split": split, "expected_abstention": negative})
        key.append({"blind_id": blind_id, "answer_file": f"reports/x-answers-{fmt}.jsonl", "model": "m"})
        judged.append({"blind_id": blind_id, "judge": JUDGE, "labels": lab,
                       "parse_status": "ok" if lab else "invalid_json"})
    paths = {name: tmp_path / name for name in ("pack.jsonl", "labels.jsonl", "key.json")}
    paths["pack.jsonl"].write_text("\n".join(map(json.dumps, pack)))
    paths["labels.jsonl"].write_text("\n".join(map(json.dumps, judged)))
    paths["key.json"].write_text(json.dumps({"schema_version": 1, "records": key}))
    return paths["labels.jsonl"], paths["pack.jsonl"], paths["key.json"]


def test_groups_by_format_and_split_keeping_partial_separate(tmp_path):
    report = aggregate(*setup(tmp_path, [
        ("a", "fp16", "development", False, labels("yes")),
        ("b", "fp16", "development", False, labels("partial", unsupported=2)),
        ("c", "awq", "development", False, labels("no")),
        ("d", "awq", "held_out", True, labels("yes", abstain="yes")),
        ("e", "gptq", "held_out", False, None),
    ]))
    dev, held = report["by_split"]["development"], report["by_split"]["held_out"]
    assert set(dev) == {"fp16", "awq"} and set(held) == {"awq", "gptq"}
    fp16 = dev["fp16"]
    assert fp16["answer_correct"]["yes"]["count"] == 1 and fp16["answer_correct"]["partial"]["count"] == 1
    assert fp16["mean_unsupported_claims"] == 1.0 and fp16["small_sample_warning"] is True
    assert held["awq"]["abstention"]["negative_control_accuracy"]["rate"] == 1.0
    assert held["gptq"]["parse_failures"] == 1 and held["gptq"]["scored"] == 0
    assert report["human_verified"] is False


def test_not_applicable_citations_excluded_from_rate(tmp_path):
    report = aggregate(*setup(tmp_path, [
        ("a", "fp16", "development", False, labels(citation="yes")),
        ("b", "fp16", "development", False, labels(citation="no")),
        ("c", "fp16", "development", False, labels(citation="not_applicable")),
        ("d", "fp16", "development", False, labels(citation="not_applicable")),
    ]))
    citation = report["by_split"]["development"]["fp16"]["citation_correct"]
    assert citation["applicable"] == 2 and citation["not_applicable"] == 2
    assert citation["yes"]["rate"] == 0.5 and citation["yes"]["n"] == 2


def test_missing_key_fails_clearly(tmp_path):
    labels_path, pack_path, key_path = setup(tmp_path, [("a", "fp16", "development", False, labels())])
    with pytest.raises(FileNotFoundError, match="Unblinding key not found"):
        aggregate(labels_path, pack_path, tmp_path / "missing.json")


def test_unknown_blind_id_rejected(tmp_path):
    labels_path, pack_path, key_path = setup(tmp_path, [("a", "fp16", "development", False, labels())])
    key_path.write_text(json.dumps({"records": []}))
    with pytest.raises(ValueError, match="missing from key"):
        aggregate(labels_path, pack_path, key_path)


def test_model_format_and_wilson():
    assert model_format({"answer_file": "reports/heldout-answers-gptq.jsonl"}) == "gptq"
    assert model_format({"answer_file": "", "model": "Qwen2.5-7B-Instruct-AWQ"}) == "awq"
    low, high = wilson(1, 4)
    assert 0 < low < 0.25 < high < 1 and wilson(0, 0) is None


def test_audit_overlay_changes_labels_in_memory_only(tmp_path):
    labels_path, pack_path, key_path = setup(tmp_path, [
        ("a", "fp16", "development", False, labels("no")),
        ("b", "fp16", "development", False, labels("yes"))])
    before = labels_path.read_text()
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({"blind_id": "a", "suggested_labels_full": labels("partial")}) + "\n")
    report = aggregate(labels_path, pack_path, key_path, audit)
    cell = report["by_split"]["development"]["fp16"]["answer_correct"]
    assert (cell["yes"]["count"], cell["partial"]["count"], cell["no"]["count"]) == (1, 1, 0)
    assert report["label_source"] == "llm_assisted_audited" and labels_path.read_text() == before


def test_compare_reports_agreement_and_disagreements(tmp_path):
    from eval.compare_judge_labels import compare, unsupported_stats

    def row(i, correct, supported="yes", unsupported=0):
        return {"blind_id": i, "parse_status": "ok", "labels": {
            "answer_correct": correct, "fully_supported": supported, "unsupported_claim_count": unsupported,
            "citation_correct": "not_applicable", "abstention_correct": "not_applicable"}}
    a = {"x": row("x", "yes"), "y": row("y", "partial", "partial", 2)}
    b = {"x": row("x", "yes"), "y": row("y", "yes", "partial", 1)}
    result = compare(a, b)
    assert result["fields"]["answer_correct"]["agree"] == 1
    assert result["fields"]["answer_correct"]["disagreements"] == {"partial->yes": 1}
    assert result["disagreeing_rows"]["answer_correct"] == ["y"]
    assert unsupported_stats(a)["total_unsupported"] == 2 and unsupported_stats(b)["rows_with_unsupported"] == 1


def test_pairwise_file_comparison_restricts_to_shared_rows_and_lists_differences(tmp_path):
    from eval.compare_judge_labels import compare_files

    def row(i, model, correct, unsupported, status="ok"):
        return {"blind_id": i, "parse_status": status, "judge": {"model": model, "prompt_version": "v2"},
                "labels": {"answer_correct": correct, "fully_supported": "partial",
                           "unsupported_claim_count": unsupported, "minor_imprecision_count": 0,
                           "citation_correct": "not_applicable", "abstention_correct": "not_applicable",
                           "claims": [], "notes": model}}
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("\n".join(json.dumps(r) for r in [row("x", "A", "yes", 0), row("y", "A", "yes", 1), row("z", "A", "yes", 0)]))
    b.write_text("\n".join(json.dumps(r) for r in [row("x", "B", "yes", 0), row("y", "B", "partial", 2)]))
    result = compare_files(a, b)
    assert result["comparison"]["rows_compared"] == 2 and result["a"] == ["A/v2"] and result["b"] == ["B/v2"]
    assert [d["blind_id"] for d in result["row_details"]] == ["y"]
    assert result["row_details"][0]["label_changes"] == {"answer_correct": ["yes", "partial"]}
