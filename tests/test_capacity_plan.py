import json

import pytest

from eval.capacity_plan import estimate_capacity


def test_capacity_uses_worst_repeat_headroom_and_reports_gpu_cost(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({
        "target": "replay", "provider": "local", "workload_sha256": "same",
        "deployment": {"model_repository": "Qwen/test", "hourly_cost_usd": 1.09},
    }))
    rows = [
        {"event": "cell_summary", "phase": "measurement", "concurrency": 4,
         "summary": {"successful_requests_per_second": 10, "latency_p95_s": 1.0,
                     "error_rate": 0.0, "output_tokens_per_second": 1000}},
        {"event": "cell_summary", "phase": "measurement", "concurrency": 4,
         "summary": {"successful_requests_per_second": 9, "latency_p95_s": 1.2,
                     "error_rate": 0.01, "output_tokens_per_second": 900}},
        {"event": "run_end", "outcome": "complete"},
    ]
    (run / "events.jsonl").write_text("\n".join(json.dumps(row) for row in rows))

    report = estimate_capacity([run], latency_slo_s=2, max_error_rate=0.01,
                               headroom=0.7, target_rps=20)
    result = report["models"][0]
    assert result["selected_level"]["requests_per_second_conservative"] == pytest.approx(6.3)
    assert result["gpu_count_for_target"] == 4
    assert result["estimated_gpu_hourly_cost_usd"] == pytest.approx(4.36)


def test_capacity_rejects_mismatched_workload_fingerprints(tmp_path):
    runs = []
    for index, fingerprint in enumerate(("first", "second")):
        run = tmp_path / str(index)
        run.mkdir()
        (run / "manifest.json").write_text(json.dumps({
            "target": "replay", "provider": "local", "workload_sha256": fingerprint,
        }))
        cells = [{"event": "cell_summary", "phase": "measurement", "concurrency": 1,
                  "summary": {"successful_requests_per_second": 1, "latency_p95_s": 1,
                              "error_rate": 0, "output_tokens_per_second": 1}}
                 for _ in range(2)]
        (run / "events.jsonl").write_text("\n".join(json.dumps(row) for row in [
            *cells, {"event": "run_end", "outcome": "complete"}
        ]))
        runs.append(run)

    with pytest.raises(ValueError, match="different workload"):
        estimate_capacity(runs, latency_slo_s=None, max_error_rate=0.01,
                          headroom=0.7, target_rps=None)


def test_capacity_is_unchanged_by_an_attached_gpu_utilization_file_and_by_cell_windows(tmp_path):
    def build(directory, with_window):
        directory.mkdir()
        (directory / "manifest.json").write_text(json.dumps({
            "target": "replay", "provider": "local", "workload_sha256": "same",
            "deployment": {"model_repository": "Qwen/test", "hourly_cost_usd": 1.09}}))
        window = {"window": {"started_at": "2026-10-06T12:00:00+00:00", "ended_at": "2026-10-06T12:01:00+00:00",
                             "clock": "benchmark_client_wall_clock_utc"}} if with_window else {}
        cells = [{"event": "cell_summary", "phase": "measurement", "concurrency": 4, **window,
                  "summary": {"successful_requests_per_second": rps, "latency_p95_s": 1.0, "error_rate": 0.0,
                              "output_tokens_per_second": 1000}} for rps in (10, 9)]
        (directory / "events.jsonl").write_text("\n".join(json.dumps(row) for row in [
            *cells, {"event": "run_end", "outcome": "complete"}]))
    plain, enriched = tmp_path / "plain", tmp_path / "enriched"
    build(plain, with_window=False)
    build(enriched, with_window=True)
    (enriched / "gpu-utilization.json").write_text(json.dumps({"run_id": "x", "cells": []}))
    options = {"latency_slo_s": 2, "max_error_rate": 0.01, "headroom": 0.7, "target_rps": 20}
    assert estimate_capacity([enriched], **options) == estimate_capacity([plain], **options)


def _capacity_run(tmp_path, cells, manifest_extra=None):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({
        "target": "replay", "provider": "local", "workload_sha256": "same",
        "deployment": {"model_repository": "Qwen/test", "hourly_cost_usd": 1.09}, **(manifest_extra or {})}))
    (run / "events.jsonl").write_text("\n".join(json.dumps(row) for row in [
        *[{"event": "cell_summary", "phase": "measurement", "concurrency": 4, "summary": cell} for cell in cells],
        {"event": "run_end", "outcome": "complete"}]))
    return run


