# Task: inference completion + codebase hardening (chore/inference-complete-and-hardening)

Plan: [completion plan](../docs/superpowers/plans/2026-10-01-hardening-completion.md).
Original plan: `/Users/divyanshu/.claude/plans/silly-forging-deer.md`.
Branch: `chore/inference-complete-and-hardening`, pushed and merged without conflicts
into the repository's default `master` branch. Merge `77a2abb` is on `origin/master`.
Current checks: 368 non-eval Python tests passed, 8 live evals deselected, Ruff clean;
frontend 3 files / 6 tests passed. Approved GPT-5.5 diagnostic: 20/20 cases passed.

## Part 1 - finish the inference work

- [x] 1. `--groq-model` override in `eval/inference_benchmark.py`, mirrors `--openai-model`.
      Tests in `tests/test_inference_benchmark_live_logic.py`. 257 to 259 passed.
- [x] 2. Blocked e2e check done. source_chunks was empty on this branch (legacy
      collections have old data but retriever never reads them). Ingested the 1 unique
      leftover PDF + a Wikipedia page, ran a real chat query against a host-side
      instance of current code. All 5 nodes ran clean, no JSON parse failures, no
      context-length errors, one transient Groq 429 auto-retried fine. Details in
      HANDOFF.md.
- [x] 3. Found and fixed a stale comment: the constant still said "UNVERIFIED" even
      though the module docstring already said verified against v0.30.0. Fixed, added
      a per-field note on which names matched as-is.
- [x] 4a. Phase 3 spec written (`docs/superpowers/specs/2026-10-01-quantization-comparison-design.md`).
      New `eval/quantization_compare.py` + 13 dry-run tests, no pod. 259 to 272 passed.
- [x] 4b. Phase 4 spec written (`docs/superpowers/specs/2026-10-01-batching-proof-design.md`).
      New `--serial` flag + `mode` row tag in `eval/inference_benchmark.py`, 4 dry-run
      tests including one that actually proves no overlap, not just call count. 272 to
      276 passed. **STOPPED here, waiting for a go before any pod for 4a or 4b.**
- [x] 5. `docs/inference-writeup.md` written from `eval/BENCHMARK_RESULTS.md` numbers
      only. README's Inference benchmarking section updated to match (dropped the "no
      such ceiling" overclaim, linked the write-up). 276 passed, no code changed.
- [x] 6. Asked about network volume `owdj19ss50`. User chose to keep it (Phase 3/4
      would reuse its cached weights). Not deleted.

**Part 1 status: items 1, 2, 3, 5, 6 done. Item 4 (Phase 3 + Phase 4) is spec-plus-
dry-run-tests complete, STOPPED, waiting for a go before any live pod sweep.**

