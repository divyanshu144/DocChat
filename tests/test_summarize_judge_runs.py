from eval.summarize_judge_runs import summarize


def row(correct="yes", unsupported=0, status="ok"):
    labels = None if status != "ok" else {
        "answer_correct": correct, "fully_supported": "yes" if not unsupported else "partial",
        "unsupported_claim_count": unsupported, "citation_correct": "not_applicable",
        "abstention_correct": "not_applicable"}
    return {"parse_status": status, "labels": labels}


def test_pairs_use_only_shared_rows_and_coverage_counts_cells():
    pack = {i: {"split": "development"} for i in "abc"}
    key = {i: {"answer_file": "reports/x-answers-fp16.jsonl"} for i in "abc"}
    runs = {"one": {"a": row(), "b": row(unsupported=1), "c": row()},
            "two": {"a": row(), "b": row("partial", 2)}}
    result = summarize(runs, pack, key)
    pair = result["pairs"]["one vs two"]
    assert pair["shared_rows"] == 2 and pair["disagreements"]["answer_correct"] == {"yes->partial": 1}
    assert result["coverage_by_split_format"]["one"] == {"development/fp16": 3}
    assert pair["stats"]["one"]["total_unsupported"] == 1 and pair["stats"]["two"]["total_unsupported"] == 2
