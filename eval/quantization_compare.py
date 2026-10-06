#!/usr/bin/env python3
"""Phase 3 — quantization comparison report.

Compares two or three servings of the same model (FP16 baseline, AWQ, GPTQ if
present) on both speed and cost, using rows already written by
eval/inference_benchmark.py to data/inference_benchmark.jsonl. This script
does not run any sweep itself and makes no network calls -- it only reads
JSONL and prints a comparison table. The critic quality side (precision/
recall/F1 per serving, from eval/benchmark.py) is reported separately; see
docs/superpowers/specs/2026-10-01-quantization-comparison-design.md.

Usage (once real sweep data exists for each serving):
    python eval/quantization_compare.py --jsonl data/inference_benchmark.jsonl \\
        --baseline-since 2026-10-02T00:00:00 --baseline-until 2026-10-02T01:00:00 \\
        --variant-since 2026-10-02T01:00:00 --variant-until 2026-10-02T02:00:00 \\
        --baseline-label fp16 --variant-label awq

A run is identified by a timestamp window, not guessed from provider name
alone -- the same provider ("local") writes every serving's rows to the same
file, so the only reliable way to separate them is by when each serving ran.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path



def _load_summary_rows(
    jsonl_path: Path,
    since: str,
    until: str,
    provider: str = "local",
) -> list[dict]:
    """Return the rows from `jsonl_path` whose provider matches and whose
    timestamp falls in [since, until) -- the window identifying one serving's
    sweep, since multiple servings of the same provider land in the same
    append-only file."""
    rows = []
    since_dt = datetime.fromisoformat(since)
    until_dt = datetime.fromisoformat(until)
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("provider") != provider:
                continue
            ts = datetime.fromisoformat(row["timestamp"])
            if since_dt <= ts < until_dt:
                rows.append(row)
    return rows


def _compare_rows(baseline: dict, variant: dict) -> dict:
    """Percentage change (variant vs baseline) for the fields that matter for
    a quantization comparison. `None` for any field either side could not
    compute (insufficient_samples) -- never a delta from missing data, which
    would look like a real measurement but isn't one."""
    b = baseline["summary"]
    v = variant["summary"]

    def _pct_change(field: str) -> float | None:
        b_val = b.get(field)
        v_val = v.get(field)
        if b_val is None or v_val is None or b_val == 0:
            return None
        return (v_val - b_val) / b_val * 100

    cost_pct = None
    if baseline.get("cost_usd") is not None and variant.get("cost_usd") is not None:
        if baseline["cost_usd"] != 0:
            cost_pct = (variant["cost_usd"] - baseline["cost_usd"]) / baseline["cost_usd"] * 100

    return {
        "concurrency": baseline["concurrency"],
        "ttft_p50_pct": _pct_change("ttft_p50"),
        "decode_tok_s_p50_pct": _pct_change("decode_tok_s_p50"),
        "aggregate_tok_s_pct": _pct_change("aggregate_tok_s"),
        "cost_usd_pct": cost_pct,
        "baseline_insufficient_samples": b.get("insufficient_samples", False),
        "variant_insufficient_samples": v.get("insufficient_samples", False),
    }


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "   n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _fmt_comparison_table(
    comparisons: list[dict], baseline_label: str, variant_label: str
) -> str:
    lines = [f"{baseline_label} -> {variant_label}", "-" * 60]
    header = f"{'concurrency':>11}  {'ttft_p50':>10}  {'decode_tok_s':>13}  {'agg_tok_s':>10}  {'cost':>8}"
    lines.append(header)
    for c in comparisons:
        flag = ""
        if c["baseline_insufficient_samples"] or c["variant_insufficient_samples"]:
            flag = "  [insufficient_samples on one side]"
        lines.append(
            f"{c['concurrency']:>11}  {_fmt_pct(c['ttft_p50_pct']):>10}  "
            f"{_fmt_pct(c['decode_tok_s_p50_pct']):>13}  "
            f"{_fmt_pct(c['aggregate_tok_s_pct']):>10}  "
            f"{_fmt_pct(c['cost_usd_pct']):>8}{flag}"
        )
    return "\n".join(lines)


