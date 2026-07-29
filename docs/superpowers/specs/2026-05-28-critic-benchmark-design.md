# Critic Accuracy Benchmark (Layer A) — Design Spec

**Date:** 2026-05-28
**Branch:** feat/chat-folders
**Status:** Approved, ready for implementation
**Depends on:** `docs/superpowers/specs/2026-05-28-critic-eval-harness-design.md` (Layer B)

---

## Overview

Layer A is a standalone diagnostic script for the `critic_node`. It measures precision/recall/F1 over a set of **ambiguous edge cases** — cases that sit near the critic's decision boundary and are unsuitable for binary regression assertions.

It is distinct from Layer B (regression guard) in one key way: it measures a **rate**, not a **binary**. A case that the critic gets wrong does not fail a test; it contributes to the aggregate score. This makes it safe to run with borderline cases that would flap in the guard.

**Important framing:** The initial dataset of 5 cases is a seed for investigation, not a statistically meaningful benchmark. With N=5, a single case flip moves precision by ~33 points. The dataset is also deliberately stacked toward the critic's known failure modes (over-firing on hedged/partial answers), so the numbers measure **edge-case precision** — not overall critic quality in production. Expand to 20–30 cases before quoting these numbers externally.

---

## Dataset

Layer A introduces `BENCHMARK_CASES` — a second `list[CriticCase]` in `eval/cases.py`, using the same `CriticCase` frozen dataclass already defined there. The two lists stay independent:

- `CASES` — imported by `tests/test_critic_eval.py` (regression guard only)
- `BENCHMARK_CASES` — imported by `eval/benchmark.py` (benchmark only)

Neither list imports the other. No change to `CriticCase` or `CASES`.

### Initial 5 Cases

Each `expected` value is the human-expert label. The benchmark measures how often the critic agrees.

| Label | Expected | Why borderline |
|---|---|---|
| `correct_admits_gaps` | good | Critic reads "doesn't address query" as poor; human reads it as correct RAG behavior |
| `hedged_but_correct` | good | Directionally correct but hedged — critic may flag as vague |
| `partially_addresses_multipart` | poor | Strategy answered, specific numbers omitted — critic may call it good enough |
| `correct_but_terse` | good | One-sentence correct answer — critic may expect elaboration |
| `admits_gaps_with_partial_answer` | good | First part answered, second part honestly acknowledged as missing |

4 expected=`good`, 1 expected=`poor`. Balance reflects the critic's known over-firing bias on "poor" — most ambiguous cases land in the false-positive region.

---

## Files

| Action | Path | Responsibility |
|---|---|---|
| Modify | `eval/cases.py` | Add `BENCHMARK_CASES: list[CriticCase]` below `CASES` |
| Create | `eval/benchmark.py` | Standalone async script — runs cases, prints report |

---

## `eval/cases.py` Addition

Append below `CASES`:

```python
BENCHMARK_CASES: list[CriticCase] = [
    CriticCase(
        label="correct_admits_gaps",
        query="What is the internal training loss curve for BAAI/bge-small-en-v1.5?",
        answer=(
            "The provided context does not contain information about the training loss curve "
            "for BAAI/bge-small-en-v1.5. I cannot answer this question from the available sources."
        ),
        expected="good",
        reason="Appropriate acknowledgement of missing context — borderline because critic reads "
               "'doesn't address query' as poor, but human expert reads it as correct RAG behavior",
    ),
    CriticCase(
        label="hedged_but_correct",
        query="What database does DocChat use to store conversations?",
        answer=(
            "DocChat appears to use PostgreSQL for storing conversations, though this may depend "
            "on the specific deployment configuration. The system likely uses an async SQLAlchemy "
            "connection, but I'm not entirely certain of the exact setup."
        ),
        expected="good",
        reason="Directionally correct (PostgreSQL + SQLAlchemy) but hedged — critic may flag as "
               "vague despite the factual content being present",
    ),
    CriticCase(
        label="partially_addresses_multipart",
        query="What chunking strategy does DocChat use for PDFs and what are the chunk size and overlap?",
        answer=(
            "DocChat uses LangChain's RecursiveCharacterTextSplitter, which splits text recursively "
            "using paragraph breaks, line breaks, and sentence boundaries as separators."
        ),
        expected="poor",
        reason="Correctly describes the strategy but omits the specific numbers explicitly asked "
               "for — borderline because the strategy part IS answered",
    ),
    CriticCase(
        label="correct_but_terse",
        query="What LLM does DocChat use for generating answers?",
        answer="DocChat uses the Groq API with the llama-3.3-70b-versatile model.",
        expected="good",
        reason="One sentence, directly correct — borderline because critic may expect elaboration "
               "or flag brevity as insufficient",
    ),
    CriticCase(
        label="admits_gaps_with_partial_answer",
        query="What are the access token and refresh token expiry times in DocChat?",
        answer=(
            "Access tokens expire after 30 minutes. I don't have information about the refresh "
            "token expiry time in the available context."
        ),
        expected="good",
        reason="First part answered correctly, second part honestly acknowledged as missing — "
               "borderline because the query is only half-answered",
    ),
]
```

