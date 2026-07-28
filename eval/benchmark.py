#!/usr/bin/env python3
"""Layer A — Critic accuracy diagnostic.

Runs the ambiguous edge cases in `BENCHMARK_CASES` against the real critic node
and reports precision/recall/F1 on detecting "poor" answers.

This measures a RATE, not a binary. A case the critic gets wrong does not fail
anything — it moves the aggregate. That is what makes it safe to run borderline
cases here that would flap in the Layer B regression guard
(`tests/test_critic_eval.py`).

Usage:
    python eval/benchmark.py          # requires GROQ_API_KEY

Always exits 0. It measures; it does not assert.
"""

import asyncio
import sys
from pathlib import Path

# Invoked as a script (`python eval/benchmark.py`), sys.path[0] is eval/, not the
# repo root — so `app` and `eval` are unimportable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.nodes.critic import critic_node  # noqa: E402
from app.agent.state import AgentState  # noqa: E402
from eval.cases import BENCHMARK_CASES, CriticCase  # noqa: E402

_RULE = "─" * 53


async def run_case(case: CriticCase) -> dict:
    """Run one case through the critic. Returns the case's verdict and feedback."""
    state: AgentState = {
        "query": case.query,
        "answer": case.answer,
        "iteration": 0,  # must be 0 — critic short-circuits at >= 2 without an LLM call
        "conversation_id": "",
        "conversation_history": [],
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [],
        "critic_feedback": "",
        "needs_replan": False,
        "grounding_passed": False,
    }

    result = await critic_node(state)
    got = "poor" if result["needs_replan"] else "good"

    return {
        "label": case.label,
        "expected": case.expected,
        "got": got,
        "correct": got == case.expected,
        "feedback": result.get("critic_feedback", ""),
    }


def _compute_metrics(results: list[dict]) -> dict:
    """Confusion matrix and derived metrics. Positive class is "poor".

    Precision/recall are None when their denominator is zero — undefined, not zero.
    """
    tp = sum(1 for r in results if r["expected"] == "poor" and r["got"] == "poor")
    fp = sum(1 for r in results if r["expected"] == "good" and r["got"] == "poor")
    fn = sum(1 for r in results if r["expected"] == "poor" and r["got"] == "good")
    tn = sum(1 for r in results if r["expected"] == "good" and r["got"] == "good")

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None

    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
    }


def _fmt(metric: float | None) -> str:
    return "N/A " if metric is None else f"{metric:.2f}"


async def main() -> None:
    n = len(BENCHMARK_CASES)
    print(
        f"\nDiagnostic run — {n} ambiguous edge cases "
        "(seed dataset, not statistically significant)\n"
    )

    width = max(len(c.label) for c in BENCHMARK_CASES) + 2

    results: list[dict] = []
    for case in BENCHMARK_CASES:
        # Sequential on purpose — 5 cases at ~1s each needs no parallelism.
        result = await run_case(case)
        results.append(result)

        tag = "PASS" if result["correct"] else "FAIL"
        line = (
            f"[{tag}] {result['label']:<{width}}"
            f"expected={result['expected']:<5} got={result['got']:<5}"
        )
        # Feedback on failures only, so a wrong verdict is self-diagnosing
        # without a re-run.
        if not result["correct"] and result["feedback"]:
            line += f' | "{result["feedback"]}"'
        print(line)

    m = _compute_metrics(results)
    correct = sum(1 for r in results if r["correct"])

    print(f"\n{_RULE}")
    print(f"{correct} / {n} correct on edge cases\n")
    print(f"  TP (correctly flagged poor)  : {m['tp']}")
    print(f"  FP (good flagged as poor)    : {m['fp']}")
    print(f"  FN (poor missed as good)     : {m['fn']}")
    print(f"  TN (correctly passed good)   : {m['tn']}\n")
    print(f"  Precision (edge cases) : {_fmt(m['precision'])}   "
          "(of cases flagged poor, how many were?)")
    print(f"  Recall    (edge cases) : {_fmt(m['recall'])}   "
          "(of poor cases, how many were caught?)")
    print(f"  F1        (edge cases) : {_fmt(m['f1'])}\n")
    print(f"  Note: N={n} — expand to 20–30 cases before quoting these numbers externally.")
    print("        Dataset is stacked toward the Critic's known failure modes (over-firing on")
    print("        hedged/partial answers). These numbers measure edge-case precision, not")
    print("        overall Critic quality in production.")
    print(_RULE)


if __name__ == "__main__":
    asyncio.run(main())
