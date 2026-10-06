"""Coverage and pairwise agreement for partially completed judge runs (v1-corrected, and any v2 judges).

Compares judges only on the rows both scored. Reads the unblinding key for coverage by split/format
(aggregation stage). LLM-assisted labels, not human-verified.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from eval.compare_judge_labels import compare, load, overlay, unsupported_stats
from eval.paired_format_comparison import model_format


def coverage(rows: dict[str, dict], pack: dict, key: dict) -> dict:
    cells = Counter((pack[i]["split"], model_format(key[i])) for i, r in rows.items() if r["parse_status"] == "ok")
    return {f"{split}/{fmt}": n for (split, fmt), n in sorted(cells.items())}


def summarize(runs: dict[str, dict[str, dict]], pack: dict, key: dict) -> dict:
    out = {"label_source": "llm_assisted", "human_verified": False,
           "rows_judged": {n: len(r) for n, r in runs.items()},
           "parse_ok": {n: sum(x["parse_status"] == "ok" for x in r.values()) for n, r in runs.items()},
           "coverage_by_split_format": {n: coverage(r, pack, key) for n, r in runs.items()}, "pairs": {}}
    for (na, a), (nb, b) in combinations(runs.items(), 2):
        shared = sorted(i for i in a if i in b and a[i]["parse_status"] == "ok" and b[i]["parse_status"] == "ok")
        if not shared:
            continue
        sa, sb = {i: a[i] for i in shared}, {i: b[i] for i in shared}
        result = compare(sa, sb)
        out["pairs"][f"{na} vs {nb}"] = {
            "shared_rows": len(shared), "agreement": {f: v["agree"] for f, v in result["fields"].items()},
            "disagreements": {f: v["disagreements"] for f, v in result["fields"].items() if v["disagreements"]},
            "stats": {na: unsupported_stats(sa), nb: unsupported_stats(sb)}}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1", type=Path, default=Path("reports/quality-judge-labels.jsonl"))
    parser.add_argument("--audit", type=Path, default=Path("reports/quality-judge-label-audit.jsonl"))
    parser.add_argument("--judge", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--key", type=Path, default=Path("/private/tmp/docchat-quality-review-key.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runs = {"v1_corrected": overlay(load(args.v1), args.audit)}
    runs |= {n: load(Path(p)) for n, p in (item.split("=", 1) for item in args.judge)}
    pack = {r["blind_id"]: r for r in map(json.loads, args.pack.read_text().splitlines()) if r}
    key = {r["blind_id"]: r for r in json.loads(args.key.read_text())["records"]}
    rendered = json.dumps(summarize(runs, pack, key), indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
