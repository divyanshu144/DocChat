"""Paired comparison of retrieval arms from a `retrieval_eval` / `live_retrieval_ab` report.

A mean difference of a few points on ~100 questions is easy to read as a result when it is noise, so every
comparison here carries a paired-bootstrap confidence interval over questions, a win/loss/tie count, and a
per-stratum breakdown.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

METRICS = ("reciprocal_rank", "recall@1", "recall@3", "recall@5")
DEFAULT_PAIRS = (
    ("hybrid_rrf", "dense_overlap_rerank"),
    ("hybrid_rrf", "dense"),
    ("hybrid_rrf", "bm25"),
    ("dense_overlap_rerank", "dense"),
    ("prod_hybrid", "prod_dense"),
)


def paired_bootstrap(a: list[float], b: list[float], *, resamples: int = 10_000, seed: int = 0,
                     confidence: float = 0.95) -> dict:
    """Mean of (a - b) over questions with a percentile bootstrap CI that resamples questions, keeping pairs."""
    if len(a) != len(b) or not a:
        raise ValueError("paired samples must be non-empty and the same length")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(statistics.fmean(rng.choices(diffs, k=n)) for _ in range(resamples))
    tail = (1 - confidence) / 2
    low, high = means[int(tail * resamples)], means[min(resamples - 1, int((1 - tail) * resamples))]
    return {"n": n, "mean_diff": statistics.fmean(diffs), "ci_low": low, "ci_high": high,
            "significant": low > 0 or high < 0}


def win_loss_tie(a: list[float], b: list[float], *, tol: float = 1e-9) -> dict:
    wins = sum(x - y > tol for x, y in zip(a, b, strict=True))
    losses = sum(y - x > tol for x, y in zip(a, b, strict=True))
    return {"wins": wins, "losses": losses, "ties": len(a) - wins - losses}


def compare(rows: list[dict], arm_a: str, arm_b: str, metric: str, **kw) -> dict:
    a = [row["rankings"][arm_a][metric] for row in rows]
    b = [row["rankings"][arm_b][metric] for row in rows]
    return {**paired_bootstrap(a, b, **kw), **win_loss_tie(a, b)}


def mean_metrics(rows: list[dict], arms: list[str]) -> dict:
    return {arm: {m: statistics.fmean(row["rankings"][arm][m] for row in rows) for m in METRICS} for arm in arms}


def overlap_buckets(rows: list[dict]) -> dict[str, list[dict]]:
    """Split questions that carry a lexical_overlap into equal-sized low / mid / high thirds."""
    scored = sorted((r for r in rows if r.get("lexical_overlap") is not None), key=lambda r: r["lexical_overlap"])
    third = len(scored) // 3
    if third == 0:
        return {}
    return {"overlap_low": scored[:third], "overlap_mid": scored[third:2 * third], "overlap_high": scored[2 * third:]}


def analyse(report: dict, pairs=DEFAULT_PAIRS, **kw) -> dict:
    rows = report["results"]
    arms = sorted({arm for row in rows for arm in row["rankings"]})
    groups = {"all": rows}
    for stratum in sorted({r.get("stratum") for r in rows if r.get("stratum")}):
        groups[f"stratum:{stratum}"] = [r for r in rows if r.get("stratum") == stratum]
    groups.update(overlap_buckets(rows))
    out = {}
    for name, group in groups.items():
        out[name] = {"n": len(group), "means": mean_metrics(group, arms), "comparisons": {}}
        for arm_a, arm_b in pairs:
            if arm_a in arms and arm_b in arms:
                out[name]["comparisons"][f"{arm_a} - {arm_b}"] = {
                    m: compare(group, arm_a, arm_b, m, **kw) for m in ("reciprocal_rank", "recall@1", "recall@3")}
    return out


def render(analysis: dict) -> str:
    lines = []
    for name, block in analysis.items():
        lines.append(f"\n## {name} (n={block['n']})")
        lines.append(f"{'arm':24s}" + "".join(f"{m:>17s}" for m in METRICS))
        for arm, vals in block["means"].items():
            lines.append(f"{arm:24s}" + "".join(f"{vals[m]:>17.3f}" for m in METRICS))
        for pair, metrics in block["comparisons"].items():
            for metric, r in metrics.items():
                flag = " *" if r["significant"] else ""
                lines.append(f"  {pair:44s} {metric:16s} diff {r['mean_diff']:+.3f}  95% CI [{r['ci_low']:+.3f}, "
                             f"{r['ci_high']:+.3f}]  W/L/T {r['wins']}/{r['losses']}/{r['ties']}{flag}")
    lines.append("\n* = 95% CI excludes zero")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    analysis = analyse(json.loads(args.report.read_text()))
    print(render(analysis))
    if args.json_out:
        args.json_out.write_text(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    main()
