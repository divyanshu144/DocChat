"""Aggregate explicitly annotated DocChat answers without making model judgments.

Input is a JSON object with ``schema_version: 1`` and ``cases``. Each case records
the retrieved context IDs, expected answer fact IDs, emitted citation IDs, and
human-labeled answer claims. See docs/retrieval-quality-evaluation.md.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_case(case: dict) -> dict:
    required = {"id", "expected_fact_ids", "claims", "cited_ids", "context_ids",
                "expected_abstention", "abstained"}
    missing = required - case.keys()
    if missing:
        raise ValueError(f"{case.get('id', '<unknown>')}: missing fields {sorted(missing)}")
    if not isinstance(case["claims"], list):
        raise ValueError(f"{case['id']}: claims must be a list")
    claim_ids = [claim.get("id") for claim in case["claims"]]
    if any(not claim_id for claim_id in claim_ids) or len(set(claim_ids)) != len(claim_ids):
        raise ValueError(f"{case['id']}: claim IDs must be nonempty and unique")
    for claim in case["claims"]:
        if not isinstance(claim.get("supported"), bool) or not isinstance(claim.get("citation_ids", []), list):
            raise ValueError(f"{case['id']}: every claim needs a boolean supported label and citation_ids list")
    expected = set(case["expected_fact_ids"])
    emitted_facts = {fact_id for claim in case["claims"] for fact_id in claim.get("fact_ids", [])}
    cited = set(case["cited_ids"])
    context = set(case["context_ids"])
    claims = case["claims"]
    unsupported = sum(not claim["supported"] for claim in claims)
    supported = len(claims) - unsupported
    cited_claims = sum(bool(claim.get("citation_ids")) for claim in claims)
    return {
        "id": case["id"],
        "answer_fact_recall": _ratio(len(expected & emitted_facts), len(expected)),
        "unsupported_claim_rate": _ratio(unsupported, len(claims)),
        "claim_citation_coverage": _ratio(
            sum(claim["supported"] and bool(claim.get("citation_ids")) for claim in claims), supported
        ),
        "citation_validity": _ratio(sum(citation in context for citation in cited), len(cited)),
        "citation_coverage": _ratio(cited_claims, len(claims)),
        "abstention_correct": case["abstained"] == case["expected_abstention"],
        "abstention_expected": bool(case["expected_abstention"]),
        "claim_count": len(claims),
    }


def aggregate(cases: list[dict]) -> dict:
    if not cases:
        raise ValueError("At least one annotated case is required")
    ids = [case.get("id") for case in cases]
    if any(not case_id for case_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("Case IDs must be nonempty and unique")
    rows = [score_case(case) for case in cases]
    metric_names = ("answer_fact_recall", "unsupported_claim_rate",
                    "claim_citation_coverage", "citation_validity", "citation_coverage")
    summary = {}
    for metric in metric_names:
        values = [row[metric] for row in rows if row[metric] is not None]
        summary[metric] = statistics.mean(values) if values else None
    summary["abstention_accuracy"] = statistics.mean(row["abstention_correct"] for row in rows)
    summary["cases"] = len(rows)
    summary["cases_with_expected_abstention"] = sum(row["abstention_expected"] for row in rows)
    return {"summary": summary, "cases": rows,
            "interpretation": "Metrics aggregate supplied labels; they do not independently verify claim support."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", type=Path, help="Version 1 annotated-answer JSON")
    parser.add_argument("--output", type=Path, help="Optional path for the aggregate JSON report")
    args = parser.parse_args()
    payload = json.loads(args.annotations.read_text())
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cases"), list):
        raise ValueError("Expected schema_version 1 and a cases array")
    report = aggregate(payload["cases"])
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
