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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=Path("data/inference_benchmark.jsonl"))
    parser.add_argument("--baseline-since", required=True)
    parser.add_argument("--baseline-until", required=True)
    parser.add_argument("--variant-since", required=True)
    parser.add_argument("--variant-until", required=True)
    parser.add_argument("--baseline-label", default="fp16")
    parser.add_argument("--variant-label", default="awq")
    args = parser.parse_args()

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
