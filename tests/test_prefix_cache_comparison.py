import json

import pytest

from eval.quantization_compare import compare_prefix_caching, compare_sustained_runs, main
from eval.serving_load import ArtifactWriter, repeat_summary, summarize

BASE_MANIFEST = {
    "schema_version": 2, "target": "replay", "workload_sha256": "w", "corpus_sha256": "c", "cache_mode": "reuse",
    "token_policy": "provider_only", "duration_s": 60, "request_limit": 100, "timeout_s": 120, "warmup_requests": 2,
    "repeats": 2, "min_samples": 1, "sampling": "default", "concurrency": [4], "arrival_rates": [None],
    "latency_slo_s": None, "source": {"git_commit": "example"},
}
DEPLOYMENT = {"engine": "vllm", "image_digest": "d", "gpu_name": "g", "gpu_count": 1, "max_model_len": 16384,
              "compute_dtype": "float16", "model_repository": "Qwen/test", "weight_quantization": None}


def hit(queries, hits):
    return {"status": "ok", "queries": queries, "hits": hits, "hit_rate": hits / queries, "unit": "tokens"}


HALF_HITS = (hit(1000, 500), hit(3000, 1500))
NO_HITS = (hit(1000, 0), hit(3000, 0))


def make_run(tmp_path, label, prefix_caching, repeats=HALF_HITS, cache_mode="reuse",
             deployment=None, with_events=True):
    manifest = {**BASE_MANIFEST, "run_id": label, "cache_mode": cache_mode,
                "deployment": {**DEPLOYMENT, "prefix_caching": prefix_caching, **(deployment or {})}}
    writer = ArtifactWriter(tmp_path / label, manifest)
    cells = []
    for index, summary_hit in enumerate(repeats, 1):
        cell_id = f"r{index}-c4-rateNone"
        summary = summarize([{"status": "ok", "total_s": 1.0 + index, "output_tokens": 10}], 10, min_samples=1)
        writer.write({"event": "cell_summary", "cell_id": cell_id, "phase": "measurement", "concurrency": 4,
                      "arrival_rate": None, "summary": summary})
        if with_events:
            event = {"event": "engine_counter_changes", "cell_id": cell_id, "failed_scrapes": 0, "changes": []}
            if summary_hit is not None:
                event["prefix_cache"] = summary_hit
            writer.write(event)
        cells.append({"concurrency": 4, "arrival_rate": None, "summary": summary})
    writer.write({"event": "run_summary", "cells": repeat_summary(cells)})
    writer.write({"event": "run_end", "outcome": "complete"})
    writer.close()
    return tmp_path / label


def pair(tmp_path, on_hits=HALF_HITS, off_hits=NO_HITS, **kwargs):
    return (make_run(tmp_path, "on", True, on_hits, **kwargs), make_run(tmp_path, "off", False, off_hits, **kwargs))


def test_on_versus_off_reports_pooled_hit_rates_per_cell_and_the_design(tmp_path):
    on, off = pair(tmp_path)
    result = compare_prefix_caching(on, off)
    column = result["cells"][0]["prefix_cache"]
    assert column["baseline"]["hit_rate"] == pytest.approx(2000 / 4000)         # pooled across repeats, not a mean of rates
    assert column["baseline"]["repeats_with_data"] == 2 and column["variant"]["hit_rate"] == 0
    assert result["design"]["cache_mode"] == "reuse" and result["design"]["baseline"] == "prefix caching on"
    assert result["warnings"] == [] and any("no causal" in limit for limit in result["limits"])
    assert result["cells"][0]["metrics"]                                           # the ordinary comparison is still there


def test_pooling_weights_by_queries_not_by_repeat(tmp_path):
    on, off = pair(tmp_path, on_hits=(hit(100, 90), hit(900, 90)))
    assert compare_prefix_caching(on, off)["cells"][0]["prefix_cache"]["baseline"]["hit_rate"] == pytest.approx(180 / 1000)


@pytest.mark.parametrize("on_flag,off_flag", [(False, False), (True, True), (None, False), (True, None), (False, True)])
def test_refuses_unless_baseline_is_caching_on_and_variant_is_caching_off(tmp_path, on_flag, off_flag):
    on, off = make_run(tmp_path, "on", on_flag), make_run(tmp_path, "off", off_flag)
    with pytest.raises(ValueError, match="prefix_caching"):
        compare_prefix_caching(on, off)


