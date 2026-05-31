# DocChat — Session Handoff

**Branch:** `feat/chat-folders`
**Last session:** 2026-05-28/29
**Status:** Active development

---

## What Is Done

### 1. Chat Folders (feat/chat-folders) — Code Complete, Not Committed
The entire chat-folders feature is implemented in the working tree but uncommitted. The plan at `docs/superpowers/plans/2026-05-11-chat-folders.md` shows 5/42 tasks checked, but the code is shipped. Files in working tree:

- `app/models/conversation.py` — `Folder` model, `folder_id` FK on `Conversation`
- `app/api/folders.py` — full CRUD (create, list, rename, delete)
- `app/api/conversations.py` — list, detail, move-to-folder
- `app/api/auth.py` — JWT signup/login/refresh/logout/me
- `frontend/` — full React 18 + Vite + TypeScript SPA
  - Sidebar with folder tree, drag-and-drop, context menu
  - SourcesDrawer (right panel, ingest + source selection)
  - ChatPanel with SSE streaming and filter chips
- `app/static/index.html` — updated SPA entry point

**Nothing is committed.** All changes are unstaged.

---

### 2. Critic Eval Harness — Layer B (Regression Guard) — COMPLETE ✓

**Files created:**
- `eval/__init__.py`
- `eval/cases.py` — `CriticCase` frozen dataclass + `CASES` (8 labeled cases)
- `tests/test_critic_eval.py` — parametrized real-LLM guard, `@pytest.mark.eval`
- `pytest.ini` — `eval` marker registered

**Run with:**
```bash
pytest -m eval -v          # real Groq LLM, hits API
pytest -m "not eval" -v    # normal suite, skips eval
```

**Last result:** 8/8 PASS

**One finding logged:** `correct_admits_gaps` ("I cannot answer from context") flipped — critic rates it `poor` because its prompt defines "good" as "addresses the full query." This case was moved to `BENCHMARK_CASES` (Layer A). It reveals a real design tension: the critic can't distinguish appropriate "no context" from a poor answer.

**Spec:** `docs/superpowers/specs/2026-05-28-critic-eval-harness-design.md`
**Plan:** `docs/superpowers/plans/2026-05-28-critic-eval-harness.md`

---

### 3. Critic Accuracy Benchmark — Layer A (Diagnostic Script) — SPEC DONE, NOT BUILT

**Status:** Spec written and approved. Brainstorming complete. Implementation plan NOT written. Code NOT written.

**What it is:** A standalone `python eval/benchmark.py` script (not pytest) that runs 5 ambiguous edge cases against the real Groq LLM and prints precision/recall/F1 on "poor" detection.

**What needs to be built:**
1. Add `BENCHMARK_CASES` list to `eval/cases.py` (5 cases — see spec)
2. Create `eval/benchmark.py` — `run_case()`, `_compute_metrics()`, `main()`

**5 BENCHMARK_CASES to add to `eval/cases.py`:**

| Label | Expected | Why borderline |
|---|---|---|
| `correct_admits_gaps` | good | Critic over-fires on "I don't know from context" |
| `hedged_but_correct` | good | Correct facts but uncertainty language triggers critic |
| `partially_addresses_multipart` | poor | Strategy answered but specific numbers omitted |
| `correct_but_terse` | good | One-sentence correct answer, critic may want depth |
| `admits_gaps_with_partial_answer` | good | Half answered + honest gap admission |

**IMPORTANT framing (baked into the spec):**
- N=5 is a seed dataset, not a statistically meaningful benchmark. A single flip = 33pt precision swing.
- Dataset is stacked toward the critic's known failure mode (over-firing on hedged/partial answers).
- Output labels metrics as `Precision (edge cases)` not just `Precision`.
- Footer note: "Expand to 20–30 cases before quoting these numbers externally."

**Spec:** `docs/superpowers/specs/2026-05-28-critic-benchmark-design.md`

**To continue:** invoke `writing-plans` skill with the spec, then implement.

---

## Open Question: Resume/Interview Bullet

Draft in discussion:
> "Architected a 5-node LangGraph pipeline (Planner, Retriever, Synthesizer, Grounding, Critic) with bounded critic-feedback retry loops — an evaluator-optimizer pattern that measurably lifted weak-answer quality on a [X]-question eval set."

**The gap:** "Measurably lifted" requires a before/after measurement that hasn't been done. The eval harness measures *critic accuracy*, not *end-to-end quality lift*.

**Two options:**
1. **Use today (safe):** "...built a 13-case regression and diagnostic harness to validate critic accuracy" — honest, no lift claim needed.
2. **Use after one experiment:** Run 20 "poor" queries with critic loop disabled vs enabled, count improvements. Then `[X]` = that count and the lift claim is honest.

---

## What To Do Next (In Order)

1. **Commit all uncommitted work** — the working tree has months of work unstaged
2. **Build Layer A** — invoke `writing-plans` on `2026-05-28-critic-benchmark-design.md`, implement `BENCHMARK_CASES` + `eval/benchmark.py`, run it
3. **Decide on resume bullet** — either use the safe version now or run the quality-lift experiment
4. **Update chat-folders plan checkboxes** — `2026-05-11-chat-folders.md` shows 5/42 checked but code is shipped; either check them off or archive the plan

---

## Key Files Reference

```
eval/
├── __init__.py
└── cases.py              ← CASES (8, guard) + BENCHMARK_CASES (5, to add)

tests/
└── test_critic_eval.py   ← regression guard

docs/superpowers/
├── specs/
│   ├── 2026-05-28-critic-eval-harness-design.md    ← Layer B spec
│   └── 2026-05-28-critic-benchmark-design.md        ← Layer A spec (approved)
└── plans/
    ├── 2026-05-11-chat-folders.md                   ← folders plan (code done, boxes unchecked)
    └── 2026-05-28-critic-eval-harness.md            ← Layer B plan (complete)
```

---

## Running Things

```bash
source venv/bin/activate

# Normal test suite (no LLM calls)
pytest -m "not eval" -v

# Critic regression guard (real Groq API)
pytest -m eval -v

# Critic benchmark diagnostic (once built)
python eval/benchmark.py

# Dev server
uvicorn app.main:app --reload

# Full stack
docker compose up --build
```
