# DocChat session handoff

Updated: 2026-10-02. Branch: `master`. Checklist: [tasks/todo.md](tasks/todo.md).

## Phase 3 complete — no active pod

[Report and artifacts](reports/quantization-2026-10-01/README.md),
[benchmark entry](eval/BENCHMARK_RESULTS.md), and
[write-up](docs/inference-writeup.md) are updated. No production code or persistent
provider configuration changed. No commit made in this resume session.

The prior handoff was stale: original pod `ryy03s0132en85` returned 404 and the pod
list was empty. AWQ control/quality/speed artifacts already existed locally despite
being marked pending. Those and the corrected FP16 rows were preserved, including
FP16's c=64 disconnect. The 8192-context attempt remains excluded.

GPTQ ran on replacement `54caxtprn07c1r`, Secure L40S 48GB, EUR-IS-2, $1.09/hr,
created 2026-10-02 00:30:54 UTC and terminated by 00:39:23 UTC. Delete returned 204;
subsequent pod list was empty. GPU, driver, CUDA, PyTorch and exact image digest
matched the original, but host/data-center/network changed. **GPTQ speed differences
are not a controlled same-host quantization effect.** The replacement log and model
revision are saved; original AWQ kernel/memory log and FP16/AWQ revisions are missing.

Original pod's reported charge: $0.5284245586954057. Replacement billing returned no
records at the final check, which does not mean free compute. `billing-readback.json`
and `resume-state.json` retain evidence. Original $5 cap was retained; replacement
ran under nine minutes. Retain network volume `owdj19ss50` (50GB, US-TX-3), confirmed
present and untouched. No cleanup remains except optional later billing reconciliation.

Results:
- FP16: 87/88 speed requests; AWQ: 88/88; GPTQ: 88/88. Every cell measured zero
  prefix-cache hits and zero preemptions. Each serving passed its positive control.
- AWQ aggregate throughput vs FP16: +105.8% / +59.6% / +15.3% at c=1/16/64.
- Critic edge cases correct: FP16 1/5, AWQ 3/5, GPTQ 1/5.
- Corruptions caught/all: FP16 15/15, AWQ 15/15, GPTQ 9/15.
- GPTQ produced Markdown-fenced JSON on 8/20 cases (2 edge + 6 corruption), rejected
  by the current strict parser. Its error-excluding recall 1.00 is not 100% overall
  reliability. Raw responses are retained. No end-to-end quality claim is justified.

13 comparison tests passed this resume session. Comparison reports were generated
with explicit UTC windows and checked against all nine raw cells. Broader historical
checks below were not rerun because no production code changed. Unrelated
`Claude outputs/` remains untouched.

Phase 4 and the grounding/critic redesigns remain deferred. Do not launch more paid
experiments or change production critic behavior just to improve these scores.
Previous checkpoint: [archive](tasks/archive/handoff-before-quantization-resume-2026-10-02.md).

## Status

The codebase hardening and Phase 3 measurements are complete. Auth gaps,
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

Phase 3 measurements are complete with documented limitations. Phase 4 batching
remains deferred. No pods remain; this was confirmed on 2026-10-02.
The retained network volume owdj19ss50 (50GB, US-TX-3) has cached Qwen weights and its
own storage charge; user chose to keep it. Do not delete it without a specific go.

Grounding verdict/removal and context-aware critic redesigns stop at these specs:
- [Grounding](docs/superpowers/specs/2026-10-01-grounding-verdict-design.md)
- [Critic context/ablation](docs/superpowers/specs/2026-10-01-critic-context-ablation-design.md)

They contain concrete paired quality/latency experiments. No production redesign or
critic-on/off quality-lift claim has been made. A 20/20 classification diagnostic is
not evidence that the retry loop improves end-to-end answers.

## History and next action

The hardening checklist and authorized Phase 3 live measurements are complete.
The hardening branch was pushed
and merged into the repository's default `master` branch without conflicts. Merge
commit `77a2abb` is published on `origin/master`. Checks on the integrated branch:
368 Python tests passed, 6 frontend tests passed, and Ruff clean.
Unrelated `Claude outputs/` is untouched.
Older handoff: [archive](tasks/archive/handoff-before-hardening-completion-2026-10-01.md).
Older inference checklist: [archive](tasks/archive/inference-todo-prior-sessions.md).
Historical counts and obsolete pending entries there are not current instructions.
