# DocChat — Session Handoff

**Branch:** `feat/chat-folders` (pushed, in sync with `origin`)
**Last updated:** 2026-07-28
**Status:** Active development — green build, no blockers

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

Nothing blocking. Layer A shipped 2026-07-28 and surfaced a concrete finding — the
critic cannot represent a correct "I can't answer from this context" as good. The
highest-value next task is the critic prompt fix described under Critic Eval below;
it changes agent behaviour, so write a spec first.

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

**Next step if pursuing this:** the fix is a prompt change to `app/agent/nodes/critic.py`
carving out appropriate gap-admission from "poor", then re-running both layers. That is a
behaviour change to the agent, so it wants its own spec.

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
pytest -m "not eval" -q     # 73 passed, 0 failed
```

**Both gates are green.** There are no known-failing tests, so any red is a real
regression — don't dismiss one as pre-existing without diffing against a stash.

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
eval/cases.py        CASES (8, regression guard) + BENCHMARK_CASES (5, diagnostic)
eval/benchmark.py    Layer A diagnostic — python eval/benchmark.py
tasks/               todo.md · lessons.md · agent_memory.md
docs/superpowers/    specs/ · plans/
pyproject.toml       ruff config
RESOLVER.md          keyword → skill routing table
```