def _cell(rps=10, **extra):
    return {"successful_requests_per_second": rps, "latency_p95_s": 1.0, "error_rate": 0.0,
            "output_tokens_per_second": 1000, **extra}


OPTIONS = {"latency_slo_s": 2, "max_error_rate": 0.01, "headroom": 0.7, "target_rps": None}


def test_capacity_reports_the_worst_repeat_p99_and_never_gates_the_slo_on_it(tmp_path):
    run = _capacity_run(tmp_path, [_cell(10, latency_p99_s=1.5, ttft_p99_s=0.4),
                                   _cell(9, latency_p99_s=3.0, ttft_p99_s=0.6)])
    level = estimate_capacity([run], **OPTIONS)["models"][0]["levels"][0]
    assert level["latency_p99_s_worst"] == 3.0 and level["ttft_p99_s_worst"] == 0.6
    assert level["latency_p99_s_each"] == [1.5, 3.0] and level["p99_repeats_available"] == 2
    assert level["meets_slo"] is True                    # a 3.0 s p99 above the 2 s SLO does not fail the level


def test_capacity_p99_is_null_when_any_repeat_lacks_it_and_old_runs_still_load(tmp_path):
    partial = _capacity_run(tmp_path, [_cell(10, latency_p99_s=1.5, ttft_p99_s=0.4), _cell(9, latency_p99_s=None)])
    level = estimate_capacity([partial], **OPTIONS)["models"][0]["levels"][0]
    assert level["latency_p99_s_worst"] is None and level["p99_repeats_available"] == 1
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    old = _capacity_run(old_dir, [_cell(10), _cell(9)])                  # cells predate p99 entirely
    level = estimate_capacity([old], **OPTIONS)["models"][0]["levels"][0]
    assert level["latency_p99_s_worst"] is None and level["p99_repeats_available"] == 0


# --- cost per request and per 1K output tokens ----------------------------------------------------

def test_capacity_reports_cost_per_request_and_per_1k_output_tokens(tmp_path):
    cells = [_cell(10, output_tokens_per_second=1000), _cell(9, output_tokens_per_second=900)]
    model = estimate_capacity([_capacity_run(tmp_path, cells)], **OPTIONS)["models"][0]
    conservative_rps = 9 * 0.7                                           # worst repeat times headroom
    assert model["cost_per_request_usd"] == pytest.approx(1.09 / (conservative_rps * 3600))
    assert model["cost_per_1k_output_tokens_usd"] == pytest.approx(1.09 / (950 * 3600) * 1000)   # mean token rate
    assert model["cost_per_million_requests_usd"] == pytest.approx(model["cost_per_request_usd"] * 1_000_000)


def test_cost_fields_are_skipped_when_no_cost_is_known(tmp_path):
    run = _capacity_run(tmp_path, [_cell(10), _cell(9)])
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["deployment"].pop("hourly_cost_usd")
    (run / "manifest.json").write_text(json.dumps(manifest))
    model = estimate_capacity([run], **OPTIONS)["models"][0]
    assert model["hourly_cost_per_gpu_usd"] is None
    assert not {"cost_per_request_usd", "cost_per_1k_output_tokens_usd", "cost_per_million_requests_usd"} & set(model)


def test_cost_per_1k_tokens_is_null_when_token_usage_is_unknown_but_request_cost_remains(tmp_path):
    cells = [_cell(10, output_tokens_per_second=None), _cell(9, output_tokens_per_second=None)]
    model = estimate_capacity([_capacity_run(tmp_path, cells)], **OPTIONS)["models"][0]
    assert model["cost_per_request_usd"] > 0 and model["cost_per_1k_output_tokens_usd"] is None


def test_an_explicit_hourly_cost_override_feeds_the_new_fields_and_the_basis_is_stated(tmp_path):
    run = _capacity_run(tmp_path, [_cell(10), _cell(9)])
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["deployment"].pop("hourly_cost_usd")
    (run / "manifest.json").write_text(json.dumps(manifest))
    report = estimate_capacity([run], hourly_cost_override=2.0, **OPTIONS)
    assert report["models"][0]["cost_per_request_usd"] == pytest.approx(2.0 / (9 * 0.7 * 3600))
    assert "GPU rental only" in report["assumptions"]["cost_basis"]