def compare_sustained_runs(baseline_dir: Path, variant_dir: Path) -> dict:
    """Compare schema-v2 runs only when recorded workload/load conditions agree."""
    def load(directory):
        manifest = json.loads((directory / "manifest.json").read_text())
        events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines() if line]
        if (manifest.get("schema_version") != 2 or not events or events[-1].get("event") != "run_end"
                or events[-1].get("outcome") != "complete"):
            raise ValueError("Comparison requires complete schema-v2 runs")
        if any(event.get("run_id") != manifest["run_id"] for event in events):
            raise ValueError("Artifact run IDs do not match")
        report = next((e for e in reversed(events) if e.get("event") == "run_summary"), None)
        if not report:
            raise ValueError("Run summary missing")
        return manifest, report["cells"]

    baseline, b_cells = load(baseline_dir)
    variant, v_cells = load(variant_dir)
    for key in ("target", "workload_sha256", "corpus_sha256", "cache_mode", "token_policy", "duration_s",
                "request_limit", "timeout_s", "warmup_requests", "repeats", "min_samples", "sampling",
                "concurrency", "arrival_rates", "latency_slo_s", "source"):
        if key not in baseline or key not in variant or baseline[key] != variant[key]:
            raise ValueError(f"Incompatible benchmark field: {key}")
    # Quantization/model checkpoint may differ; the remaining serving conditions must not.
    for key in ("engine", "image_digest", "gpu_name", "gpu_count", "max_model_len", "compute_dtype"):
        a, b = baseline.get("deployment", {}).get(key), variant.get("deployment", {}).get(key)
        if a is None or b is None or a != b:
            raise ValueError(f"Missing or incompatible deployment field: {key}")
    if baseline["target"] == "api":
        for key in ("application_revision", "application_config_sha256"):
            a, b = baseline["deployment"].get(key), variant["deployment"].get(key)
            if a is None or b is None or a != b:
                raise ValueError(f"Missing or incompatible application field: {key}")
    def index(cells):
        if any(cell["repeats"] != baseline["repeats"] for cell in cells):
            raise ValueError("Incomplete repeated cells")
        indexed = {(cell["concurrency"], cell["arrival_rate"]): cell for cell in cells}
        expected = {(c, r) for c in baseline["concurrency"] for r in baseline["arrival_rates"]}
        if len(indexed) != len(cells) or indexed.keys() != expected:
            raise ValueError("Incomplete or duplicate load levels")
        return indexed
    left, right = index(b_cells), index(v_cells)
    if not left or left.keys() != right.keys():
        raise ValueError("Run cells differ")
    rows = []
    for key in left:
        a, b = left[key], right[key]
        changes = {}
        for name, values in a["statistics"].items():
            old = values["mean"]
            new = b["statistics"][name]["mean"]
            changes[name] = {"baseline": values, "variant": b["statistics"][name],
                             "change_pct": ((new - old) / old * 100
                                            if old not in (None, 0) and new is not None else None)}
        rows.append({"concurrency": key[0], "arrival_rate": key[1], "metrics": changes})
    result = {"baseline_run_id": baseline["run_id"], "variant_run_id": variant["run_id"], "cells": rows,
              "limits": ["Recorded metadata compatibility does not verify the same physical host or network",
                         "Success percentiles exclude errors; inspect error-rate changes",
                         "Speed-only report; no answer-quality or causal quantization claim"]}
    _add_gpu_utilization(result, (baseline_dir, baseline["run_id"]), (variant_dir, variant["run_id"]))
    return result


def _gpu_side(directory: Path, run_id: str):
    """(per-load GPU summaries, reason). A missing, foreign or unreadable file never raises or changes comparability."""
    from eval.gpu_utilization import load_gpu_utilization, summarize_by_load  # lazy: keeps this CLI light

    try:
        report = load_gpu_utilization(directory)
    except (OSError, ValueError):
        return None, "gpu-utilization.json is unreadable"
    if report is None:
        return None, "no gpu-utilization.json attached to this run"
    if report.get("run_id") != run_id:
        return None, "gpu-utilization.json belongs to a different run"
    try:
        return summarize_by_load(report), None
    except (KeyError, TypeError, ValueError):
        return None, "gpu-utilization.json is malformed"


