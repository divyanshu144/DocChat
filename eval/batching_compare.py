"""Fixed-batch serial versus concurrent comparison for the legacy burst harness (the Phase 4 batching proof).

The harness already runs a fixed batch of N requests either strictly one at a time (`--serial`) or all at once, and
tags each row with `mode`. This compares the two for each shared N: the wall-time speedup (serial wall divided by
concurrent wall) and the throughput ratio. It is a ratio of two single runs, not a per-request latency comparison.

    python -m eval.batching_compare --jsonl data/inference_benchmark.jsonl --since T0 --until T1 --provider local
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.quantization_compare import _load_summary_rows

OUTPUT_LENGTH_TOLERANCE = 0.10   # serial/concurrent total output tokens differing by more than this mixes in length
LIMITS = ["One run per mode and batch size; the ratio carries run-to-run variation that is not measured here",
          "Wall-time speedup compares fixed batches of N requests; it says nothing about per-request latency",
          "Provider-default sampling: output lengths differ between runs, which the caveat flags when material",
          "The same physical host and network for both runs is not verified by this tool"]


def _pair(batch_size, serial, concurrent):
    s, c = serial["summary"], concurrent["summary"]
    entry = {"batch_size": batch_size, "n_requests": s.get("n_total"), "serial_wall_s": s.get("wall_time_s"),
             "concurrent_wall_s": c.get("wall_time_s"), "comparable": False, "reason": None,
             "wall_time_speedup": None, "throughput_ratio": None,
             "output_tokens_serial": s.get("total_output_tokens"), "output_tokens_concurrent": c.get("total_output_tokens")}
    if s.get("n_total") != c.get("n_total"):
        entry["reason"] = "the two runs used different numbers of requests"
    elif s.get("n_ok") != s.get("n_total") or c.get("n_ok") != c.get("n_total"):
        entry["reason"] = "failed requests in one or both runs; ratios would compare unequal work"
    elif not (s.get("wall_time_s") or 0) > 0 or not (c.get("wall_time_s") or 0) > 0:
        entry["reason"] = "a run has no positive wall time"
    else:
        entry.update(comparable=True, wall_time_speedup=s["wall_time_s"] / c["wall_time_s"])
        if s.get("aggregate_tok_s") and c.get("aggregate_tok_s"):
            entry["throughput_ratio"] = c["aggregate_tok_s"] / s["aggregate_tok_s"]
        tokens_s, tokens_c = s.get("total_output_tokens"), c.get("total_output_tokens")
        entry["output_length_differs"] = bool(tokens_s and tokens_c and
                                              abs(tokens_s - tokens_c) / max(tokens_s, tokens_c) > OUTPUT_LENGTH_TOLERANCE)
        if entry["output_length_differs"]:
            entry["caveat"] = ("total output length differs between the runs by more than "
                               f"{OUTPUT_LENGTH_TOLERANCE:.0%}, so the ratio mixes batching with output length")
    return entry


def compare_batching(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("no rows to compare")
    if len({row.get("provider") for row in rows}) != 1:
        raise ValueError("rows must come from one provider")
    indexed = {}
    for row in rows:
        key = (row["concurrency"], row.get("mode", "concurrent"))       # old rows have no mode: they were concurrent
        if key in indexed:
            raise ValueError(f"multiple rows for concurrency {key[0]} mode {key[1]}; narrow the time window")
        indexed[key] = row
    sizes = {n for n, _ in indexed}
    shared = sorted(n for n in sizes if (n, "serial") in indexed and (n, "concurrent") in indexed and n > 1)
    skipped = {}
    if {1} & sizes and (1, "serial") in indexed and (1, "concurrent") in indexed:
        skipped["batch_size_1"] = "serial and concurrent are identical by construction"
    skipped["serial_only"] = sorted(n for n in sizes if (n, "serial") in indexed and (n, "concurrent") not in indexed)
    skipped["concurrent_only"] = sorted(n for n in sizes if (n, "concurrent") in indexed and (n, "serial") not in indexed)
    skipped = {key: value for key, value in skipped.items() if value}
    return {"provider": rows[0]["provider"], "batches": [_pair(n, indexed[(n, "serial")], indexed[(n, "concurrent")])
                                                        for n in shared],
            "skipped": skipped, "limits": LIMITS}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=Path("data/inference_benchmark.jsonl"))
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    parser.add_argument("--provider", default="local")
    args = parser.parse_args()
    print(json.dumps(compare_batching(_load_summary_rows(args.jsonl, args.since, args.until, args.provider)), indent=2))


if __name__ == "__main__":
    main()
