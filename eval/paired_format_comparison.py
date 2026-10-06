"""Paired per-case comparison of serving formats from blinded judge labels.

Each workload case is answered by all three formats, so formats are compared on the same case rather
than across independent cells. Reads the unblinding key (aggregation stage only). LLM-assisted labels,
not human-verified. Win/loss/tie counts, exact sign-test p-values and bootstrap intervals are
descriptive; with a few dozen cases they are wide.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path

SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0}
FORMATS = ("fp16", "awq", "gptq")
METRICS = {
    "answer_score": lambda labels: SCORE[labels["answer_correct"]],
    "fully_supported_yes": lambda labels: float(labels["fully_supported"] == "yes"),
    "unsupported_claims": lambda labels: float(labels["unsupported_claim_count"]),
}
EXPLORATORY = {"fully_supported_yes", "unsupported_claims"}
HIGHER_IS_BETTER = {"answer_score": True, "fully_supported_yes": True, "unsupported_claims": False}


def sign_test_p(wins: int, losses: int) -> float | None:
    """Exact two-sided sign test on non-tied pairs."""
    n = wins + losses
    if not n:
        return None
    tail = sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_ci(diffs: list[float], seed: int = 20261006, draws: int = 5000) -> list[float] | None:
    if not diffs:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(draws))
    return [round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws) - 1], 4)]


def model_format(record: dict) -> str:
    match = re.search(r"answers-(fp16|awq|gptq)", record.get("answer_file", ""))
    if match:
        return match.group(1)
    model = record.get("model", "").lower()
    return next((name for name in ("awq", "gptq") if model.endswith(name)), "fp16")


def paired(labels_path: Path, pack_path: Path, key_path: Path, audit_path: Path | None = None) -> dict:
    key = {r["blind_id"]: r for r in json.loads(key_path.read_text())["records"]}
    pack = {r["blind_id"]: r for r in map(json.loads, pack_path.read_text().splitlines()) if r}
    rows = {r["blind_id"]: r for r in map(json.loads, labels_path.read_text().splitlines()) if r}
    if audit_path:
        for line in audit_path.read_text().splitlines():
            audit = json.loads(line) if line.strip() else None
            if audit and rows[audit["blind_id"]]["parse_status"] == "ok":
                rows[audit["blind_id"]]["labels"] = audit["suggested_labels_full"]
    cases: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for blind_id, row in rows.items():
        if row["parse_status"] == "ok":
            cases[(pack[blind_id]["split"], key[blind_id]["workload_case_id"])][model_format(key[blind_id])] = row["labels"]
    out: dict = {"label_source": "llm_assisted_audited" if audit_path else "llm_assisted", "human_verified": False,
                 "note": "Descriptive. Sign-test p-values are exact and two-sided on non-tied cases; intervals are "
                         "bootstrap 95%. Do not read these as significance claims.",
                 "by_split": {}}
    for split in sorted({s for s, _ in cases}):
        split_cases = {c: v for (s, c), v in cases.items() if s == split}
        result = {"cases": len(split_cases), "comparisons": {}}
        for a, b in combinations(FORMATS, 2):
            shared = [v for v in split_cases.values() if a in v and b in v]
            entry = {"paired_cases": len(shared), "metrics": {}}
            for name, fn in METRICS.items():
                diffs = [fn(v[a]) - fn(v[b]) for v in shared]
                better = (lambda d: d > 0) if HIGHER_IS_BETTER[name] else (lambda d: d < 0)
                worse = (lambda d: d < 0) if HIGHER_IS_BETTER[name] else (lambda d: d > 0)
                wins, losses = sum(better(d) for d in diffs), sum(worse(d) for d in diffs)
                entry["metrics"][name] = {
                    "exploratory": name in EXPLORATORY, f"{a}_better": wins, f"{b}_better": losses,
                    "ties": len(diffs) - wins - losses,
                    "mean_diff": round(sum(diffs) / len(diffs), 4) if diffs else None,
                    "bootstrap_ci95": bootstrap_ci(diffs), "sign_test_p": sign_test_p(wins, losses)}
            result["comparisons"][f"{a}_vs_{b}"] = entry
        out["by_split"][split] = result
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=Path("reports/quality-judge-labels.jsonl"))
    parser.add_argument("--audit", type=Path, help="Optional audit overlay (corrected labels)")
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--key", type=Path, default=Path("/private/tmp/docchat-quality-review-key.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(paired(args.labels, args.pack, args.key, args.audit), indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
