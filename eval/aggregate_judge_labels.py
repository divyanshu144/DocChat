"""Aggregate blinded LLM-assisted judge labels by model format and split.

This is the only step that reads the unblinding key. The labels are LLM-assisted
and have not been fully human-verified.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

DEFAULT_KEY = Path("/private/tmp/docchat-quality-review-key.json")
SMALL_SAMPLE = 30
DISCLAIMER = ("LLM-assisted labels from a blinded judge; not fully human-verified. "
              "Confidence intervals are 95% Wilson intervals and are wide for small samples.")
_FORMAT = re.compile(r"answers-(fp16|awq|gptq)")


def model_format(record: dict) -> str:
    match = _FORMAT.search(record.get("answer_file", ""))
    if match:
        return match.group(1)
    model = record.get("model", "").lower()
    return next((name for name in ("awq", "gptq") if model.endswith(name)), "fp16")


def wilson(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if not total:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _rate(successes: int, total: int) -> dict:
    return {"n": total, "count": successes, "rate": successes / total if total else None,
            "ci95": wilson(successes, total)}


def load_key(path: Path) -> dict[str, dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Unblinding key not found at {path}. Pass --key, or rebuild it by re-running "
            "eval/build_answer_review_pack.py (new blind ids) or by matching workload_case_id and "
            "answer text against reports/*answers-*.jsonl.")
    records = json.loads(path.read_text())["records"]
    return {record["blind_id"]: record for record in records}


def _count(items: list[dict], field: str, value: str) -> int:
    return sum(item[field] == value for item in items)


def summarize(cells: list[tuple[dict, dict]], failures: int) -> dict:
    """cells: (judge row, pack row) pairs with parse_status == ok."""
    labels = [judge["labels"] for judge, _ in cells]
    n = len(labels)
    cited = [label for label in labels if label["citation_correct"] != "not_applicable"]
    negative = [judge["labels"] for judge, pack in cells if pack["expected_abstention"]]
    positive = [judge["labels"] for judge, pack in cells if not pack["expected_abstention"]]
    return {
        "scored": n,
        "parse_failures": failures,
        "answer_correct": {value: _rate(_count(labels, "answer_correct", value), n)
                           for value in ("yes", "partial", "no")},
        "fully_supported": {value: _rate(_count(labels, "fully_supported", value), n)
                            for value in ("yes", "partial")},
        "mean_unsupported_claims": (sum(label["unsupported_claim_count"] for label in labels) / n) if n else None,
        "citation_correct": {"applicable": len(cited), "not_applicable": n - len(cited),
                             **{value: _rate(_count(cited, "citation_correct", value), len(cited))
                                for value in ("yes", "partial")}},
        "abstention": {
            "negative_control_accuracy": _rate(_count(negative, "abstention_correct", "yes"), len(negative)),
            "false_abstentions": _rate(_count(positive, "abstention_correct", "no"), len(positive))},
        "small_sample_warning": n < SMALL_SAMPLE,
        **({"mean_minor_imprecision": sum(label["minor_imprecision_count"] for label in labels) / n}
           if n and "minor_imprecision_count" in labels[0] else {}),
    }


def aggregate(labels_path: Path, pack_path: Path, key_path: Path, audit_path: Path | None = None) -> dict:
    key = load_key(key_path)
    pack = {row["blind_id"]: row for row in
            (json.loads(line) for line in pack_path.read_text().splitlines() if line.strip())}
    judged = [json.loads(line) for line in labels_path.read_text().splitlines() if line.strip()]
    corrections = {}
    if audit_path:
        corrections = {row["blind_id"]: row["suggested_labels_full"]
                       for row in map(json.loads, audit_path.read_text().splitlines()) if row}
        for row in judged:
            if row["blind_id"] in corrections and row["parse_status"] == "ok":
                row["labels"] = corrections[row["blind_id"]]  # in-memory only; the file is never rewritten
    ids = [row["blind_id"] for row in judged]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate blind_id in judge labels")
    unknown = [blind_id for blind_id in ids if blind_id not in key or blind_id not in pack]
    if unknown:
        raise ValueError(f"labels reference blind_ids missing from key/pack: {unknown[:3]}")
    cells: dict[tuple[str, str], list] = defaultdict(list)
    failures: dict[tuple[str, str], int] = defaultdict(int)
    for row in judged:
        cell = (pack[row["blind_id"]]["split"], model_format(key[row["blind_id"]]))
        if row["parse_status"] == "ok":
            cells[cell].append((row, pack[row["blind_id"]]))
        else:
            failures[cell] += 1
    by_split: dict[str, dict] = defaultdict(dict)
    for split, fmt in sorted(set(cells) | set(failures)):
        by_split[split][fmt] = summarize(cells[(split, fmt)], failures[(split, fmt)])
    return {"label_source": "llm_assisted_audited" if audit_path else "llm_assisted", "human_verified": False,
            "audit_overlay_rows": len(corrections), "disclaimer": DISCLAIMER,
            "judges": sorted({json.dumps(row["judge"], sort_keys=True) for row in judged}),
            "rows_judged": len(judged), "rows_in_pack": len(pack), "by_split": dict(by_split)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=Path("reports/quality-judge-labels.jsonl"))
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--audit", type=Path, help="Optional audit overlay (suggested labels) to apply in memory")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(aggregate(args.labels, args.pack, args.key, args.audit), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