def test_refuses_different_models_or_quantization_and_everything_the_base_comparison_refuses(tmp_path):
    on = make_run(tmp_path, "on", True)
    other = make_run(tmp_path, "other", False, deployment={"model_repository": "Qwen/other"})
    with pytest.raises(ValueError, match="model_repository"):
        compare_prefix_caching(on, other)
    quant = make_run(tmp_path, "quant", False, deployment={"weight_quantization": "awq"})
    with pytest.raises(ValueError, match="weight_quantization"):
        compare_prefix_caching(on, quant)
    mismatch = make_run(tmp_path, "mismatch", False, deployment={"gpu_name": "other-gpu"})
    with pytest.raises(ValueError, match="gpu_name"):
        compare_prefix_caching(on, mismatch)                                     # the existing comparability check


def test_bust_mode_is_labelled_a_control_and_unexpected_hits_are_warned_about(tmp_path):
    on, off = pair(tmp_path, on_hits=(hit(1000, 0), hit(1000, 0)), off_hits=(hit(1000, 0), hit(1000, 0)),
                   cache_mode="bust")
    result = compare_prefix_caching(on, off)
    assert "control" in result["design"]["note"] and result["warnings"] == []
    t2 = tmp_path / "t2"
    t2.mkdir()
    on2, off2 = pair(t2, on_hits=(hit(1000, 400), hit(1000, 400)), off_hits=(hit(1000, 0), hit(1000, 0)),
                     cache_mode="bust")
    assert any("busting" in w for w in compare_prefix_caching(on2, off2)["warnings"])


def test_a_caching_off_arm_that_shows_hits_and_a_reuse_arm_that_shows_none_are_flagged(tmp_path):
    on, off = pair(tmp_path, off_hits=(hit(1000, 300), hit(1000, 300)))
    assert any("caching-off" in w for w in compare_prefix_caching(on, off)["warnings"])
    t2 = tmp_path / "t2"
    t2.mkdir()
    on2, off2 = pair(t2, on_hits=(hit(1000, 0), hit(1000, 0)))
    assert any("caching-on" in w and "no hits" in w for w in compare_prefix_caching(on2, off2)["warnings"])


def test_missing_or_old_run_data_is_unavailable_with_a_reason_and_never_refuses(tmp_path):
    on = make_run(tmp_path, "on", True, with_events=False)                       # no engine metrics at all
    off = make_run(tmp_path, "off", False, repeats=(None, None))                 # events without a prefix_cache field
    column = compare_prefix_caching(on, off)["cells"][0]["prefix_cache"]
    assert column["baseline"]["status"] == "unavailable" and "no engine metrics" in column["baseline"]["reason"]
    assert column["variant"]["status"] == "unavailable" and "predates" in column["variant"]["reason"]
    assert "hit_rate" not in column["baseline"] and "hit_rate" not in column["variant"]


def test_partial_data_is_marked_partial_and_pooled_only_over_repeats_that_have_it(tmp_path):
    on, off = pair(tmp_path, on_hits=(hit(1000, 500), {"status": "unavailable", "reason": "counter reset"}))
    base = compare_prefix_caching(on, off)["cells"][0]["prefix_cache"]["baseline"]
    assert base["status"] == "partial" and base["repeats_with_data"] == 1 and base["hit_rate"] == 0.5


def test_the_generic_comparison_is_unchanged_by_this_mode(tmp_path):
    on, off = pair(tmp_path)
    generic = compare_sustained_runs(on, off)
    assert all("prefix_cache" not in row for row in generic["cells"]) and "design" not in generic


def test_cli_flag_prints_the_prefix_cache_comparison(tmp_path, monkeypatch, capsys):
    on, off = pair(tmp_path)
    monkeypatch.setattr("sys.argv", ["quantization_compare", "--prefix-cache-comparison",
                                     "--baseline-run", str(on), "--variant-run", str(off)])
    main()
    printed = json.loads(capsys.readouterr().out)
    assert printed["design"]["baseline"] == "prefix caching on" and "prefix_cache" in printed["cells"][0]
    monkeypatch.setattr("sys.argv", ["quantization_compare", "--prefix-cache-comparison"])
    with pytest.raises(SystemExit):
        main()
