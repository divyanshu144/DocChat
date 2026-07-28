# DocChat — Session Handoff

**Branch:** `feat/chat-folders`
**Last updated:** 2026-07-28
**Status:** Active development — one manual step pending (see Next Action)

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

### Repo hygiene (2026-07-28)

- `postgres_data/` and `qdrant_data/` removed from git and gitignored. Both still exist
  on disk and are still bind-mounted by `docker-compose.yml` — local DBs are unaffected.
- Branch history rewritten with `git filter-repo` to purge those blobs. Verified
  tree-identical to the pre-rewrite tip (`e963dce…`), all 30 commits preserved.
  Old tip `c874b73` → new tip `bee1cf6`.
- Ruff added as the lint gate (`pyproject.toml`), currently clean.
- `tasks/` scaffolding created; `CLAUDE.md` now documents the session files and DoD.

---

## Next Action (immediately actionable)

**1. Force-push the rewritten branch.** Blocked for the agent by the
`pre-tool-use.sh` guard — run manually:

```bash
git push --force-with-lease=feat/chat-folders:a1cb13d89388248b35f74963c2c9a580c921dc0d \
         origin feat/chat-folders
```

**2. Then reclaim disk** (only after the push succeeds):

```bash
git branch -D backup/pre-filter-repo
git fetch --prune && git reflog expire --expire=now --all && git gc --prune=now --aggressive
```

Expect `.git` 48M → ~5M. **`backup/pre-filter-repo` is the only rollback path — keep it
until the push lands.** Roll back with `git reset --hard backup/pre-filter-repo`.

---

## Open Work

### Critic Accuracy Benchmark — Layer A — SPEC DONE, NOT BUILT

Verified still unbuilt: `eval/benchmark.py` does not exist, `BENCHMARK_CASES` appears
0 times in `eval/cases.py`.

Standalone `python eval/benchmark.py` (not pytest) running 5 ambiguous edge cases against
real Groq, printing precision/recall/F1 on "poor" detection.

| Label | Expected | Why borderline |
|---|---|---|
| `correct_admits_gaps` | good | Critic over-fires on "I don't know from context" |
| `hedged_but_correct` | good | Correct facts, uncertainty language trips the critic |
| `partially_addresses_multipart` | poor | Strategy answered, specific numbers omitted |
| `correct_but_terse` | good | One-sentence correct answer; critic may want depth |
| `admits_gaps_with_partial_answer` | good | Half answered + honest gap admission |

Framing baked into the spec: N=5 is a seed dataset, not a benchmark — one flip = 33pt
precision swing. Label output `Precision (edge cases)`. Footer: "Expand to 20–30 cases
before quoting externally."

**Spec:** `docs/superpowers/specs/2026-05-28-critic-benchmark-design.md`
**To continue:** invoke `writing-plans` on the spec, then implement.

### Other

- **Fix the FastAPI↔Starlette clash** — 16 tests fail at collection. Pin a compatible
  pair and rebuild the venv. This also fixes the broken-path venv (see below).
- **Chat-folders plan checkboxes** — `2026-05-11-chat-folders.md` shows 5/42 checked
  though the code shipped. Check off or archive.
- **`scripts/` lint debt** — 22 findings, currently excluded in `pyproject.toml`.
- **Ingestion has no version cleanup** — re-ingesting a shorter document orphans tail
  chunks.

---

## Verification Baseline

```bash
venv/bin/python -m ruff check .              # clean — must stay clean
venv/bin/python -m pytest -m "not eval" -q   # 45 passed, 4 failed, 12 errors
```

The 4 failures + 12 errors are all `TypeError: Router.__init__() got an unexpected
keyword argument 'on_startup'` — a FastAPI/Starlette version clash introduced when
`dd8043b` loosened the pins. **Not application bugs.** Diff against this baseline before
concluding you caused a regression.

**`source venv/bin/activate` is broken** — the venv was built at
`/Users/divyanshu/Desktop/FDE_Projects/docchat` and the project moved. Activation
silently resolves to anaconda; `venv/bin/pip` and `venv/bin/pytest` fail with
`bad interpreter`. Use `venv/bin/python -m <tool>`. Full detail in `tasks/lessons.md`.

---

## In-Flight Files

None — working tree is clean apart from this documentation work.

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
eval/cases.py        CASES (8, regression guard) + BENCHMARK_CASES (5, to add)
tasks/               todo.md · lessons.md · agent_memory.md
docs/superpowers/    specs/ · plans/
pyproject.toml       ruff config
RESOLVER.md          keyword → skill routing table
```
