"""Unit tests for eval/quantization_compare.py's pure logic.

No network calls, no pod, no live sweep -- these are the dry-run tests for
Phase 3 (quantization comparison spec,
docs/superpowers/specs/2026-10-01-quantization-comparison-design.md). The
live sweep this script reports on needs a pod and an explicit go.
"""

import json
import tempfile
from pathlib import Path

from eval.quantization_compare import (
    _compare_rows,
    _fmt_comparison_table,
    _fmt_pct,
    _load_summary_rows,
)


def _row(provider, concurrency, timestamp, summary=None, cost_usd=0.01):
    return {
        "provider": provider,
        "concurrency": concurrency,
        "timestamp": timestamp,
        "summary": summary or {},
        "cost_usd": cost_usd,
    }


# ---------------------------------------------------------------------------
# _load_summary_rows
# ---------------------------------------------------------------------------


def test_load_summary_rows_filters_by_provider_and_window():
    rows = [
        _row("local", 1, "2026-10-02T00:30:00+00:00"),
        _row("openai", 1, "2026-10-02T00:30:00+00:00"),
        _row("local", 4, "2026-10-02T02:30:00+00:00"),  # outside the window
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        path = Path(f.name)

    result = _load_summary_rows(
        path, since="2026-10-02T00:00:00+00:00", until="2026-10-02T01:00:00+00:00"
    )
    path.unlink()

    assert len(result) == 1
    assert result[0]["concurrency"] == 1
    assert result[0]["provider"] == "local"


def test_load_summary_rows_skips_blank_lines():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(_row("local", 1, "2026-10-02T00:30:00+00:00")) + "\n")
        f.write("\n")
        path = Path(f.name)

    result = _load_summary_rows(
        path, since="2026-10-02T00:00:00+00:00", until="2026-10-02T01:00:00+00:00"
    )
    path.unlink()

    assert len(result) == 1


def test_load_summary_rows_empty_file_returns_empty_list():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = Path(f.name)

    result = _load_summary_rows(path, since="2026-10-02T00:00:00", until="2026-10-02T01:00:00")
    path.unlink()

    assert result == []


# ---------------------------------------------------------------------------
# _compare_rows
# ---------------------------------------------------------------------------


def test_compare_rows_computes_percentage_change():
    baseline = _row(
        "local", 16,
        "2026-10-02T00:30:00",
        summary={"ttft_p50": 1.0, "decode_tok_s_p50": 50.0, "aggregate_tok_s": 100.0},
        cost_usd=0.02,
    )
    variant = _row(
        "local", 16,
        "2026-10-02T01:30:00",
        summary={"ttft_p50": 0.5, "decode_tok_s_p50": 75.0, "aggregate_tok_s": 150.0},
        cost_usd=0.01,
    )
    result = _compare_rows(baseline, variant)
    assert result["concurrency"] == 16
    assert result["ttft_p50_pct"] == -50.0
    assert result["decode_tok_s_p50_pct"] == 50.0
    assert result["aggregate_tok_s_pct"] == 50.0
    assert result["cost_usd_pct"] == -50.0


def test_compare_rows_none_when_a_field_is_missing_not_a_fabricated_delta():
    baseline = _row("local", 16, "t", summary={"ttft_p50": 1.0})
    variant = _row("local", 16, "t", summary={})  # e.g. insufficient_samples cell

    result = _compare_rows(baseline, variant)

    assert result["ttft_p50_pct"] is None
    assert result["decode_tok_s_p50_pct"] is None
    assert result["aggregate_tok_s_pct"] is None


def test_compare_rows_none_when_baseline_field_is_zero_not_division_by_zero():
    baseline = _row("local", 16, "t", summary={"ttft_p50": 0.0})
    variant = _row("local", 16, "t", summary={"ttft_p50": 0.5})

    result = _compare_rows(baseline, variant)

    assert result["ttft_p50_pct"] is None


def test_compare_rows_flags_insufficient_samples_on_either_side():
    baseline = _row("local", 16, "t", summary={"insufficient_samples": True})
    variant = _row("local", 16, "t", summary={"insufficient_samples": False})

    result = _compare_rows(baseline, variant)

    assert result["baseline_insufficient_samples"] is True
    assert result["variant_insufficient_samples"] is False


def test_compare_rows_cost_pct_none_when_either_cost_is_none():
    baseline = _row("local", 16, "t", summary={}, cost_usd=None)
    variant = _row("local", 16, "t", summary={}, cost_usd=0.01)

    result = _compare_rows(baseline, variant)

    assert result["cost_usd_pct"] is None


# ---------------------------------------------------------------------------
# _fmt_pct / _fmt_comparison_table
# ---------------------------------------------------------------------------


def test_fmt_pct_none_is_na():
    assert _fmt_pct(None) == "   n/a"


