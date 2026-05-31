# Critic Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a regression guard that runs the real `critic_node` against a labeled dataset and asserts pass/fail per case, gated behind `pytest -m eval`.

**Architecture:** A shared `eval/cases.py` owns the `CriticCase` dataclass and the `CASES` list; `tests/test_critic_eval.py` parametrizes over that list, constructs minimal `AgentState`, calls the real Groq LLM via `critic_node`, and asserts `needs_replan` matches `expected`. The `eval/` module is separate from `tests/` so the future accuracy benchmark (`eval/benchmark.py`) can import the same dataset without coupling to pytest.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio (`asyncio_mode = auto`), `app.agent.nodes.critic.critic_node`, `app.agent.state.AgentState`, Groq API (real, not mocked).

**Spec:** `docs/superpowers/specs/2026-05-28-critic-eval-harness-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `eval/__init__.py` | Makes `eval` a package so `tests/` can import from it |
| Create | `eval/cases.py` | `CriticCase` frozen dataclass + `CASES` list (8 labeled cases) |
| Create | `tests/test_critic_eval.py` | Parametrized regression guard — real LLM, `@pytest.mark.eval` |
| Modify | `pytest.ini` | Register the `eval` marker |

---

## Task 1 — Create `eval/__init__.py` and `eval/cases.py`

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/cases.py`

- [ ] **Step 1: Create `eval/__init__.py`**

```python
```

(Empty file — just makes `eval` a package.)

Run:
```bash
mkdir -p /Users/divyanshu/Desktop/FDE_Projects/docchat/eval
touch /Users/divyanshu/Desktop/FDE_Projects/docchat/eval/__init__.py
```

- [ ] **Step 2: Create `eval/cases.py`**

Full file content:

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CriticCase:
    label: str                         # failure-mode slug — used as pytest id and report label
    query: str
    answer: str
    expected: Literal["good", "poor"]  # human-readable; test owns translation to needs_replan bool
    reason: str                        # why this label exists — survives prompt refactors


CASES: list[CriticCase] = [
    CriticCase(
        label="correct_well_grounded",
        query="What embedding model does DocChat use and what is the vector dimension?",
        answer=(
            "DocChat uses the BAAI/bge-small-en-v1.5 model via the fastembed ONNX runtime, "
            "producing 384-dimensional float32 vectors. The model runs entirely on CPU with no "
            "GPU required.\n\nSources:\n- [PDF — architecture.pdf p.2]"
        ),
        expected="good",
        reason="Complete, specific, cited answer with no ambiguity — critic should always approve",
    ),
    CriticCase(
        label="correct_admits_gaps",
        query="What is the internal training loss curve for BAAI/bge-small-en-v1.5?",
        answer=(
            "The provided context does not contain information about the training loss curve "
            "for BAAI/bge-small-en-v1.5. I cannot answer this question from the available sources."
        ),
        expected="good",
        reason="Appropriate acknowledgement of missing information rather than fabrication — critic should always approve",
    ),
    CriticCase(
        label="vague_no_substance",
        query="How does the retrieval pipeline work?",
        answer=(
            "The retrieval pipeline works by processing information in a systematic and efficient "
            "way to provide relevant and accurate results based on user queries using advanced techniques."
        ),
        expected="poor",
        reason="Pure filler with zero factual content — no mechanism described at all; critic should always flag",
    ),
    CriticCase(
        label="incomplete_two_part_query",
        query="What vector store does DocChat use and why was it chosen over ChromaDB?",
        answer=(
            "DocChat uses Qdrant as its vector store, which provides HNSW indexing for fast "
            "approximate nearest neighbour search via a REST API."
        ),
        expected="poor",
        reason="Addresses only the first part — the ChromaDB comparison is entirely ignored; critic should always flag",
    ),
    CriticCase(
        label="hallucinated_claim",
        query="How many nodes does the LangGraph agent have and what are they called?",
        answer=(
            "The LangGraph agent has 5 nodes: planner, retriever, synthesizer, grounding, and critic. "
            "It also contains 9 nodes in total, including 4 additional internal routing nodes "
            "for error recovery and state validation."
        ),
        expected="poor",
        reason="Answer contradicts itself (claims 5 nodes then 9 nodes) with fabricated details — internally inconsistent; critic should always flag",
    ),
    CriticCase(
        label="off_topic",
        query="How are PDF documents chunked before ingestion?",
        answer=(
            "YouTube videos are ingested by fetching transcripts via youtube-transcript-api. "
            "The transcript is split into overlapping chunks and embedded before storage in Qdrant."
        ),
        expected="poor",
        reason="Answers the YouTube ingestion question instead of PDF chunking — completely off topic; critic should always flag",
    ),
    CriticCase(
        label="fabricated_source",
        query="What does the research paper say about transformer self-attention?",
        answer=(
            "Sources:\n- [PDF — transformer_paper.pdf p.1]\n"
            "- [PDF — transformer_paper.pdf p.4]\n"
            "- [PDF — transformer_paper.pdf p.9]"
        ),
        expected="poor",
        reason="Response contains only citation markers with no actual content — query is entirely unaddressed",
    ),
    CriticCase(
        label="contradicts_context",
        query="Does DocChat support real-time token streaming?",
        answer=(
            "Yes, DocChat fully supports real-time token streaming via Server-Sent Events, "
            "delivering tokens word-by-word as the LLM generates them. "
            "However, DocChat does not support streaming at all — responses are returned as a "
            "complete JSON payload only after the full answer is generated."
        ),
        expected="poor",
        reason="Answer directly contradicts itself on the core question — self-contradictory answers cannot adequately address a query",
    ),
]
```

- [ ] **Step 3: Verify the file imports cleanly**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat && python -c "from eval.cases import CASES, CriticCase; print(f'{len(CASES)} cases loaded')"
```

