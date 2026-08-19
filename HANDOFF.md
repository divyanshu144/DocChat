# DocChat — Session Handoff

**Branch:** `feat/openai-sse-chat-quality`
**Last updated:** 2026-08-16
**Status:** Active development — green build, all work committed, nothing in flight.

---

## Current State

### Shipped and committed

- **Chat folders** — `Folder` model, `app/api/folders.py` CRUD, `app/api/conversations.py`
  (list/detail/move), full React 18 + Vite + TS SPA in `frontend/`. Committed.
- **Auth** — JWT signup/login/refresh/logout/me with bcrypt and refresh-token rotation.
- **MCP stdio server** — `app/mcp_server.py` exposing `query_documents`, `ingest_document`,
  `list_documents`. Spec + plan in `docs/superpowers/`. Committed `bcbb640`…`a281bcb`.
- **Chat history reaches the agent** (`98b030e`) — `conversation_history` is now on
  `AgentState`; planner and synthesizer format the last 10 messages into their prompts.
- **Ingestion idempotency** (`98b030e`) — deterministic `uuid5` source IDs from content
  hash (PDF) / canonical URL (web) / video ID (YouTube).
- **Docker fixes** — dependency ranges loosened (`dd8043b`), host ports moved to
  8081/5433 to avoid local conflicts (`a1cb13d`).

### Built in this branch (2026-07-29)

- **OpenAI primary provider** — `LLM_PROVIDER=openai` is supported through
  `app/services/llm.py` using the existing `httpx` dependency. OpenAI chat and SSE
  streaming both use `OPENAI_CHAT_MODEL` (`gpt-5.6-luna` default) and
  `OPENAI_API_KEY`.
- **Groq fallback safety** — Groq can use an optional same-provider
  `GROQ_FALLBACK_CHAT_MODEL`; when unset, retryable Groq failures can fall back to
  OpenAI if `FALLBACK_LLM_PROVIDER=openai` and `OPENAI_API_KEY` are configured.
- **SSE chat progress** — `/api/v1/chat` emits status events for planner/retriever/
  synthesizer/grounding/critic, then token events for the final answer.
- **No blank assistant messages** — chat preserves the last non-empty graph answer and
  refuses to save/stream empty assistant content. The frontend also avoids appending an
  empty bubble if a stream ends without tokens.
- **Grounding guard** — if the verifier returns meta-failure text like "I don't have an
  answer to clean", the original draft is preserved instead of showing that bad cleanup.
- **Better answer shape** — synthesizer/grounding prompts now ask for concise,
  structured prose with citations at the end, avoiding raw Markdown dumps.
- **Conversation continuity** — chat history ordering and optimistic local transcript
  handling keep previous turns visible after a new streamed answer.
- **PDF ingest progress** — async ingest jobs expose status/progress and the source
  drawer polls them instead of blocking silently.
- **UI fixes** — message pane scrolling/clipping fixed; response rendering now handles
  basic headings, lists, bold/code, and citation chips.
- **Benchmark diagnostics** — F1 now distinguishes defined zero from undefined, and the
  benchmark keeps per-case error rows while exiting 0 as documented.

### Built in this branch (2026-08-15 → 2026-08-16)

Three independent threads, committed separately.

**1. LangSmith tracing of the LLM calls**

- `app/agent/graph.py` — `_configure_langsmith()` now sets the modern `LANGSMITH_*`
  env vars (was the deprecated `LANGCHAIN_*`) and requires **both** a key and the new
  `langsmith_tracing` flag. `langsmith_endpoint` added for EU-region keys, which 403
  against the US host in a way that looks identical to a revoked key.
- `app/services/llm.py` — `@traceable` on `chat_complete` / `chat_stream`, plus
  `_tag_run()` (provider/model/streaming metadata) and `_join_stream()` (collapses
  streamed tokens into one output instead of hundreds of fragments). LangGraph traces
  nodes on its own but never sees the vendor SDK calls, so traces previously showed
  five node runs and zero prompts.
- `tests/conftest.py` — forces `LANGSMITH_TRACING=false` for the suite before anything
  imports `app`. `settings` is a module-level singleton, so conftest is the only window.
- `requirements.txt` — `langsmith` capped `<1.0.0`; the code calls `traceable(reduce_fn=)`
  and `run_helpers.get_current_run_tree` directly. Floor of `0.1.0` is **unverified** —
  it predates this code and is almost certainly too low. Installed and working: 0.10.11.

**2. Critic rejection sink**

