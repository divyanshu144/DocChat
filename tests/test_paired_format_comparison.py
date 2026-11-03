import json

from eval.paired_format_comparison import bootstrap_ci, paired, sign_test_p


def test_sign_test_and_bootstrap_basics():
    assert sign_test_p(0, 0) is None
    assert sign_test_p(5, 5) == 1.0
    assert abs(sign_test_p(8, 0) - 2 / 256) < 1e-12
    low, high = bootstrap_ci([1.0, 1.0, 0.0, 1.0])
    assert 0 <= low <= high <= 1 and bootstrap_ci([]) is None


def labels(correct="yes", supported="yes", unsupported=0):
    return {"answer_correct": correct, "fully_supported": supported, "unsupported_claim_count": unsupported,
            "citation_correct": "not_applicable", "abstention_correct": "not_applicable", "claims": [], "notes": ""}


def test_pairs_the_same_case_across_formats_and_skips_failed_rows(tmp_path):
    specs = [("a1", "c1", "fp16", labels("yes")), ("a2", "c1", "awq", labels("partial")),
             ("a3", "c1", "gptq", labels("yes")), ("b1", "c2", "fp16", labels("yes")),
             ("b2", "c2", "awq", labels("no")), ("b3", "c2", "gptq", None)]
    pack, key, rows = [], [], []
    for blind, case, fmt, lab in specs:
        pack.append({"blind_id": blind, "split": "held_out"})
        key.append({"blind_id": blind, "workload_case_id": case, "answer_file": f"reports/x-answers-{fmt}.jsonl"})
        rows.append({"blind_id": blind, "parse_status": "ok" if lab else "invalid_json", "labels": lab})
    paths = {n: tmp_path / n for n in ("p.jsonl", "l.jsonl", "k.json")}
    paths["p.jsonl"].write_text("\n".join(map(json.dumps, pack)))
    paths["l.jsonl"].write_text("\n".join(map(json.dumps, rows)))
    paths["k.json"].write_text(json.dumps({"records": key}))
    result = paired(paths["l.jsonl"], paths["p.jsonl"], paths["k.json"])
    split = result["by_split"]["held_out"]
    fp_awq = split["comparisons"]["fp16_vs_awq"]
    assert fp_awq["paired_cases"] == 2 and fp_awq["metrics"]["answer_score"]["fp16_better"] == 2
    assert fp_awq["metrics"]["answer_score"]["mean_diff"] == 0.75
    assert split["comparisons"]["fp16_vs_gptq"]["paired_cases"] == 1       # c2's gptq row failed to parse
    assert fp_awq["metrics"]["unsupported_claims"]["exploratory"] is True
    assert result["human_verified"] is False


def test_base_and_tuned_arms_are_kept_apart_and_paired(tmp_path):
    """Regression: base/tuned answer files used to fall into one 'fp16' bucket, so nothing was compared."""
    from eval.aggregate_judge_labels import aggregate, model_format as agg_format
    from eval.paired_format_comparison import model_format
    for fn in (model_format, agg_format):
        assert fn({"answer_file": "d/answers-base-v2.jsonl", "model": "Qwen2.5-7B-Instruct"}) == "base"
        assert fn({"answer_file": "d/answers-tuned-old.jsonl", "model": "docchat-lora"}) == "tuned"
    specs = [("a1", "c1", "base", labels("no")), ("a2", "c1", "tuned", labels("yes")),
             ("b1", "c2", "base", labels("partial")), ("b2", "c2", "tuned", labels("partial"))]
    pack, key, rows = [], [], []
    for blind, case, arm, lab in specs:
        pack.append({"blind_id": blind, "split": "held_out", "expected_abstention": False})
        key.append({"blind_id": blind, "workload_case_id": case, "answer_file": f"d/answers-{arm}-v2.jsonl"})
        rows.append({"blind_id": blind, "parse_status": "ok", "labels": lab, "judge": {"m": 1}})
    p, k, lp = tmp_path / "p.jsonl", tmp_path / "k.json", tmp_path / "l.jsonl"
    p.write_text("\n".join(map(json.dumps, pack)))
    k.write_text(json.dumps({"records": key}))
    lp.write_text("\n".join(map(json.dumps, rows)))
    result = paired(lp, p, k, formats=("base", "tuned"))
    cmp_ = result["by_split"]["held_out"]["comparisons"]
    assert list(cmp_) == ["base_vs_tuned"]
    score = cmp_["base_vs_tuned"]["metrics"]["answer_score"]
    assert (score["base_better"], score["tuned_better"], score["ties"]) == (0, 1, 1)
    arms = aggregate(lp, p, k)["by_split"]["held_out"]
    assert set(arms) == {"base", "tuned"} and arms["base"]["scored"] == 2