---

## `eval/benchmark.py`

Standalone async script. Three focused functions plus `main()`.

```
run_case(case)       → builds minimal AgentState, calls critic_node, returns result dict
_compute_metrics(results) → TP/FP/FN/TN → precision, recall, F1
main()               → orchestrates run_case per case, prints per-case lines, prints aggregate
```

### Metrics

"Positive" class is `"poor"` — the critic's job is to detect poor answers and trigger replanning.

- **TP**: expected=poor, critic flags poor — correct detection
- **FP**: expected=good, critic flags poor — false alarm (over-firing)
- **FN**: expected=poor, critic passes good — missed poor answer
- **TN**: expected=good, critic passes good — correct pass

```
Precision = TP / (TP + FP)   — of cases flagged poor, how many actually were?
Recall    = TP / (TP + FN)   — of actually poor cases, how many were caught?
F1        = 2·P·R / (P + R)
```

`N/A` when denominator is zero (no poor cases → recall undefined; nothing flagged → precision undefined).

### Report Format

```
Diagnostic run — 5 ambiguous edge cases (seed dataset, not statistically significant)

[PASS] correct_admits_gaps              expected=good  got=good
[FAIL] hedged_but_correct               expected=good  got=poor  | "The answer is hedged..."
[PASS] partially_addresses_multipart    expected=poor  got=poor
[PASS] correct_but_terse                expected=good  got=good
[FAIL] admits_gaps_with_partial_answer  expected=good  got=poor  | "The answer is incomplete"

─────────────────────────────────────────────────────
3 / 5 correct on edge cases

  TP (correctly flagged poor)  : 1
  FP (good flagged as poor)    : 2
  FN (poor missed as good)     : 0
  TN (correctly passed good)   : 2

  Precision (edge cases) : 0.33   (of cases flagged poor, how many were?)
  Recall    (edge cases) : 1.00   (of poor cases, how many were caught?)
  F1        (edge cases) : 0.50

  Note: N=5 — expand to 20–30 cases before quoting these numbers externally.
        Dataset is stacked toward the Critic's known failure modes (over-firing on
        hedged/partial answers). These numbers measure edge-case precision, not
        overall Critic quality in production.
─────────────────────────────────────────────────────
```

`[FAIL]` lines include the critic's feedback string so a wrong verdict is self-diagnosing without a re-run.

Cases run sequentially. No concurrent LLM calls — 5 cases at ~1s each needs no parallelism.

---

## Running

```bash
# Requires GROQ_API_KEY in environment
python eval/benchmark.py
```

No pytest. No markers. No flags. The script exits 0 regardless of score — it measures, it does not assert.

---

## What This Does Not Cover

- Saving results over time (no JSON output, no history file) — out of scope for this iteration
- Parallelising LLM calls — unnecessary at 5 cases
- CI integration — benchmark is a developer tool, not a CI gate
- Evaluation of other nodes — separate harnesses if needed
