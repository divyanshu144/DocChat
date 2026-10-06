"""Compare judge runs on the same blinded rows: v1 original, v1 + audit correction, and v2.

Reads blinded labels only (no unblinding key). Reports per-field agreement, confusion counts and
unsupported-claim totals so prompt/judge changes can be separated from real disagreement.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

FIELDS = ("answer_correct", "fully_supported", "citation_correct", "abstention_correct")


def load(path: Path) -> dict[str, dict]:
    return {row["blind_id"]: row for row in map(json.loads, path.read_text().splitlines()) if row}


def overlay(v1: dict[str, dict], audit_path: Path) -> dict[str, dict]:
    corrected = {k: dict(v) for k, v in v1.items()}
    for row in map(json.loads, audit_path.read_text().splitlines()):
        if row and corrected[row["blind_id"]]["parse_status"] == "ok":
            corrected[row["blind_id"]]["labels"] = row["suggested_labels_full"]
    return corrected


def unsupported_stats(rows: dict[str, dict]) -> dict:
    ok = [r["labels"] for r in rows.values() if r["parse_status"] == "ok"]
    return {"scored": len(ok), "total_unsupported": sum(label["unsupported_claim_count"] for label in ok),
            "rows_with_unsupported": sum(label["unsupported_claim_count"] > 0 for label in ok),
            "fully_supported_yes": sum(label["fully_supported"] == "yes" for label in ok),
            "total_minor_imprecision": sum(label.get("minor_imprecision_count", 0) for label in ok)}


def compare(a: dict[str, dict], b: dict[str, dict]) -> dict:
    ids = sorted(k for k in a if k in b and a[k]["parse_status"] == "ok" and b[k]["parse_status"] == "ok")
    out = {"rows_compared": len(ids), "fields": {}}
    for field in FIELDS:
        pairs = Counter((a[i]["labels"][field], b[i]["labels"][field]) for i in ids)
        agree = sum(n for (x, y), n in pairs.items() if x == y)
        out["fields"][field] = {"agreement": agree / len(ids) if ids else None, "agree": agree,
                                "disagreements": {f"{x}->{y}": n for (x, y), n in sorted(pairs.items()) if x != y}}
    out["disagreeing_rows"] = {field: [i for i in ids if a[i]["labels"][field] != b[i]["labels"][field]]
                               for field in FIELDS}
    return out


def row_details(a: dict[str, dict], b: dict[str, dict], ids: list[str]) -> list[dict]:
    """Per-row view of where two judges differ: label changes, claim counts and both notes."""
    out = []
    for i in ids:
        la, lb = a[i]["labels"], b[i]["labels"]
        changed = {f: [la[f], lb[f]] for f in FIELDS if la[f] != lb[f]}
        counts = {"unsupported": [la["unsupported_claim_count"], lb["unsupported_claim_count"]],
                  "minor_imprecision": [la.get("minor_imprecision_count"), lb.get("minor_imprecision_count")],
                  "claims": [len(la["claims"]), len(lb["claims"])]}
        if changed or counts["unsupported"][0] != counts["unsupported"][1]:
            out.append({"blind_id": i, "label_changes": changed, "counts": counts,
                        "notes": [la["notes"], lb["notes"]]})
    return out


def compare_files(path_a: Path, path_b: Path) -> dict:
    """Compare two label files on their shared rows (any prompt version or judge)."""
    a, b = load(path_a), load(path_b)
    shared = sorted(k for k in a if k in b and a[k]["parse_status"] == "ok" and b[k]["parse_status"] == "ok")
    both = {k: a[k] for k in shared}, {k: b[k] for k in shared}
    judge = lambda rows: sorted({f"{r['judge']['model']}/{r['judge']['prompt_version']}" for r in rows.values()})  # noqa: E731
    return {"a": judge(both[0]), "b": judge(both[1]), "comparison": compare(*both),
            "stats": {"a": unsupported_stats(both[0]), "b": unsupported_stats(both[1])},
            "row_details": row_details(a, b, shared)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-a", type=Path, help="Pairwise mode: first label file (e.g. Opus v2)")
    parser.add_argument("--judge-b", type=Path, help="Pairwise mode: second label file (e.g. gpt-6-astra v2)")
    parser.add_argument("--v1", type=Path, default=Path("reports/quality-judge-labels.jsonl"))
    parser.add_argument("--audit", type=Path, default=Path("reports/quality-judge-label-audit.jsonl"))
    parser.add_argument("--v2", type=Path, default=Path("reports/quality-judge-labels-v2.jsonl"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.judge_a and args.judge_b:
        rendered = json.dumps(compare_files(args.judge_a, args.judge_b), indent=2)
        if args.output:
            args.output.write_text(rendered + "\n")
        print(rendered)
        return
    v1, v2 = load(args.v1), load(args.v2)
    corrected = overlay(v1, args.audit)
    report = {"label_source": "llm_assisted", "human_verified": False,
              "unsupported_stats": {"v1_original": unsupported_stats(v1), "v1_corrected": unsupported_stats(corrected),
                                    "v2": unsupported_stats(v2)},
              "v2_vs_v1_original": compare(v2, v1), "v2_vs_v1_corrected": compare(v2, corrected)}
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
