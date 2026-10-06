"""Estimate per-GPU serving capacity and cost from repeated load-test artifacts."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def _read_run(directory: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((directory / "manifest.json").read_text())
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines() if line]
    ended = [row for row in events if row.get("event") == "run_end"]
    if not ended or ended[-1].get("outcome") != "complete":
        raise ValueError(f"{directory}: load run is incomplete")
    return manifest, events


def estimate_capacity(directories: list[Path], *, latency_slo_s: float | None,
                      max_error_rate: float, headroom: float, target_rps: float | None,
                      hourly_cost_override: float | None = None) -> dict:
    models = []
    workload_hash = None
    for directory in directories:
        manifest, events = _read_run(directory)
        current_hash = manifest.get("workload_sha256")
        if workload_hash is None:
            workload_hash = current_hash
        elif current_hash != workload_hash:
            raise ValueError("Runs use different workload fingerprints")
        if manifest.get("target") != "replay" or manifest.get("provider") != "local":
            raise ValueError(f"{directory}: capacity estimates require local inference replay")
        deployment = manifest.get("deployment") or {}
        model = deployment.get("model_repository") or manifest.get("model") or directory.name
        hourly_cost = deployment.get("hourly_cost_usd") or hourly_cost_override
        cells: dict[int, list[dict]] = defaultdict(list)
        for row in events:
            if row.get("event") != "cell_summary" or row.get("phase") != "measurement":
                continue
            cells[int(row["concurrency"])].append(row["summary"])
        if not cells:
            raise ValueError(f"{directory}: no measurement cells found")
        levels = []
        for concurrency, repeats in sorted(cells.items()):
            if len(repeats) < 2:
                raise ValueError(f"{directory} concurrency {concurrency}: at least two repeats are required")
            rates = [r["successful_requests_per_second"] for r in repeats
                     if r.get("successful_requests_per_second") is not None]
            p95s = [r["latency_p95_s"] for r in repeats if r.get("latency_p95_s") is not None]
            errors = [r["error_rate"] for r in repeats if r.get("error_rate") is not None]
            token_rates = [r["output_tokens_per_second"] for r in repeats
                           if r.get("output_tokens_per_second") is not None]
            if len(rates) != len(repeats) or len(p95s) != len(repeats) or len(errors) != len(repeats):
                raise ValueError(f"{directory} concurrency {concurrency}: missing repeated-cell metrics")
            conservative_rps = min(rates) * headroom
            p99s = [r.get("latency_p99_s") for r in repeats]
            ttft_p99s = [r.get("ttft_p99_s") for r in repeats]
            level = {"concurrency": concurrency, "repeats": len(repeats),
                     "requests_per_second_each": rates,
                     "requests_per_second_mean": sum(rates) / len(rates),
                     "requests_per_second_conservative": conservative_rps,
                     "latency_p95_s_each": p95s, "latency_p95_s_worst": max(p95s),
                     "error_rate_worst": max(errors),
                     # Descriptive only (never gates the SLO): null unless every repeat reached the p99 sample floor.
                     "latency_p99_s_each": p99s,
                     "latency_p99_s_worst": max(p99s) if all(v is not None for v in p99s) else None,
                     "ttft_p99_s_worst": max(ttft_p99s) if all(v is not None for v in ttft_p99s) else None,
                     "p99_repeats_available": sum(v is not None for v in p99s),
                     "output_tokens_per_second_mean": (sum(token_rates) / len(token_rates)
                                                        if len(token_rates) == len(repeats) else None)}
            level["meets_slo"] = (level["error_rate_worst"] <= max_error_rate and
                                  (latency_slo_s is None or level["latency_p95_s_worst"] <= latency_slo_s))
            levels.append(level)
        candidates = [level for level in levels if level["meets_slo"]]
        best = max(candidates, key=lambda row: row["requests_per_second_conservative"], default=None)
        model_result = {"model": model, "hourly_cost_per_gpu_usd": hourly_cost,
                        "levels": levels, "selected_level": best}
        if best and hourly_cost is not None:
            rps = best["requests_per_second_conservative"]
            model_result["cost_per_request_usd"] = hourly_cost / (rps * 3600)
            model_result["cost_per_million_requests_usd"] = hourly_cost / (rps * 3600) * 1_000_000
            token_rate = best["output_tokens_per_second_mean"]
            model_result["cost_per_1k_output_tokens_usd"] = (
                hourly_cost / (token_rate * 3600) * 1000 if token_rate else None
            )
            model_result["cost_per_million_output_tokens_usd"] = (
                hourly_cost / (token_rate * 3600) * 1_000_000 if token_rate else None
            )
            if target_rps is not None:
                model_result["gpu_count_for_target"] = math.ceil(target_rps / rps)
                model_result["estimated_gpu_hourly_cost_usd"] = model_result["gpu_count_for_target"] * hourly_cost
        models.append(model_result)
    return {"schema_version": 1, "workload_sha256": workload_hash,
            "assumptions": {"latency_slo_s": latency_slo_s, "max_error_rate": max_error_rate,
                            "headroom": headroom,
                            "conservative_capacity": "minimum observed repeat throughput × headroom",
                            "cost_basis": ("GPU rental only, from hourly_cost_usd; request cost uses the conservative "
                                           "requests/s of the selected level, token cost the mean token rate; excludes "
                                           "storage, egress and idle time"),
                            "p99": "descriptive; needs at least 100 successes per cell; never used for SLO gating",
                            "gpu_scaling": "linear extrapolation; validate multi-GPU/pod interference separately"},
            "models": models}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="Run directories with manifest.json and events.jsonl")
    parser.add_argument("--latency-slo", type=float)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--headroom", type=float, default=0.70)
    parser.add_argument("--target-rps", type=float)
    parser.add_argument("--hourly-cost", type=float,
                        help="Per-GPU USD/hour if the run manifest omits a recorded price")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 <= args.max_error_rate < 1 or not 0 < args.headroom <= 1:
        parser.error("--max-error-rate must be in [0,1); --headroom must be in (0,1]")
    if args.latency_slo is not None and args.latency_slo <= 0:
        parser.error("--latency-slo must be positive")
    if args.target_rps is not None and args.target_rps <= 0:
        parser.error("--target-rps must be positive")
    if args.hourly_cost is not None and args.hourly_cost <= 0:
        parser.error("--hourly-cost must be positive")
    report = estimate_capacity(args.runs, latency_slo_s=args.latency_slo,
                               max_error_rate=args.max_error_rate, headroom=args.headroom,
                               target_rps=args.target_rps, hourly_cost_override=args.hourly_cost)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