def _add_gpu_utilization(result: dict, baseline: tuple, variant: tuple) -> None:
    """Add an informational `gpu_utilization` column per cell, only when at least one run has the file.

    It runs after every comparability check and is never read by one; with no file on either side the output is
    exactly what it was before this column existed.
    """
    sides = {"baseline": _gpu_side(*baseline), "variant": _gpu_side(*variant)}
    if all(summary is None and reason == "no gpu-utilization.json attached to this run"
           for summary, reason in sides.values()):
        return
    for row in result["cells"]:
        key = (row["concurrency"], row["arrival_rate"])
        column = {}
        for name, (summary, reason) in sides.items():
            if summary is None:
                column[name] = {"status": "unavailable", "reason": reason}
            else:
                column[name] = summary.get(key) or {"status": "unavailable",
                                                    "reason": "no GPU data for this load level"}
        row["gpu_utilization"] = column
    result["limits"].append("GPU utilization is informational and not part of comparability checks; it shows the "
                            "GPU was busy, not that it was efficient")


CACHE_OFF_HIT_RATE_WARN = 0.01   # a caching-off arm above this is suspicious
BUST_HIT_RATE_WARN = 0.05        # with cache busting on, hits above this suggest busting is not reaching the server


def _cell_prefix_cache(directory: Path) -> dict:
    """Pooled prefix-cache hit rate per (concurrency, arrival_rate), from the run's engine_counter_changes events.

    Pooled means total hits over total queries across repeats (weighted by traffic), never a mean of per-repeat rates.
    A cell with no usable summary is reported unavailable with a reason; nothing is filled in.
    """
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines() if line]
    cells = {e["cell_id"]: (e["concurrency"], e["arrival_rate"]) for e in events
             if e.get("event") == "cell_summary" and e.get("phase") == "measurement"}
    recorded = defaultdict(list)
    for event in events:
        if event.get("event") == "engine_counter_changes" and event.get("cell_id") in cells:
            recorded[cells[event["cell_id"]]].append(event.get("prefix_cache"))
    out = {}
    for key in set(cells.values()):
        summaries = recorded.get(key)
        if not summaries:
            out[key] = {"status": "unavailable", "reason": "no engine metrics recorded for this cell (no --metrics-url)"}
            continue
        usable = [item for item in summaries if item and item.get("status") == "ok"]
        entry = {"repeats": len(summaries), "repeats_with_data": len(usable)}
        if not usable:
            reasons = sorted({item["reason"] for item in summaries if item and item.get("reason")})
            entry.update(status="unavailable", reason="; ".join(reasons) or
                         "no prefix_cache summary recorded (the run predates it)")
        else:
            queries, hits = sum(item["queries"] for item in usable), sum(item["hits"] for item in usable)
            entry.update(status="ok" if len(usable) == len(summaries) else "partial", queries=queries, hits=hits,
                         hit_rate=hits / queries, unit="tokens")
        out[key] = entry
    return out


