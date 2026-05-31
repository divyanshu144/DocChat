# Critic Eval Harness — Design Spec

**Date:** 2026-05-28
**Branch:** feat/chat-folders
**Status:** Approved, ready for implementation

---

## Overview

Build a two-layer evaluation harness for the LangGraph `critic_node`. Layer B (regression guard) ships first; Layer A (accuracy benchmark) is built on top of the same shared dataset.

- **Layer B — Regression guard:** asserts binary pass/fail against an unambiguous labeled dataset using the real Groq LLM. Catches prompt regressions. Gated behind `pytest -m eval`.
- **Layer A — Accuracy benchmark:** computes precision/recall/F1 over the same dataset plus ambiguous cases added later. Measures aggregate quality rather than asserting per-case. Built after Layer B.

This spec covers Layer B in full. Layer A is noted where it affects shared infrastructure.

---

## Directory Structure

```
eval/
├── __init__.py
└── cases.py              ← CriticCase dataclass + CASES dataset (shared)

tests/
└── test_critic_eval.py   ← regression guard; imports from eval/cases.py

pytest.ini                ← registers the eval marker
```

**Module responsibilities:**

- `eval/cases.py` — data layer only. Owns the `CriticCase` dataclass and the `CASES` list. No test logic, no LLM calls. Layer A's `eval/benchmark.py` will import from here without touching the test file.
- `tests/test_critic_eval.py` — assertion layer only. Parametrizes over `CASES`, constructs minimal `AgentState`, calls real `critic_node`, asserts result. Owns the `expected → needs_replan` translation.
- `pytest.ini` — registers the `eval` marker so `-m "not eval"` works cleanly in CI without unknown-marker warnings.

---

## `eval/cases.py`

### Dataclass

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class CriticCase:
    label: str                        # failure-mode slug — used as pytest id and report label
    query: str
    answer: str
    expected: Literal["good", "poor"] # human-readable; test owns translation to needs_replan bool
    reason: str                       # why this label exists — survives prompt refactors
```

**Design decisions:**

- `frozen=True` — cases are immutable; accidental mutation would silently corrupt a test run.
- `expected: Literal["good", "poor"]` — the dataset stays in human terms. A typo like `"poro"` fails at type-check time, not silently as a test that can never pass.
- `label` is keyed on **failure mode**, not content. Slugs like `hallucinated_claim` describe why the case exists and what decision boundary it probes. Content-describing slugs (`question_about_qdrant`) tell you nothing when a case flips after a prompt change.
- `reason` is a proper field, not a comment. It appears in the assertion failure message, making a failing case self-diagnosing without a manual re-run.

### Initial Dataset (8 cases)

Cases cover the critic's decision boundary from both sides. Every case is **deliberately non-borderline** — the critic should classify each correctly on every run with any reasonable model.

| Label | Expected | What makes it unambiguous |
|---|---|---|
| `correct_well_grounded` | good | Direct answer, matches retrieved context exactly |
| `correct_admits_gaps` | good | Correctly says context doesn't cover the topic |
| `vague_no_substance` | poor | Pure filler — no factual claim made at all |
| `incomplete_two_part_query` | poor | Second half of query completely ignored |
| `hallucinated_claim` | poor | States a specific fact not present in any retrieved chunk |
| `off_topic` | poor | Answers a different question entirely |
| `fabricated_source` | poor | Cites `[PDF — paper.pdf]` when no PDF was retrieved |
| `contradicts_context` | poor | Answer directly contradicts what the retrieved context says |

**Curation rule:** if a case is genuinely ambiguous to the dataset author, it does not belong here. It belongs in Layer A (benchmark), where aggregate pass rate is measured rather than a binary asserted. This is the primary defence against flapping.

**Non-determinism policy:** no N=3 retry logic. Retries patch cases that shouldn't be in the guard. If a case flaps, remove it from the guard and add it to the benchmark dataset instead.

---

## `tests/test_critic_eval.py`

```python
pytestmark = [pytest.mark.eval, pytest.mark.asyncio]

@pytest.mark.parametrize("case", CASES, ids=[c.label for c in CASES])
async def test_critic_eval(case):
    state: AgentState = {
        "query": case.query,
        "answer": case.answer,
        "iteration": 0,        # must be 0 — critic short-circuits at >= 2 without calling LLM
        "conversation_id": "",
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [],
        "critic_feedback": "",
        "needs_replan": False,
        "grounding_passed": False,
    }

    result = await critic_node(state)

    assert result["needs_replan"] == (case.expected == "poor"), (
        f"[{case.label}] expected={'poor' if case.expected == 'poor' else 'good'} "
        f"got needs_replan={result['needs_replan']}\n"
        f"Reason: {case.reason}\n"
        f"Critic feedback: {result.get('critic_feedback', '')}"
    )
```

**Key decisions:**

- `pytestmark` at module level applies both markers to every test — no per-test decorator noise.
- `ids=[c.label for c in CASES]` makes output read `test_critic_eval[hallucinated_claim] PASSED`, not `test_critic_eval[6]`.
- `iteration: 0` is the one field that matters beyond query/answer. The critic short-circuits at `>= 2` and returns `needs_replan=False` without calling the LLM, silently passing every "poor" case.
- Translation (`case.expected == "poor"`) lives here, not in `cases.py`. The dataset never sees a boolean; the test owns knowledge of the critic's internal API.
- The assertion message includes `case.reason` and `critic_feedback` — a failing case is self-diagnosing.

### Running

```bash
# Run the eval guard (hits real Groq API):
pytest -m eval -v

# Normal test run — skips eval:
pytest -m "not eval"

# Rerun only failing eval cases:
pytest -m eval --lf
```

---

## `pytest.ini` Change

Add the `eval` marker to the existing `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
markers =
    eval: real-LLM critic evaluation — run with pytest -m eval
```

---

## Layer A — Accuracy Benchmark (deferred)

Layer A shares `eval/cases.py` with no changes. It adds:

- `eval/benchmark.py` — standalone script (not a pytest test). Iterates over `CASES` plus an extended set of ambiguous cases (added to `cases.py` in a separate `BENCHMARK_CASES` list). Calls `critic_node` for each, collects `needs_replan` results, computes precision/recall/F1 on "poor" detection, prints a report.
- Ambiguous cases that were excluded from `CASES` live in `BENCHMARK_CASES` — same `CriticCase` dataclass, same fields.

The key distinction: the benchmark measures a **rate** (e.g., "critic correctly flags 87% of poor answers"), the guard asserts a **binary** (each case must pass every time).

---

## What This Does Not Cover

- Evaluation of other nodes (planner, synthesizer, grounding) — separate harnesses if needed.
- CI integration — running `pytest -m eval` in CI requires `GROQ_API_KEY` to be available as a secret. Not in scope for this implementation.
- Prompt tuning workflow — the guard tells you a prompt regression occurred; it does not suggest fixes.