- `app/agent/nodes/critic.py` — `_record_rejection()` appends each rejected draft to
  JSONL (timestamp, query, answer, context, verdict, reason). Gated on the new
  `critic_rejection_log` setting; blank disables it. This is the **only** capture point:
  on replan the synthesizer overwrites `state["answer"]` in place, so a rejected draft
  exists nowhere else, including the saved message. All failures are swallowed — a
  broken sink costs training data, never a user's answer. `_PROMPT` → public
  `CRITIC_PROMPT`.
- `tests/test_critic_rejection_sink.py` — 5 tests: disabled-by-default, append-not-
  truncate, approved-not-recorded, field shape, and unwritable-sink-never-raises.

  **Superseded 2026-08-19** — the single-record shape described above was half a
  training example. See the 2026-08-19 section for the paired record that replaced it.

**3. Corruption generator for the critic benchmark** (2026-08-16)

Spec: `docs/superpowers/specs/2026-08-15-corruption-gen-design.md`.

- `eval/corruptions.py` — four pure, deterministic transforms that take a `good` answer
  and return a `poor` one, so ground truth is inherited from the transform instead of a
  fresh human judgement: `contradict_self` (4), `strip_specifics` (4),
  `truncate_enumeration` (1), `off_topic_swap` (6). **15 generated cases**, N=20 total.
- `eval/benchmark.py` — runs generated cases alongside the hand-written ones and scores
  the two groups **separately**. Merging them would inflate the headline number and break
  comparability with every edge-case run recorded before they existed. Adds a
  per-transform recall breakdown.
- `eval/cases.py` — `CriticCase.context` is now correctly documented as **authoring
  provenance**; the previous comment implied the critic reads it.
- `tests/test_corruptions.py` — 23 tests, weighted toward what a transform must never do.

**The finding that shaped this:** `CRITIC_PROMPT` interpolates only Query and Answer —
the critic never receives the retrieved context. So `contradict_source` (the transform
`CriticCase.context` was originally added for) is unbuildable: the critic could not get
such a case right at any quality level. `overclaim` and `drop_citation` were cut for the
same reason — a fabricated version number is indistinguishable from a real one without
the source, and a de-hedged answer reads *better*, so both would have injected
mislabelled cases. `strip_specifics` and `off_topic_swap` replaced them.

**Rule this establishes:** a corruption is sound only if a *correct* critic, given just
the query and the answer, would call the result poor. "Degraded" is not enough.

### Built in this branch (2026-08-19) — fine-tuning readiness

Spec: `docs/superpowers/specs/2026-08-19-critic-gap-admission-design.md`.

Everything below exists to make a future training corpus trustworthy. Order was forced:
the critic is the labeller, so its bias had to be fixed *before* collection starts.

**Critic gap-admission fixed — the long-standing blind spot is closed.**
`CRITIC_PROMPT` now judges in two ordered steps: step 1 rejects self-contradiction,
vagueness and off-topic outright ("nothing excuses these"); step 2 applies a
disclosure test to *missing information only* — an answer that names what the context
lacks is good. Measured: Layer A edge cases **4/5 → 5/5, precision 0.50 → 1.00, recall
held at 1.00**; generated corruptions held at 15/15; Layer B 8/8.

**Sink now writes complete training pairs.** The old record was the rejected draft
alone — half an example, useless for supervised fine-tuning (wants the preferred output)
and for preference training (wants both sides). `pending_rejection` now rides the state
from the rejecting pass to the pass that knows the replacement, and one record is written
carrying `rejection_id`, `conversation_id`, both answers, and the reason. Incomplete
pairs are dropped rather than written as halves to be filtered later.

**`temperature` threaded through the provider seam**, pinned to 0 for the classification
nodes (critic, planner) via `settings.classification_temperature`. The synthesizer is
deliberately left sampling. Omitting the argument sends no temperature at all, so every
pre-existing caller is unchanged.

**Test-infrastructure bug fixed that had made `pytest -m eval` useless.**
`app.services.llm` caches one client per provider and its connection pool binds to the
event loop that created it; pytest-asyncio gives each test a fresh loop, so 4 of 8 eval
cases failed with `RuntimeError: Event loop is closed` — confirmed pre-existing by
stashing. `tests/conftest.py` now resets the cache per test. **Layer B went 4 failed/4
passed → 8 passed.** One failure that looked like a real critic disagreement was a
symptom of this.

**`_report` no longer prints precision/F1 for an all-poor group** — FP and TN are zero by
construction there, so precision was pinned at 1.00 and measured nothing.

### Repo hygiene (2026-07-28)

