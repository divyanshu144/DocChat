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