def test_fmt_pct_positive_has_explicit_sign():
    assert _fmt_pct(12.345) == "+12.3%"


def test_fmt_pct_negative_keeps_its_own_sign():
    assert _fmt_pct(-50.0) == "-50.0%"


def test_fmt_comparison_table_contains_labels_and_concurrency():
    comparisons = [
        {
            "concurrency": 16,
            "ttft_p50_pct": -50.0,
            "decode_tok_s_p50_pct": 50.0,
            "aggregate_tok_s_pct": 50.0,
            "cost_usd_pct": -50.0,
            "baseline_insufficient_samples": False,
            "variant_insufficient_samples": False,
        }
    ]
    table = _fmt_comparison_table(comparisons, "fp16", "awq")
    assert "fp16 -> awq" in table
    assert "16" in table
    assert "-50.0%" in table


def test_fmt_comparison_table_flags_insufficient_samples():
    comparisons = [
        {
            "concurrency": 1,
            "ttft_p50_pct": None,
            "decode_tok_s_p50_pct": None,
            "aggregate_tok_s_pct": None,
            "cost_usd_pct": None,
            "baseline_insufficient_samples": True,
            "variant_insufficient_samples": False,
        }
    ]
    table = _fmt_comparison_table(comparisons, "fp16", "awq")
    assert "insufficient_samples" in table


def test_sustained_comparison_rejects_incompatible_or_incomplete_runs(tmp_path):
    import pytest
    from eval.quantization_compare import compare_sustained_runs
    from eval.serving_load import ArtifactWriter
    baseline = tmp_path / "baseline"
    variant = tmp_path / "variant"
    # Only schema/run identity are needed to prove mismatches fail before comparing numbers.
    for directory in (baseline, variant):
        writer = ArtifactWriter(directory, {"schema_version": 2, "run_id": directory.name,
                                           "target": "replay" if directory == baseline else "api"})
        writer.write({"event": "run_summary", "cells": []})
        writer.write({"event": "run_end", "outcome": "complete"})
        writer.close()
    with pytest.raises(ValueError, match="target"):
        compare_sustained_runs(baseline, variant)
    (variant / "events.jsonl").write_text("")
    with pytest.raises(ValueError, match="complete"):
        compare_sustained_runs(baseline, variant)


def test_sustained_comparison_accepts_matching_recorded_conditions(tmp_path):
    from eval.quantization_compare import compare_sustained_runs
    from eval.serving_load import ArtifactWriter, repeat_summary, summarize
    manifest = {"schema_version": 2, "target": "replay", "workload_sha256": "a", "corpus_sha256": "b",
                "cache_mode": "bust", "token_policy": "provider_only", "duration_s": 60,
                "request_limit": 1000, "timeout_s": 120, "warmup_requests": 4, "repeats": 1,
                "min_samples": 1, "sampling": "default", "concurrency": [1], "arrival_rates": [None],
                "latency_slo_s": None, "source": {"git_commit": "example"},
                "deployment": {"engine": "test", "image_digest": "test", "gpu_name": "test",
                               "gpu_count": 1, "max_model_len": 16384, "compute_dtype": "float16"}}
    for label, seconds in (("base", 2), ("variant", 1)):
        writer = ArtifactWriter(tmp_path / label, {**manifest, "run_id": label})
        summary = summarize([{"status": "ok", "total_s": seconds, "output_tokens": 10}], seconds, min_samples=1)
        writer.write({"event": "run_summary", "cells": repeat_summary([
            {"concurrency": 1, "arrival_rate": None, "summary": summary}])})
        writer.write({"event": "run_end", "outcome": "complete"})
        writer.close()
    result = compare_sustained_runs(tmp_path / "base", tmp_path / "variant")
    assert result["cells"][0]["metrics"]["output_tokens_per_second"]["change_pct"] == 100


# --- optional GPU-utilization column ----------------------------------------------------------

def _matching_runs(tmp_path, variant_target="replay"):
    from eval.serving_load import ArtifactWriter, repeat_summary, summarize
    manifest = {"schema_version": 2, "target": "replay", "workload_sha256": "a", "corpus_sha256": "b",
                "cache_mode": "bust", "token_policy": "provider_only", "duration_s": 60,
                "request_limit": 1000, "timeout_s": 120, "warmup_requests": 4, "repeats": 1,
                "min_samples": 1, "sampling": "default", "concurrency": [1], "arrival_rates": [None],
                "latency_slo_s": None, "source": {"git_commit": "example"},
                "deployment": {"engine": "test", "image_digest": "test", "gpu_name": "test",
                               "gpu_count": 1, "max_model_len": 16384, "compute_dtype": "float16"}}
    for label, seconds in (("base", 2), ("variant", 1)):
        writer = ArtifactWriter(tmp_path / label, {**manifest, "run_id": label,
                                                  "target": variant_target if label == "variant" else "replay"})
        summary = summarize([{"status": "ok", "total_s": seconds, "output_tokens": 10}], seconds, min_samples=1)
        writer.write({"event": "run_summary", "cells": repeat_summary([
            {"concurrency": 1, "arrival_rate": None, "summary": summary}])})
        writer.write({"event": "run_end", "outcome": "complete"})
        writer.close()
    return tmp_path / "base", tmp_path / "variant"