- `postgres_data/` and `qdrant_data/` removed from git and gitignored. Both still exist
  on disk and are still bind-mounted by `docker-compose.yml` — local DBs are unaffected.
- Branch history rewritten with `git filter-repo` to purge those blobs, force-pushed,
  and garbage-collected. Verified tree-identical to the pre-rewrite tip (`e963dce…`),
  all 30 commits preserved. `.git` went **48M → 6.8M**; `git fsck` clean; all 6 sibling
  worktrees still valid. The `backup/pre-filter-repo` rollback branch has been deleted —
  the old history is gone for good.
- Ruff added as the lint gate (`pyproject.toml`), clean.
- `tasks/` scaffolding created; `CLAUDE.md` now documents the session files and DoD.

### Environment rebuilt (2026-07-28)

- **venv rebuilt from scratch.** It had been created at the project's old
  `FDE_Projects` path, so `activate` silently fell through to anaconda. `activate`,
  `pip`, `pytest` and `ruff` all resolve correctly now.
- **FastAPI↔Starlette clash fixed.** The venv held `fastapi 0.104.1` against
  `starlette 1.2.1`; a clean resolve gave `fastapi 0.140.13` + `starlette 1.3.1`.
- **Two broken requirements found and fixed** — `mcp` capped `<2.0.0` (2.x removed
  `mcp.server.fastmcp.FastMCP`), and `aiosqlite` declared for the first time despite
  two test modules depending on it.
- Suite went **45 passed / 4 failed / 12 errors → 61 passed, 0 failed.**

---

## Next Action (immediately actionable)

**Enable the sink and let data accumulate.** Set `CRITIC_REJECTION_LOG=./data/critic_rejections.jsonl`.
The three reasons to wait are gone: records are now complete pairs, they carry a
correlation ID, and the labeller no longer punishes honest gap-admission. Nothing has
been collected yet — the file does not exist.

**Two things to know before trusting any number from a collection run:**

1. **`gpt-5.6-luna` rejects `temperature=0`** — "Only the default (1) value is
   supported." The pin is silently dropped and the model samples, so verdicts still move
   between runs. Verified: on `LLM_PROVIDER=groq` with `qwen/qwen3.6-27b` two runs were
   byte-identical across all 20 verdicts; on gpt-5.6-luna they disagreed. Reproducible
   eval needs a model that accepts the parameter.
2. **Groq's default model was dead.** `llama-3.3-70b-versatile` is decommissioned and
   404s; the Groq path failed entirely on defaults. Now `openai/gpt-oss-120b`. Note
   `qwen/qwen3.6-27b` rates *everything* good (recall 0.00) — it is useless as a critic
   and only served as a determinism testbed.

After that, the open behaviour change is **giving `CRITIC_PROMPT` the retrieved
context**. It would let the critic verify a claimed gap is real rather than taking the
answer's word for it, and unlocks the `contradict_source` corruption. Wants its own spec.

---

## Critic Eval — Both Layers Complete

- **Layer B (regression guard)** — `tests/test_critic_eval.py`, 8 cases, `@pytest.mark.eval`.
- **Layer A (diagnostic)** — `eval/benchmark.py` + `BENCHMARK_CASES`, built 2026-07-28.

```bash
python eval/benchmark.py     # needs GROQ_API_KEY; always exits 0
```

**First real run — 3/5 correct.** TP=1 FP=2 FN=0 TN=2 → precision 0.33, recall 1.00,
F1 0.50. Exactly the profile the spec predicted.

Both failures were the two gap-admitting cases (`correct_admits_gaps`,
`admits_gaps_with_partial_answer`), with the critic's own feedback confirming why:

> "The answer does not provide any specific information about the internal training loss
> curve … only stating that it is not available in the provided context."

This **empirically confirms the design tension** first noted when Layer B was built: the
critic's prompt defines "good" as *"addresses the full query"*, so a correct "I cannot
answer from this context" is structurally unrepresentable as good. Recall 1.00 with
precision 0.33 is the signature of a critic that over-fires rather than one that misses.

Read the numbers as **edge-case precision only** — N=5, stacked toward the known failure
mode. Expand to 20–30 cases before quoting externally.

**FIXED 2026-08-19.** The two-step prompt rewrite closed this. Edge cases now 5/5,
precision 1.00, recall still 1.00; generated corruptions 15/15; Layer B 8/8. The history
above is kept because it is the measurement that justified the change — see
`docs/superpowers/specs/2026-08-19-critic-gap-admission-design.md`, including the first
draft that fixed the edge cases but broke the corruption set.

---

