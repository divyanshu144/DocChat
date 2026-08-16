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
from eval.corruptions import generate  # noqa: E402

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
        # Stays empty even for cases carrying `context`: CRITIC_PROMPT interpolates
        # only query and answer, so populating this would change nothing.
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
    Cases without a binary verdict are excluded from the confusion matrix.
    """
    measured = [r for r in results if r["got"] in {"poor", "good"}]

    tp = sum(1 for r in measured if r["expected"] == "poor" and r["got"] == "poor")
    fp = sum(1 for r in measured if r["expected"] == "good" and r["got"] == "poor")
    fn = sum(1 for r in measured if r["expected"] == "poor" and r["got"] == "good")
    tn = sum(1 for r in measured if r["expected"] == "good" and r["got"] == "good")

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None

    if precision is None or recall is None:
        f1 = None
    elif (precision + recall) == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "errors": len(results) - len(measured),
        "precision": precision, "recall": recall, "f1": f1,
    }


def _fmt(metric: float | None) -> str:
    return "N/A " if metric is None else f"{metric:.2f}"


async def _run_group(cases: list[CriticCase], heading: str) -> list[dict]:
    """Run one group of cases, printing a line each. Never raises."""
    print(f"\n{heading}\n")
    width = max(len(c.label) for c in cases) + 2

    results: list[dict] = []
    for case in cases:
        # Sequential on purpose — a few dozen cases at ~1s each needs no parallelism.
        try:
            result = await run_case(case)
        except Exception as exc:
            result = {
                "label": case.label,
                "expected": case.expected,
                "got": "error",
                "correct": False,
                "feedback": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)

        tag = "ERROR" if result["got"] == "error" else ("PASS" if result["correct"] else "FAIL")
        line = (
            f"[{tag}] {result['label']:<{width}}"
            f"expected={result['expected']:<5} got={result['got']:<5}"
        )
        # Feedback on failures only, so a wrong verdict is self-diagnosing
        # without a re-run.
        if not result["correct"] and result["feedback"]:
            line += f' | "{result["feedback"]}"'
        print(line)

    return results


def _report(title: str, results: list[dict]) -> None:
    m = _compute_metrics(results)
    correct = sum(1 for r in results if r["correct"])

    print(f"\n{_RULE}")
    print(f"{title} — {correct} / {len(results)} correct\n")
    print(f"  TP (correctly flagged poor)  : {m['tp']}")
    print(f"  FP (good flagged as poor)    : {m['fp']}")
    print(f"  FN (poor missed as good)     : {m['fn']}")
    print(f"  TN (correctly passed good)   : {m['tn']}")
    print(f"  Errors (no verdict)          : {m['errors']}\n")
    print(f"  Precision : {_fmt(m['precision'])}   (of cases flagged poor, how many were?)")
    print(f"  Recall    : {_fmt(m['recall'])}   (of poor cases, how many were caught?)")
    print(f"  F1        : {_fmt(m['f1'])}")
    print(_RULE)


def _per_transform(results: list[dict]) -> None:
    """Recall broken out by transform.

    Every generated case is labelled "poor", so this is recall and nothing else — but
    it is the useful cut: a transform the critic misses wholesale is either a real
    blind spot or a badly designed corruption, and the two are worth telling apart.
    """
    by_transform: dict[str, list[dict]] = {}
    for r in results:
        by_transform.setdefault(r["label"].rsplit("__", 1)[-1], []).append(r)

    print("\n  Caught, by transform:")
    for name in sorted(by_transform):
        group = by_transform[name]
        caught = sum(1 for r in group if r["correct"])
        print(f"    {name:<22} {caught}/{len(group)}")


async def main() -> None:
    edge_cases = list(BENCHMARK_CASES)
    generated = generate()

    print(
        f"\nDiagnostic run — {len(edge_cases)} hand-written edge cases "
        f"+ {len(generated)} generated corruptions\n"
    )

    edge_results = await _run_group(
        edge_cases, "Hand-written edge cases — ambiguous, near the decision boundary"
    )
    gen_results = await _run_group(
        generated, "Generated corruptions — label inherited from the transform"
    )

    # Scored separately on purpose. The generated cases are mostly NOT borderline, so
    # merging them would inflate the headline number and destroy comparability with
    # every edge-case run recorded before they existed.
    _report("EDGE CASES", edge_results)
    _report("GENERATED CORRUPTIONS", gen_results)
    _per_transform(gen_results)

    print(f"\n{_RULE}")
    print(f"  Note: edge-case N={len(edge_cases)} — still too small to quote externally.")
    print("        That dataset is stacked toward the Critic's known failure modes")
    print("        (over-firing on hedged/partial answers), so it measures edge-case")
    print("        precision, not overall Critic quality in production.")
    print("        The generated set measures the opposite end: whether obvious")
    print("        degradations are caught at all. Neither is reproducible run-to-run")
    print("        until temperature is pinned on the classification nodes.")
    print(_RULE)


if __name__ == "__main__":
    asyncio.run(main())