def _gpu_file(directory, run_id, mean_pct=70.0, status="ok"):
    """A minimal gpu-utilization.json fixture (placeholder numbers, not a measurement)."""
    cell = {"concurrency": 1, "arrival_rate": None, "status": status,
            "per_gpu": {"0": {"status": "ok", "n_samples": 30, "mean_pct": mean_pct, "p95_pct": mean_pct + 10,
                              "max_pct": mean_pct + 15}} if status == "ok" else {}}
    if status != "ok":
        cell["reason"] = "sampler file not found"
    (directory / "gpu-utilization.json").write_text(json.dumps({"run_id": run_id, "cells": [cell]}))


def test_comparison_output_is_unchanged_when_no_gpu_file_exists(tmp_path):
    from eval.quantization_compare import compare_sustained_runs
    base, variant = _matching_runs(tmp_path)
    result = compare_sustained_runs(base, variant)
    assert all("gpu_utilization" not in row for row in result["cells"])
    assert len(result["limits"]) == 3 and set(result) == {"baseline_run_id", "variant_run_id", "cells", "limits"}


def test_gpu_utilization_is_an_extra_column_that_leaves_every_other_value_alone(tmp_path):
    from eval.quantization_compare import compare_sustained_runs
    base, variant = _matching_runs(tmp_path)
    before = compare_sustained_runs(base, variant)
    _gpu_file(base, "base", 70.0)
    _gpu_file(variant, "variant", 55.0)
    after = compare_sustained_runs(base, variant)
    column = after["cells"][0]["gpu_utilization"]
    assert column["baseline"]["per_gpu"]["0"]["mean_pct"] == 70.0
    assert column["variant"]["per_gpu"]["0"]["mean_pct"] == 55.0
    assert after["cells"][0]["metrics"] == before["cells"][0]["metrics"]       # nothing else moved
    assert [r["concurrency"] for r in after["cells"]] == [r["concurrency"] for r in before["cells"]]
    assert any("not part of comparability checks" in limit for limit in after["limits"])


def test_a_gpu_file_on_one_side_marks_the_other_unavailable_with_a_reason(tmp_path):
    from eval.quantization_compare import compare_sustained_runs
    base, variant = _matching_runs(tmp_path)
    _gpu_file(base, "base")
    column = compare_sustained_runs(base, variant)["cells"][0]["gpu_utilization"]
    assert column["baseline"]["status"] == "ok"
    assert column["variant"] == {"status": "unavailable", "reason": "no gpu-utilization.json attached to this run"}


def test_unavailable_gpu_data_never_changes_which_runs_are_comparable(tmp_path):
    import pytest
    from eval.quantization_compare import compare_sustained_runs
    base, variant = _matching_runs(tmp_path)
    plain = compare_sustained_runs(base, variant)
    _gpu_file(base, "base", status="unavailable")
    _gpu_file(variant, "variant", mean_pct=12.0)                              # very different GPU data
    compared = compare_sustained_runs(base, variant)                          # still comparable, same metrics
    assert compared["cells"][0]["metrics"] == plain["cells"][0]["metrics"]
    assert compared["cells"][0]["gpu_utilization"]["baseline"]["status"] == "unavailable"
    # and GPU files cannot rescue runs the existing checks reject
    other = tmp_path / "other"
    other.mkdir()
    b2, v2 = _matching_runs(other, variant_target="api")
    _gpu_file(b2, "base")
    _gpu_file(v2, "variant")
    with pytest.raises(ValueError, match="target"):
        compare_sustained_runs(b2, v2)


def test_foreign_or_unreadable_gpu_files_are_reported_not_raised(tmp_path):
    from eval.quantization_compare import compare_sustained_runs
    base, variant = _matching_runs(tmp_path)
    _gpu_file(base, "some-other-run")
    (variant / "gpu-utilization.json").write_text("{not json")
    column = compare_sustained_runs(base, variant)["cells"][0]["gpu_utilization"]
    assert "different run" in column["baseline"]["reason"]
    assert "unreadable" in column["variant"]["reason"]


def test_quantization_compare_still_has_no_heavy_imports_at_module_load():
    import ast
    from pathlib import Path
    import eval.quantization_compare as module
    tree = ast.parse(Path(module.__file__).read_text())
    top_level = {n.module for n in tree.body if isinstance(n, ast.ImportFrom)} | \
                {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    assert not any(name and name.startswith(("eval.", "app.")) for name in top_level)