## LLM Provider Seam (2026-07-29)

`app/services/llm.py` is now provider-agnostic. Switching backends is a config change:

```bash
LLM_PROVIDER=groq       # uses CHAT_MODEL + optional Groq fallback + GROQ_API_KEY
LLM_PROVIDER=openai     # active local path; uses OPENAI_CHAT_MODEL + OPENAI_API_KEY
LLM_PROVIDER=mistral    # uses MISTRAL_CHAT_MODEL + MISTRAL_API_KEY
```

Per-provider model names are separate settings, so switching provider is one variable,
not two. SDKs are imported lazily — an unused provider's package is never loaded. The
agent nodes are untouched; they still call `chat_complete` / `chat_stream`.
Groq can retry retryable chat failures against `GROQ_FALLBACK_CHAT_MODEL` when that
same-provider fallback is set. If the Groq path still fails with a retryable error and
`OPENAI_API_KEY` is configured, it falls back to the OpenAI provider using
`OPENAI_CHAT_MODEL` (`gpt-5.6-luna` by default).

**Purpose:** run the same eval suite against multiple backends and compare. Local `.env`
currently uses OpenAI primary; `.env` is ignored and not committed.

**Mistral path is verified structurally, not live** — client construction and method
surface are asserted against the real SDK (mistralai 2.8.0), but no request has been made
against the Mistral API. Set `MISTRAL_API_KEY` and run `python eval/benchmark.py` to
exercise it for real.

### Blocker for any A/B comparison

**Partly resolved 2026-08-19 — now a model constraint, not a code one.** The
classification nodes ask for `temperature=0`, but a model that rejects it is served at
its default anyway (see Next Action). Pick a model that accepts the parameter before
comparing anything. The original finding, which motivated the work:

Nothing sets `temperature`, so every node samples at the provider default.
Two back-to-back runs of the *identical* build scored 3/5 (P=0.33) then 2/5 (P=0.25).
At N=5 a single flip moves precision ~8 points — **the noise currently exceeds the
signal you'd be measuring.** Before comparing providers or a fine-tuned model:

1. Pin `temperature=0` for the classification nodes (critic, planner).
2. Average several runs rather than trusting one.
3. Expand the dataset — N=5 is a seed, as the spec says.

---

## Open Work

### Other

- **Chat-folders plan checkboxes** — `2026-05-11-chat-folders.md` shows 5/42 checked
  though the code shipped. Check off or archive.
- **`scripts/` lint debt** — 22 findings, currently excluded in `pyproject.toml`.
- **Ingestion has no version cleanup** — re-ingesting a shorter document orphans tail
  chunks.

---

## Verification Baseline

```bash
source venv/bin/activate
ruff check .                # clean
pytest -m "not eval" -q     # 153 passed, 0 failed
```

Was 109 until the critic rejection sink added 5 tests (2026-08-15).

**Both gates are green.** There are no known-failing tests, so any red is a real
regression — don't dismiss one as pre-existing without diffing against a stash.

---

## In-Flight Files

The branch contains app, frontend, static bundle, tests, and docs changes for the
2026-07-29 OpenAI/SSE/ingest-progress/chat-quality work. No secrets should be staged;
`.env` is ignored.

---

## Open Questions

**Resume/interview bullet.** Draft:

> "Architected a 5-node LangGraph pipeline (Planner, Retriever, Synthesizer, Grounding,
> Critic) with bounded critic-feedback retry loops — an evaluator-optimizer pattern that
> measurably lifted weak-answer quality on a [X]-question eval set."

The gap: "measurably lifted" needs a before/after measurement nobody has run. The eval
harness measures *critic accuracy*, not *end-to-end quality lift*. Either:

1. **Safe today:** "...built a 13-case regression and diagnostic harness to validate
   critic accuracy" — honest, no lift claim.
2. **After one experiment:** run 20 "poor" queries with the critic loop disabled vs.
   enabled, count improvements; `[X]` becomes that count and the claim is honest.

---

## Key Files

```
app/agent/           planner · retriever · synthesizer · grounding · critic
app/api/             auth · chat · ingest · folders · conversations
app/services/        ingestion/{pdf,youtube,web}.py · llm.py · embedder.py
eval/cases.py        CASES (8, regression guard) + BENCHMARK_CASES (5, diagnostic)
eval/benchmark.py    Layer A diagnostic — python eval/benchmark.py
tasks/               todo.md · lessons.md · agent_memory.md
docs/superpowers/    specs/ · plans/
pyproject.toml       ruff config
RESOLVER.md          keyword → skill routing table
```
