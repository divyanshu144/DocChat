"""Judge-free answer behaviour: format, citations and abstention, with Wilson intervals and paired comparisons.

This measures what the serving prompt asks for and what can be checked mechanically. It does NOT measure whether the
claims in an answer are true or complete; that needs a judge or a person (see `judge_answer_review_pack.py`).

Per answer (an error or an empty answer counts as a failure, never as a skipped case):
  has_sources            a `Sources:` section with at least one marker
  citations_valid        every marker in it is a marker that was in the supplied context
  no_body_citations      no markers inside the answer text (the prompt asks for them only at the end)
  no_markdown            no headings or bold (the prompt forbids them)
  no_duplicate_sources   each source listed once
  abstained              says the context lacks the information and cites nothing
  abstained_short        the same, and the answer is under 500 characters, so a full answer that merely notes one missing
                         detail is not counted as a refusal. Added after the first run showed that the base model, which
                         never cites, was credited with "abstaining" whenever it mentioned a gap; both are reported.
  well_formed_answer     all of the above format checks pass and the answer did not abstain
Answerable cases (every category except negative_control) report well_formed_answer and false_refusal (= abstained).
Negative controls report correct_abstention (= abstained) and unsupported_answer (= did not abstain).

Pairs: two arms are compared on the same case ids. The exact two-sided binomial test is run on the cases where they
differ (McNemar), so a difference inside the noise is reported as such.

Usage:  python -m eval.answer_behaviour_metrics --run base:v2:a.jsonl --run tuned:v2:b.jsonl --pair tuned:base
"""
from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path

from eval.aggregate_judge_labels import wilson
from finetune.citations import body_markers, cited_markers, context_markers, split_answer
from finetune.validate_examples import _ABSTAIN, _MARKDOWN

SHORT_ABSTENTION_CHARS = 500
FORMAT_CHECKS = ("has_sources", "citations_valid", "no_body_citations", "no_markdown", "no_duplicate_sources")


def analyse(row: dict) -> dict:
    """Mechanical checks on one answer row (a row of `generate_answer_samples.py` output)."""
    answer = (row.get("answer") or "").strip()
    usable = row.get("status", "ok") == "ok" and bool(answer)
    system = next((m["content"] for m in row.get("messages", []) if m.get("role") == "system"), "")
    supplied = set(context_markers(system))
    cited = cited_markers(answer) if usable else []
    body, _ = split_answer(answer)
    abstained = usable and bool(_ABSTAIN.search(body)) and not cited
    checks = {
        "has_sources": bool(cited),
        "citations_valid": bool(cited) and all(c in supplied for c in cited),
        "no_body_citations": usable and not body_markers(answer),
        "no_markdown": usable and not _MARKDOWN.search(answer),
        "no_duplicate_sources": usable and len(set(cited)) == len(cited),
    }
    return {**checks, "abstained": abstained, "abstained_short": abstained and len(answer) < SHORT_ABSTENTION_CHARS,
            "well_formed_answer": all(checks.values()) and not abstained,
            "truncated": row.get("finish_reason") == "length", "failed": not usable, "chars": len(answer)}


def _rate(flags: list[bool]) -> dict:
    k, n = sum(flags), len(flags)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None,
            "wilson95": [round(x, 4) for x in wilson(k, n)] if n else None}


def summarise(rows: list[dict]) -> dict:
    """Rates for one arm on one workload, answerable cases and negative controls reported separately."""
    out: dict = {"cases": len(rows), "failed_or_empty": sum(analyse(r)["failed"] for r in rows)}
    answerable = [analyse(r) for r in rows if r.get("category") != "negative_control"]
    negatives = [analyse(r) for r in rows if r.get("category") == "negative_control"]
    out["answerable"] = {"well_formed_answer": _rate([a["well_formed_answer"] for a in answerable]),
                         "false_refusal": _rate([a["abstained"] for a in answerable]),
                         "false_refusal_short": _rate([a["abstained_short"] for a in answerable]),
                         "truncated": _rate([a["truncated"] for a in answerable]),
                         **{check: _rate([a[check] for a in answerable]) for check in FORMAT_CHECKS},
                         "mean_chars": round(sum(a["chars"] for a in answerable) / len(answerable), 1) if answerable else None}
    out["negative_control"] = {"correct_abstention": _rate([a["abstained"] for a in negatives]),
                               "correct_abstention_short": _rate([a["abstained_short"] for a in negatives]),
                               "unsupported_answer": _rate([not a["abstained"] for a in negatives])}
    return out


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact binomial p-value for `only_a` vs `only_b` discordant pairs under a 50/50 null."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired(rows_a: list[dict], rows_b: list[dict], group: str, metric: str) -> dict:
    """Compare two arms on the cases they share: how many each got right that the other did not, and the exact p-value."""
    def flags(rows):
        return {r["case_id"]: analyse(r) for r in rows if (r.get("category") == "negative_control") == (group == "negative_control")}
    a, b = flags(rows_a), flags(rows_b)
    shared = sorted(set(a) & set(b))
    only_a = sum(a[c][metric] and not b[c][metric] for c in shared)
    only_b = sum(b[c][metric] and not a[c][metric] for c in shared)
    return {"shared_cases": len(shared), "only_first": only_a, "only_second": only_b, "p_exact": round(mcnemar_exact(only_a, only_b), 4)}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="ARM:WORKLOAD:FILE",
                        help="answers of one arm on one workload, e.g. tuned:v2:answers.jsonl")
    parser.add_argument("--pair", action="append", default=[], metavar="FIRST:SECOND", help="compare two arms")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runs: dict[tuple[str, str], list[dict]] = {}
    for spec in args.run:
        arm, workload, file = spec.split(":", 2)
        runs[(arm, workload)] = load(Path(file))
    report: dict = {"arms": {f"{arm}/{workload}": summarise(rows) for (arm, workload), rows in runs.items()}, "paired": {}}
    for pair in args.pair:
        first, second = pair.split(":")
        for workload in sorted({w for (_, w) in runs}):
            if (first, workload) in runs and (second, workload) in runs:
                a, b = runs[(first, workload)], runs[(second, workload)]
                report["paired"][f"{first}-vs-{second}/{workload}"] = {
                    "well_formed_answer": paired(a, b, "answerable", "well_formed_answer"),
                    "false_refusal": paired(a, b, "answerable", "abstained"),
                    "false_refusal_short": paired(a, b, "answerable", "abstained_short"),
                    "correct_abstention": paired(a, b, "negative_control", "abstained"),
                    "correct_abstention_short": paired(a, b, "negative_control", "abstained_short")}
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
