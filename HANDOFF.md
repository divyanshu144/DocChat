# DocChat session handoff

Updated: 2026-10-01. Branch: `master` (merged from `chore/inference-complete-and-hardening`).
Current checklist: [tasks/todo.md](tasks/todo.md).

## PAUSED: Phase 3 quantization comparison, mid-discussion, no pod created

User said "let's do the quantization part now, let's discuss it first," then paused
mid-discussion before answering. **Nothing has been created. No pod exists. Pick this
up by re-asking the three open questions below, don't just proceed on the recommended
defaults without the user actually confirming them.**

Spec: `docs/superpowers/specs/2026-10-01-quantization-comparison-design.md`. Tooling
(`eval/quantization_compare.py`) and its dry-run tests already exist and pass (see
Part 1 item 4a in `tasks/todo.md`) — only the live pod run is outstanding.

**Facts confirmed this session (read-only, no pod), reusable without re-checking:**
- Both quantized repos the spec names are real on Hugging Face, not assumed:
  `Qwen/Qwen2.5-7B-Instruct-AWQ` (AWQ 4-bit) and `Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4`
  (GPTQ 4-bit), both official Qwen releases. So the plan can run all three servings
  (FP16, AWQ, GPTQ-Int4), not just FP16+AWQ with GPTQ skipped.
- L40S 48GB stock as of this check: Secure $1.09/hr, Community $0.79/hr, LOW stock,
  currently only in `US-MO-1` (checked via `get-capacity`/`list-gpu-types` — re-check
  before creating anything, stock shifts).
- The cached network volume (`owdj19ss50`, `US-TX-3`, holds FP16 weights from the
  Fourth sweep) probably will NOT help this run: L40S Secure stock isn't in `US-TX-3`
  right now, and the volume has no cache for the two new quantized repos anyway, so the
  time saved would be small even if it did line up. Recommendation worked out so far:
  don't pin a data center, let it land wherever L40S has stock, skip the volume.

**Three open questions asked, not yet answered — ask again before proceeding:**
1. Concurrency levels per serving: spec default is `1,16,64` (9 cells total across 3
   servings) vs. the Fourth sweep's full `1,4,16,64,128` (15 cells, slower/costlier,
   but directly comparable cell-by-cell to existing data).
2. GPU: same L40S 48GB as the Fourth sweep (Secure first, Community fallback) vs. a
   different GPU.
3. Cost cap to state before creating anything: proposed $5 as a reasonable ceiling
   (rough estimate: 3 servings x [download + positive control + harness sweep +
   `eval/benchmark.py` quality run], mostly idle/setup time, ~3-4 hours of pod time at
   $1.09/hr worst case). Not yet confirmed.

**Next action if resuming:** re-ask these three questions (don't assume the
recommended options were silently accepted), then write the exact `create-pod` request
and state GPU/rate/duration/cost cap for explicit go, per the money-safety rules in the
original task (Terminate not Stop, confirm `list-pods` empty at the end).

## Status

The authorized codebase hardening and measurement work is complete. Auth gaps,
folder ownership and default-secret startup refusal were already committed before
this session. SSE whitespace preservation and frontend decoder/build were also done.
This completion pass covers:

- Configured chat history limit, removed dead YouTube API key setting.
- Lazy Qdrant URL, reused HTTP client per event loop, API/MCP shutdown cleanup;
  retrieval query embedding runs in a worker thread.
- Original user question survives all planner rewrites; synthesis and critique use it.
- Partial context truncation searches within the body and preserves citation labels.
- Independent CPU embedding batches, off-loop ingestion indexing, shared source
  deletion/replacement; successful shorter re-ingests leave no orphan chunks.
- Bounded uploads (50 MiB by default), ordered awaited PDF progress, startup recovery
  of queued/running jobs left by restart; temp files cleaned on failure.
- Dependency-aware health (503 if DB or Qdrant fails), bounded per-IP auth/chat limits,
  atomic refresh rotation and user-wide refresh-session revocation on replay.
- Critic JSON failure warnings; benchmark no longer scores parse fallback as good.
- Real-corpus retrieval comparison and both requested redesign specs.
- Current docs/skills reconciled with one source_chunks collection and independent
  embeddings; historical audit/design claims clearly marked as provenance.

## Verification

- `venv/bin/ruff check .`: All checks passed!
- `venv/bin/python -m pytest -m "not eval" -q`: 368 passed, 8 deselected.
  13 warnings from python-jose's deprecated UTC timestamp helper.
- `cd frontend && npm test -- --run`: 3 test files, 6 tests passed.
- No frontend code changed in this completion pass; existing SSE build is retained.
- Approved live critic diagnostic using OpenAI `gpt-5.5`, reasoning=none,
  temperature=0, max_completion_tokens=150, fallback disabled: 5/5 edge cases,
  15/15 corruptions, 20 requests, no errors/parse failures, every finish_reason=stop.
  Report: [critic benchmark](reports/critic-benchmark-gpt55.md), raw JSON alongside.
  This was a per-run override; persistent provider/model config was not changed.
- Retrieval eval: 24 real-corpus questions, 17 chunks from the PDF declaration and
  Wikipedia RAG article. Recall@3 dense 0.8750, lexical 0.9792, cross-encoder 1.0000.
  Cross-encoder ranking averaged 1.17 seconds on CPU; production ranker unchanged.
  [Report](reports/retrieval-evaluation.md), golden labels and raw rankings retained.

## Operational limits

One application worker is the current model. Job recovery, in-memory IP limits,
and source-write locks are process-local; use shared ownership/queue/limiter before
scaling to independent workers. Qdrant delete plus batched upsert is not transactional;
retry failed indexing jobs. Replay revokes refresh tokens, not existing access JWTs.

A production restart requires a real JWT_SECRET_KEY (or DEBUG=true for local dev).
The prior running Compose app lacked that setting; do not expose the shipped key.
Host-side scripts must use localhost:6333 and Postgres port 5433, rather than Docker's
qdrant/postgres DNS names. Do not read/print .env secrets in session output.

## Explicitly deferred

No GPU pod was created in this session. Phase 3 quantization and Phase 4 batching
live sweeps remain deferred by the user's choice; specs and dry-run tooling are done.
Last recorded GPU pod was terminated and an empty pod list confirmed in that session.
The retained network volume owdj19ss50 (50GB, US-TX-3) has cached Qwen weights and its
own storage charge; user chose to keep it. Do not delete it without a specific go.

Grounding verdict/removal and context-aware critic redesigns stop at these specs:
- [Grounding](docs/superpowers/specs/2026-10-01-grounding-verdict-design.md)
- [Critic context/ablation](docs/superpowers/specs/2026-10-01-critic-context-ablation-design.md)

They contain concrete paired quality/latency experiments. No production redesign or
critic-on/off quality-lift claim has been made. A 20/20 classification diagnostic is
not evidence that the retry loop improves end-to-end answers.

## History and next action

All current authorized checklist items are complete. The hardening branch was pushed
and merged into the repository's default `master` branch without conflicts. Merge
commit `77a2abb` is published on `origin/master`. Checks on the integrated branch:
368 Python tests passed, 6 frontend tests passed, and Ruff clean.
Unrelated `Claude outputs/` is untouched.
Older handoff: [archive](tasks/archive/handoff-before-hardening-completion-2026-10-01.md).
Older inference checklist: [archive](tasks/archive/inference-todo-prior-sessions.md).
Historical counts and obsolete pending entries there are not current instructions.