Expected output:
```
8 cases loaded
```

---

## Task 2 — Create `tests/test_critic_eval.py`

**Files:**
- Create: `tests/test_critic_eval.py`

- [ ] **Step 1: Create the test file**

```python
import pytest
from eval.cases import CASES
from app.agent.nodes.critic import critic_node
from app.agent.state import AgentState

pytestmark = [pytest.mark.eval, pytest.mark.asyncio]


@pytest.mark.parametrize("case", CASES, ids=[c.label for c in CASES])
async def test_critic_eval(case):
    state: AgentState = {
        "query": case.query,
        "answer": case.answer,
        "iteration": 0,           # must be 0 — critic short-circuits at >= 2 without LLM call
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
        f"\n[{case.label}] "
        f"expected={'poor' if case.expected == 'poor' else 'good'} "
        f"got needs_replan={result['needs_replan']}\n"
        f"Reason: {case.reason}\n"
        f"Critic feedback: {result.get('critic_feedback', '')}"
    )
```

- [ ] **Step 2: Verify pytest can collect the tests (no LLM call yet)**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat && pytest tests/test_critic_eval.py --collect-only -q 2>&1 | head -20
```

Expected output (8 lines, one per case label):
```
tests/test_critic_eval.py::test_critic_eval[correct_well_grounded]
tests/test_critic_eval.py::test_critic_eval[correct_admits_gaps]
tests/test_critic_eval.py::test_critic_eval[vague_no_substance]
tests/test_critic_eval.py::test_critic_eval[incomplete_two_part_query]
tests/test_critic_eval.py::test_critic_eval[hallucinated_claim]
tests/test_critic_eval.py::test_critic_eval[off_topic]
tests/test_critic_eval.py::test_critic_eval[fabricated_source]
tests/test_critic_eval.py::test_critic_eval[contradicts_context]
8 tests
```

If you see an `unknown mark` warning for `eval`, proceed to Task 3 before running.

---

## Task 3 — Update `pytest.ini`

**Files:**
- Modify: `pytest.ini`

Current content:
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 1: Add the eval marker**

New content:
```ini
[pytest]
asyncio_mode = auto
markers =
    eval: real-LLM critic evaluation — run with pytest -m eval
```

- [ ] **Step 2: Verify marker is registered**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat && pytest --markers | grep eval
```

Expected output:
```
@pytest.mark.eval: real-LLM critic evaluation — run with pytest -m eval
```

- [ ] **Step 3: Verify normal test run still excludes eval cases**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat && pytest -m "not eval" --collect-only -q 2>&1 | grep test_critic_eval
```

Expected: no output (eval cases excluded from normal run).

- [ ] **Step 4: Verify `-m eval` selects exactly the 8 cases**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat && pytest -m eval --collect-only -q
```

Expected:
```
tests/test_critic_eval.py::test_critic_eval[correct_well_grounded]
...
8 tests
```

---

## Task 4 — Run the Eval Guard

> Requires `GROQ_API_KEY` to be set in the environment.

- [ ] **Step 1: Run all 8 eval cases against the real LLM**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat && pytest -m eval -v
```

Expected: all 8 cases PASSED. If any fail, read the assertion message — it prints `label`, `expected`, `needs_replan`, `reason`, and `critic_feedback` to diagnose immediately.

- [ ] **Step 2: If a case flaps or fails unexpectedly**

Check `critic_feedback` in the assertion output. If the case is genuinely borderline (critic is confused), remove it from `CASES` in `eval/cases.py` — it does not belong in the guard. Add it to `BENCHMARK_CASES` (future Layer A) instead.

- [ ] **Step 3: Run the full normal test suite to confirm nothing broke**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat && pytest -m "not eval" -v
```

Expected: all existing tests pass, no regressions.
