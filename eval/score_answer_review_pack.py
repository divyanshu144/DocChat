"""Convert a completed blind answer-review JSONL into reviewed metrics."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from eval.answer_quality import aggregate


def _scorer_case(row: dict) -> dict:
    review = row.get("review", {})
    if not isinstance(review.get("abstained"), bool):
        raise ValueError(f"{row.get('blind_id')}: review.abstained must be a human-labeled boolean")
    claims = review.get("claims")
    if not isinstance(claims, list):
        raise ValueError(f"{row.get('blind_id')}: review.claims must be a reviewed list")
    if any(not isinstance(claim.get("supported"), bool) for claim in claims):
        raise ValueError(f"{row.get('blind_id')}: every claim needs a human supported boolean")
    return {"id": row["blind_id"],
            "expected_fact_ids": [fact["id"] for fact in row.get("expected_facts", [])],
            "context_ids": row.get("source_markers_in_context", []),
            "cited_ids": row.get("emitted_citations", []),
            "expected_abstention": row["expected_abstention"],
            "abstained": review["abstained"], "claims": claims}


def score_review_pack(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError("Review pack is empty")
    blind_ids = [row.get("blind_id") for row in rows]
    if any(not value for value in blind_ids) or len(set(blind_ids)) != len(blind_ids):
        raise ValueError("blind_id values must be present and unique")
    successful = [row for row in rows if row.get("answer_status", "ok") == "ok"]
    failed = [row for row in rows if row.get("answer_status", "ok") != "ok"]
    if not successful:
        raise ValueError("No successful answers are available to score")
    reviewed = [(row, _scorer_case(row)) for row in successful]
    groups: dict[str, list[dict]] = defaultdict(list)
    for row, case in reviewed:
        groups[row.get("split", "unknown")].append(case)
    return {"schema_version": 1, "records": len(rows), "scored_records": len(successful),
            "failed_answers": len(failed),
            "overall": aggregate([case for _, case in reviewed]),
            "by_split": {name: aggregate(cases) for name, cases in sorted(groups.items())}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_pack", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = score_review_pack(args.review_pack)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
