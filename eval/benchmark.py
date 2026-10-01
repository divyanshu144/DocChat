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
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Invoked as a script (`python eval/benchmark.py`), sys.path[0] is eval/, not the
# repo root — so `app` and `eval` are unimportable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.nodes.critic import critic_node  # noqa: E402
from app.agent.state import AgentState  # noqa: E402
from eval.cases import BENCHMARK_CASES, CriticCase  # noqa: E402
from eval.corruptions import generate  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import llm  # noqa: E402

_RULE = "─" * 53


async def run_case(case: CriticCase) -> dict:
    """Run one case through the critic. Returns the case's verdict and feedback."""
    state: AgentState = {
        "query": case.query,
        "original_query": case.query,
        "answer": case.answer,
        "iteration": 0,  # must be 0 — critic short-circuits at >= 2 without an LLM call
        "conversation_id": "",
        "conversation_history": [],
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "pending_rejection": None,
        # Stays empty even for cases carrying `context`: CRITIC_PROMPT interpolates
        # only query and answer, so populating this would change nothing.
        "retrieved_chunks": [],
        "critic_feedback": "",
        "needs_replan": False,
        "grounding_passed": False,
    }

    responses = []
    original_complete = llm.chat_complete

    async def track_response(*args, **kwargs):
        response = await original_complete(*args, **kwargs)
        responses.append(response)
        return response

    with patch("app.agent.nodes.critic.chat_complete", new=track_response):
        result = await critic_node(state)
    got = "poor" if result["needs_replan"] else "good"
    # A fail-open parse fallback is not an observed good verdict.
    try:
        parsed = json.loads(responses[-1])
        valid = isinstance(parsed, dict) and parsed.get("quality") in ("good", "poor")
    except (ValueError, TypeError, IndexError):
        valid = False
    if not valid:
        got = "error"

    return {
        "label": case.label,
        "expected": case.expected,
        "got": got,
        "correct": got == case.expected,
        "feedback": result.get("critic_feedback", ""),
        "raw_response": responses[-1] if responses else None,
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


def _report(title: str, results: list[dict], cases: list[CriticCase]) -> None:
    m = _compute_metrics(results)
    correct = sum(1 for r in results if r["correct"])

    print(f"\n{_RULE}")
    print(f"{title} — {correct} / {len(results)} correct\n")
    print(f"  TP (correctly flagged poor)  : {m['tp']}")
    print(f"  FP (good flagged as poor)    : {m['fp']}")
    print(f"  FN (poor missed as good)     : {m['fn']}")
    print(f"  TN (correctly passed good)   : {m['tn']}")
    print(f"  Errors (no verdict)          : {m['errors']}\n")

    # With no "good" cases in the group, FP and TN are zero no matter how the critic
    # behaves, so precision is pinned at 1.00 and F1 inherits it. Printing them next to
    # a real recall invites reading a structural constant as a result.
    if any(c.expected == "good" for c in cases):
        print(f"  Precision : {_fmt(m['precision'])}   (of cases flagged poor, how many were?)")
        print(f"  Recall    : {_fmt(m['recall'])}   (of poor cases, how many were caught?)")
        print(f"  F1        : {_fmt(m['f1'])}")
    else:
        print(f"  Recall    : {_fmt(m['recall'])}   (of poor cases, how many were caught?)")
        print("  Precision : not defined — every case here is labelled poor, so precision")
        print("              is 1.00 by construction and measures nothing.")
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


async def main(output: Path | None = None) -> None:
    edge_cases = list(BENCHMARK_CASES)
    generated = generate()
    http_usage = []
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        client = llm._get_client()
        preflight = await client.get(f"/models/{settings.openai_chat_model}")
        preflight.raise_for_status()

        async def observe(response):
            await response.aread()
            if response.request.url.path.endswith("/chat/completions"):
                data = response.json()
                http_usage.append({"status": response.status_code, "usage": data.get("usage"),
                                   "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason")})

        client.event_hooks["response"].append(observe)

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
    _report("EDGE CASES", edge_results, edge_cases)
    _report("GENERATED CORRUPTIONS", gen_results, generated)
    _per_transform(gen_results)

    print(f"\n{_RULE}")
    print(f"  Note: edge-case N={len(edge_cases)} — still too small to quote externally.")
    print("        That dataset is stacked toward the Critic's known failure modes")
    print("        (over-firing on hedged/partial answers), so it measures edge-case")
    print("        precision, not overall Critic quality in production.")
    print("        The generated set measures the opposite end: whether obvious")
    print("        degradations are caught at all.")
    print("        Reproducibility depends on the MODEL, not just the config: the critic")
    print("        asks for temperature=0, but a model that rejects it (gpt-5.6-luna and")
    print("        the reasoning family) is silently served at its default and verdicts")
    print("        will move between runs. Check the logs for")
    print("        openai_rejected_temperature_retrying_without before trusting a delta.")
    print(_RULE)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": settings.llm_provider, "model": llm._active_model(),
            "reasoning_effort": settings.openai_reasoning_effort,
            "max_completion_tokens": 150, "temperature": settings.classification_temperature,
            "fallback": settings.fallback_llm_provider,
            "edge_metrics": _compute_metrics(edge_results), "generated_metrics": _compute_metrics(gen_results),
            "edge_results": edge_results, "generated_results": gen_results,
            "http_usage": http_usage,
        }, indent=2))


async def _cli(output: Path | None) -> None:
    try:
        await asyncio.wait_for(main(output), timeout=300)
    finally:
        if llm._client is not None:
            close = getattr(llm._client, "aclose", None) or llm._client.close
            await close()
            llm._client = None
            llm._client_provider = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(_cli(args.output))