def compare_prefix_caching(baseline_dir: Path, variant_dir: Path) -> dict:
    """Prefix caching on (baseline) versus off (variant), only for runs the existing checks accept.

    Runs compare_sustained_runs first (so every existing comparability rule applies), then requires the same model and
    quantization and an explicit prefix_caching true/false pair. Adds a per-cell hit-rate column for each arm.
    """
    result = compare_sustained_runs(baseline_dir, variant_dir)
    manifests = [json.loads((directory / "manifest.json").read_text()) for directory in (baseline_dir, variant_dir)]
    on, off = (manifest.get("deployment") or {} for manifest in manifests)
    if on.get("prefix_caching") is not True or off.get("prefix_caching") is not False:
        raise ValueError("Prefix-cache comparison requires deployment prefix_caching=true (baseline) and "
                         "prefix_caching=false (variant)")
    if on.get("model_repository") is None or on.get("model_repository") != off.get("model_repository"):
        raise ValueError("Prefix-cache comparison requires the same non-null model_repository in both runs")
    if on.get("weight_quantization") != off.get("weight_quantization"):
        raise ValueError("Prefix-cache comparison requires the same weight_quantization in both runs")
    for key in ("model_revision", "tokenizer_revision"):
        if on.get(key) is not None and off.get(key) is not None and on[key] != off[key]:
            raise ValueError(f"Prefix-cache comparison requires the same {key} in both runs")
    cache_mode = manifests[0]["cache_mode"]
    arms = (_cell_prefix_cache(baseline_dir), _cell_prefix_cache(variant_dir))
    missing = {"status": "unavailable", "reason": "no data for this load level"}
    warnings = []
    for row in result["cells"]:
        key = (row["concurrency"], row["arrival_rate"])
        row["prefix_cache"] = {"baseline": arms[0].get(key, missing), "variant": arms[1].get(key, missing)}
        base_rate, off_rate = (row["prefix_cache"][arm].get("hit_rate") for arm in ("baseline", "variant"))
        label = f"concurrency {row['concurrency']}"
        if off_rate is not None and off_rate > CACHE_OFF_HIT_RATE_WARN:
            warnings.append(f"{label}: the caching-off arm shows a {off_rate:.1%} hit rate; caching may not have been disabled")
        if cache_mode == "reuse" and base_rate is not None and base_rate == 0:
            warnings.append(f"{label}: the caching-on arm shows no hits under cache_mode reuse; reuse may not be reaching the server")
        if cache_mode == "bust" and base_rate is not None and base_rate > BUST_HIT_RATE_WARN:
            warnings.append(f"{label}: {base_rate:.1%} hits despite cache busting; busting may not be reaching the server")
    note = ("cache_mode=bust gives every request a unique prefix, so both arms should show about 0% hits; this "
            "comparison is then a control, not a measurement of the caching effect" if cache_mode == "bust" else
            "cache_mode=reuse preserves prompt prefixes; the caching-on arm shows observed reuse. With caching off the "
            "engine may report no prefix-cache queries at all, which is shown as unavailable and not as 0%")
    result["design"] = {"baseline": "prefix caching on", "variant": "prefix caching off", "cache_mode": cache_mode,
                        "note": note}
    result["warnings"] = warnings
    result["limits"].append("Prefix-cache comparison: one run per arm, no causal claim; hit rate is in tokens from the "
                            "engine's counters; the same physical host is not verified")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=Path("data/inference_benchmark.jsonl"))
    parser.add_argument("--baseline-since")
    parser.add_argument("--baseline-until")
    parser.add_argument("--variant-since")
    parser.add_argument("--variant-until")
    parser.add_argument("--baseline-label", default="fp16")
    parser.add_argument("--variant-label", default="awq")
    parser.add_argument("--baseline-run", type=Path, help="Schema-v2 artifact directory")
    parser.add_argument("--variant-run", type=Path, help="Schema-v2 artifact directory")
    parser.add_argument("--prefix-cache-comparison", action="store_true",
                        help="baseline run has prefix caching on, variant off; adds a per-cell hit-rate column")
    args = parser.parse_args()
    if args.prefix_cache_comparison:
        if not args.baseline_run or not args.variant_run:
            parser.error("--prefix-cache-comparison requires --baseline-run and --variant-run")
        print(json.dumps(compare_prefix_caching(args.baseline_run, args.variant_run), indent=2))
        return
    if args.baseline_run or args.variant_run:
        if not args.baseline_run or not args.variant_run:
            parser.error("Both --baseline-run and --variant-run are required")
        if any((args.baseline_since, args.baseline_until, args.variant_since, args.variant_until)):
            parser.error("Do not mix legacy timestamp windows and schema-v2 directories")
        print(json.dumps(compare_sustained_runs(args.baseline_run, args.variant_run), indent=2))
        return
    if not all((args.baseline_since, args.baseline_until, args.variant_since, args.variant_until)):
        parser.error("Legacy comparisons require all four timestamp-window arguments")

    baseline_rows = _load_summary_rows(args.jsonl, args.baseline_since, args.baseline_until)
    variant_rows = _load_summary_rows(args.jsonl, args.variant_since, args.variant_until)

    baseline_by_concurrency = {r["concurrency"]: r for r in baseline_rows}
    variant_by_concurrency = {r["concurrency"]: r for r in variant_rows}
    shared = sorted(set(baseline_by_concurrency) & set(variant_by_concurrency))

    if not shared:
        print("No matching concurrency levels between baseline and variant windows.")
        return

    comparisons = [
        _compare_rows(baseline_by_concurrency[c], variant_by_concurrency[c]) for c in shared
    ]
    print(_fmt_comparison_table(comparisons, args.baseline_label, args.variant_label))
    print(
        "\nThis table is speed/cost only. See "
        "docs/superpowers/specs/2026-10-01-quantization-comparison-design.md for how "
        "the critic quality regression (precision/recall/F1 per serving) is reported "
        "separately, from eval/benchmark.py, not from this script."
    )


if __name__ == "__main__":
    main()