**Phase 3 live sweep: discussion started 2026-10-01, then paused by the user before
answering. See the "PAUSED" section at the top of HANDOFF.md for the three open
questions (concurrency levels, GPU choice, cost cap) and the facts already confirmed
(both AWQ/GPTQ-Int4 repos are real, L40S stock/pricing, the cached volume probably
won't help this run). No pod created. Resume by re-asking those questions, not by
assuming the recommended defaults.**

## Part 2 - codebase review fixes, in order

### A. Auth gaps
- [x] `Depends(get_current_user)` on all `app/api/ingest.py` (9) + `app/api/folders.py`
      (4) routes. 13 new 401 tests. 276 to 289 passed.
- [x] `Folder.user_id` column + `_migrate()` extension (mirror `conversations.user_id`).
      Verified for real against SQLite (not mocked): adds, idempotent, indexed, no-op
      on current schema. Postgres branch unchanged query pattern, not live-verified
      (DROP TABLE blocked by the safety hook even for a scratch table).
- [x] Scope folder queries by user; conversation-move verifies folder ownership
      (this was the one real gap: a conversation owner could move it into someone
      else's folder). 7 cross-user isolation tests against a real SQLite database.
      289 to 302 passed.
- [x] `decisions.md` entry 003 added (corrects 001's "any authenticated user" wording
      now that it's actually enforced). 302 passed.
- [x] Startup refusal if `jwt_secret_key` is still the shipped default and debug=false.
      5 new tests, one drives the real lifespan context manager directly. 307 passed.
      Note: the running docker-compose app container will refuse to restart until a
      real JWT_SECRET_KEY is set in .env, or DEBUG=true for local dev. Intended.

**Part 2 A (auth gaps) complete.**

### B. Chat streaming and formatting
- [x] `chat.py`: whitespace-preserving split (`_TOKEN_SPLIT_RE`), committed.
- [x] `_sse()` frames multi-line payloads as multiple `data:` lines per SSE spec, committed.
- [x] Backend test (6 new, including a full real-answer round-trip through the endpoint).
      307 to 313 passed.
- [x] `frontend/src/api.ts`'s `readStream()` now accumulates consecutive `data:` lines
      per event and joins with `\n` on the blank-line terminator.
- [x] Deleted `normalizeMessageText` in `ChatPanel.tsx` and its one call site.
- [x] 2 new frontend tests. `npm test`: 3 files, 6 passed.
- [x] `npm run build` into `app/static`, confirmed via `git status` (old bundle
      removed, new one added).

**Part 2 B complete.**

### C. Retrieval correctness
- [x] Wired `retrieval_min_score` into `retriever.py` (filters before rerank, logs
      drops). Synthesizer short-circuits to a fixed answer on empty retrieved_chunks,
      skipping the LLM call (grounding already handled this case). 4 new tests, 317
      passed.
- [x] `context_max_chars` drops now log a warning (synthesizer + grounding), with the
      drop count correctly excluding a partially-included chunk. 6 new tests, 322
      passed. Found a real pre-existing bug while testing it, not fixed (out of scope
      for this item): the word-boundary `rsplit(" ", 1)` can land inside the label
      prefix instead of the chunk body and erase an entire space-free partial chunk.
      See `tasks/lessons.md` 2026-10-01. **Follow-up DONE:** shared body-only truncation preserves space-free partial
      text and citation labels. Regression tests cover synthesis and grounding.
- [x] `chat_history_limit` actually drives `chat.py`'s history query. Verified by the configured SQL LIMIT test.
- [x] Remove dead `youtube_api_key` setting (config.py + .env.example).
- [x] `context_max_chars`: logs drops from the already rank-ordered tail (see above).
- [x] Lazy Qdrant base URL + reused httpx client per event loop in `retriever.py`.
      API and MCP lifespan cleanup closes the client. Tests cover reuse, current
      settings, loop isolation and shutdown. Retrieval embeddings also run off-loop.

### D. Planner query overwrite
- [x] `original_query` added to `AgentState`, set once at state construction (chat.py,
      mcp_server.py), never touched by the planner.
- [x] Synthesizer answers `original_query`; critic judges against `original_query`.
- [x] Tests: replan loop doesn't lose the original question.
- [x] Approved live benchmark run with OpenAI `gpt-5.5`, reasoning=none,
      temperature=0, 150 output-token cap, fallback disabled. 20/20 cases passed;
      no parse failures/errors. See `reports/critic-benchmark-gpt55.md`.

### E. Ingestion robustness
- [x] web.py/youtube.py: embedding + upsert off the event loop, batched.
- [x] Delete-by-`source_id` before upsert (shared helper with `delete_source`). Test.
- [x] Configurable upload size limit, 413 past it.
- [x] Startup: mark stuck `queued`/`running` ingest jobs as `error`.
- [x] Fix unawaited `create_task` progress-update race in `_run_pdf_ingest_job`.
- [x] Late chunking: rename `embed_late` to something honest (recommended: smaller
      change than implementing it for real), strip false claims from docs.

### F. Smaller hardening
- [x] `/health` checks Postgres + Qdrant, non-200 when either is down.
- [x] Basic rate limiting on `/auth/login`, `/auth/signup`, `/chat`.
- [x] Refresh-token reuse detection revokes the user's whole token family. Test.
- [x] `critic.py` logs a warning on JSON-parse failure.

### G. Retrieval measurement (report only)
- [x] `eval/retrieval_eval.py`: golden set (20-30 Qs) against the real corpus. 24 labeled questions against the
      actual two-source, 17-chunk local corpus; evidence and source/page labels saved.
- [x] Report recall@k/MRR: dense-only, current lexical rerank, cross-encoder rerank.
      Exact cosine over stored vectors and a shared 24-candidate pool, floor 0.3.
      Unit tests on metric logic only; no live calls in the suite. Results in
      `reports/retrieval-evaluation.md`; production ranking unchanged.
- [x] Do not change the production retriever from this without showing numbers first.

### H. Specs complete; production redesigns explicitly deferred
- [x] Grounding redesign spec (verdict + sentences-to-drop instead of full rewrite),
      latency/quality plan via `eval/e2e_pipeline.py`. Spec complete; production redesign deferred.
- [x] Critic-context spec + critic-loop on/off ablation plan. Spec complete; production redesign and ablation deferred.

### I. Documentation reconciliation (last)
- [x] Fix "three collections" claims (CLAUDE.md, agent_memory.md, README,
      `.claude/skills/langgraph/SKILL.md`, `.claude/skills/ingestion/SKILL.md`).
- [x] Fix README's stale default model (`llama-3.3-70b-versatile` -> `openai/gpt-oss-120b`).
- [x] Mark `reports/docchat-audit.md` historical, matching `docs/claude_onboarding.md`.
- [x] Update every quoted test count via grep, not memory.
- [x] Trim HANDOFF.md to current and shorter than its ~660 lines today.


## Deferred follow-ups (outside completed hardening scope)

- GPU Phase 3/4 live sweeps: user chose to defer. Specs and offline tooling are done.
- Grounding-verdict and context-aware critic implementations, plus their paid
  latency/quality and critic-on/off ablations: original plan stops at the specs.
  Review the two dated specs before giving a separate implementation/run go.
- Network volume `owdj19ss50`: retained by explicit user choice; no deletion planned.

Historical checklists and handoff logs live under `tasks/archive/`; their counts and
unchecked items are provenance, not new work.
