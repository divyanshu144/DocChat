# DocChat session handoff

## Latest: LLM-assisted answer-quality review (2026-10-05, uncommitted)

STOPPED by user 2026-10-06. Final report (v1 complete + v2 partial): `reports/answer-quality-final-report-v1-v2-2026-10-06.md`.
v2 partial: Opus 22, astra 66, Groq 53 of 120 (credits/daily cap); no GPTQ coverage; no v2 format conclusions.
To finish: resume Groq (same command, see report section 9) once its cap/tier allows. Nothing committed.

Blinded `gpt-5.6-luna` judge ran over all 120 rows of `reports/quality-review-pack.jsonl`
(119 ok, 1 schema_error: `review-ec6f5335912c`). The judge rejected `temperature=0`; labels
use provider-default sampling and are NOT manually spot-checked yet. Full write-up:
`reports/answer-quality-llm-judge-2026-10-05.md`. Next: spot-check ~10 rows, decide on the
failed row, optional re-judge for agreement. Do not claim temperature 0 or human evaluation.
v2 rerun (2026-10-06): Opus v2 halted at 22/120 (credits); gpt-6-astra v2 halted at 66/120 (OpenAI credits exhausted) -> `reports/quality-judge-labels-v2-gpt-6-astra.jsonl`.
Draft: `reports/answer-quality-v2-report-2026-10-06-DRAFT.md` (Groq gpt-oss-120b v2 temp=0 run halted at 53/120: daily token cap; resume later with same command, output reports/quality-judge-labels-v2-groq-gpt-oss-120b.jsonl; section 7 PENDING; astra aggregate files cover only 66 rows, do not quote). New tools: paired_format_comparison,
build_disagreement_sheet, refresh_pack_citations (fixed pack copy), compare_judge_labels pairwise mode.
Final report: `reports/answer-quality-final-report-2026-10-06.md` (corrected answer/abstention/citation labels;
unsupported-claim counts exploratory; v2 rerun deliberately deferred).
Audit pass (2026-10-06): `reports/quality-judge-label-audit.{jsonl,md}` hold suggested corrections (LLM-audited, not human-verified;
original labels untouched). `eval/audit_judge_labels.py` applies per-claim decisions; see the md for the strict/full bounds.

## Current: Phase 2 benchmarks and metrics (completed locally 2026-10-05)

User authorized Phase 2 after Phase 1. Both phases are implemented but uncommitted;
last commit is still `04179e4` (benchmark evidence). No push/deployment or paid model
workload ran. Unrelated `Claude outputs/` is untouched. Prometheus client 0.26.0 was
installed in the existing venv; requirements declare `prometheus-client>=0.21,<1`.

Phase 2 additions:
- `/api/v1/metrics`, optionally protected by METRICS_BEARER_TOKEN. Single-process
  registry observes complete HTTP requests/in-flight, first answer, graph/retrieval
  stages, LLM duration/TTFT/tokens, missing usage, retries and critic parser failures.
  Labels exclude identity/content; metrics scrapes do not instrument themselves.
- Existing `eval.inference_benchmark` now accepts a `sustained` subcommand. Historical
  burst commands/data are unchanged. New schema-v2 runs support captured prompt replay
  or authenticated chat SSE, closed-loop concurrency or bounded fixed-rate arrivals,
  repeats/warmup/deadlines, generator rejections and incremental JSONL artifacts.
- Per-case workload schema and capture integration, source/workload/corpus fingerprints,
  allowlisted deployment metadata, per-category summaries and repeated-run variation.
  Missing usage remains unknown, and success percentiles are reported with failure
  counts. Default p95 sample minimum is 100. API SSE has no token counts/model TTFT.
- Label-preserving vLLM metrics snapshots and reset-aware counter deltas; explicit
  schema-v2 comparison mode refuses mismatched/incomplete runs. Server physical-host
  control and live-index/corpus consistency still require operator verification.
- Workload authoring template, optional Prometheus scrape config and Grafana panel
  queries. No actual monitoring stack provisioned.

Verification:
- `venv/bin/ruff check .`: All checks passed!
- `venv/bin/python -m pytest -m "not eval" -q`: 428 passed, 8 deselected;
  13 pre-existing python-jose UTC deprecation warnings.
- Offline CLI `sustained --target api --workloads data/workloads.example.json
  --out-dir /tmp/docchat-validation-no-write --validate-only`: four categories valid,
  no run directory created. Template is not a measured or labeled real workload.
- Benchmark API consumer tested against the actual FastAPI SSE route with a mocked
  graph. Transport/scheduling/cancellation/capture/metrics/comparison tests remain offline.
- Frontend unchanged; no frontend checks rerun. No persistent `.env` modifications.

Entry docs: `docs/benchmarking.md`, `docs/grafana-plan.md`,
`docs/serving-observability.md`. Phase 2 spec/plan are dated 2026-10-04 (started before
midnight; completed 2026-10-05).

Next: review/commit the accumulated Phase 1+2 work, then Phase 3 held-out retrieval
and answer-quality evaluation. Live Phase 1+2 acceptance remains pending an available
approved GPU endpoint and real authored/captured corpus workloads. Do not claim new
throughput, quality improvements or sustainable capacity from these offline tests.

---

## Phase 1 checkpoint (2026-10-04)

Previous benchmark evidence committed as `04179e4` (local; not pushed this session).
User authorized continuing the agreed staged platform work. Phase 1 implementation
and offline verification are complete; live GPU acceptance is still pending.
Current changes are uncommitted. `Claude outputs/` remains unrelated and untouched.

Implemented:
- Local inference request/result protocol and vLLM-first HTTP adapter under
  `app/services/inference/`; public chat_complete/chat_stream return types preserved.
- Event-loop/configuration-owned clients, explicit API/MCP/benchmark cleanup,
  configurable HTTPX timeouts/connection limits and local endpoint/model validation.
- Content-free JSON telemetry in `app/core/telemetry.py`: request lifecycle through
  SSE delivery, first answer latency, graph iterations, retrieval subspans, model
  attempts/usage, fallback attribution, streamed TTFT and estimated decode rate.
- Optional `LOCAL_STREAM_COMPLETIONS=true` buffers local model streams internally;
  default false. Grounding/critic and UI answer-release ordering unchanged.
- Separate `/api/v1/health/serving` model-list probe; ordinary health remains DB/Qdrant.
- Serving runbook additions, observability definitions and a deployment manifest
  template requiring actual digest/revisions/hardware before any measurement.
- Formatting-only correction to the historical run-serving.py runner so Ruff covers
  the newly committed artifact. Raw results/logs remain unchanged.

Verification this session:
- `venv/bin/ruff check .`: All checks passed!
- `venv/bin/python -m pytest -m "not eval" -q`: 398 passed, 8 deselected;
  13 existing python-jose UTC deprecation warnings.
- `git diff --check`: clean. Frontend unchanged; no frontend checks rerun.
- No live model calls, GPU creation, new experiments, persistent `.env` changes,
  application deployment, commit or push of this implementation.

Next: review this Phase 1 diff, then Phase 2 sustained prompt-replay/end-to-end
benchmarks and Prometheus metrics. Keep the existing burst benchmark results and
statistics historically labeled until its planned schema migration. Live acceptance
needs an available approved vLLM endpoint: real document QA, trace inspection,
internal streaming on/off comparison and remote cancellation behavior.

Plan: `docs/superpowers/plans/2026-10-04-serving-foundation.md`.
Contract/timing limits: `docs/serving-observability.md`.
Nonstream model TTFT and per-request engine queue wait remain unknown; the client
stream decode rate is explicitly an estimate. SDK-internal retries are not separately
instrumented. No Prometheus endpoint or production ranker/critic redesign yet.

---

## Historical quantization checkpoint (2026-10-02)

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

## Phase 3 evaluation tooling

Added an evaluation-only full-corpus BM25 baseline to `eval/retrieval_eval.py`;
the overlap and cross-encoder rankers remain labeled as rerankers over the shared
dense candidate pool. Added `eval/answer_quality.py` to aggregate human-labeled
claim support, expected fact coverage, citation coverage/validity and abstention
quality. Usage, annotation schema, limitations and the future comparison protocol
are in [retrieval-quality-evaluation.md](docs/retrieval-quality-evaluation.md).
The existing retrieval report is explicitly marked historical; its lexical row
is not a BM25 result. No new labels or evaluation results were fabricated, no
production ranking behavior changed, and this tooling pass did not run tests,
connect to Qdrant, call a model, or use a GPU. Meaningful quality comparisons
still require a larger held-out workload with reviewed answer annotations.

## Phase 3 evaluation run (2026-10-05)

Ran `eval.retrieval_eval` read-only against the healthy local `source_chunks`
collection and saved the full-corpus BM25 comparison to
[`phase3-evaluation-2026-10-05.md`](reports/phase3-evaluation-2026-10-05.md)
and [`retrieval-eval-phase3.json`](reports/retrieval-eval-phase3.json). Corpus:
17 chunks, two sources; golden set: 24 single-annotator questions. Recall@3:
dense .875, BM25 .917, dense + overlap .979, dense + cross-encoder 1.000. Mean
CPU ranking time: .143ms, .919ms, .132ms reranking-only, and 1170ms
reranking-only respectively. This small development set does not justify a
production ranker change.

This retrieval-only status was superseded by the same-day serving follow-up.
The follow-up ran FP16, AWQ and GPTQ on one temporary L40S host at concurrency
1/4/16/32/64 and saved 24 generated answer/context pairs. All 372 load-test
requests succeeded. Full measurements, limitations, and raw artifact links are
in [the serving and answer-quality report](reports/phase3-serving-quality-2026-10-05.md).
The pod is terminated and no active pods remain. The answer audit found no valid
source-marker citations, but claim-level groundedness still needs human review;
the critic diagnostic is not a substitute.

### Expanded held-out evaluation follow-up (2026-10-05)

Expanded the workload to 40 captured DocChat QA, summary, long-context,
multi-document and negative-control cases. Repeated FP16, AWQ and GPTQ serving
at concurrency 1/4/16/32/64, 64 requests per cell and two repeats: all 1,920
measured requests succeeded. Added raw run artifacts under
`reports/heldout-serving-{fp16,awq,gptq}/`, 40 answers per format,
`reports/heldout-citation-audit.json`, a blinded 120-answer review pack, and
`reports/capacity-plan.json`. Results and caveats are in
[`heldout-serving-evaluation-2026-10-05.md`](reports/heldout-serving-evaluation-2026-10-05.md).

At a 20s p95 SLO and 30% throughput headroom, the capacity script estimates
4 FP16 GPUs or 3 AWQ/GPTQ GPUs for 5 RPS, using linear extrapolation. This is
provisional for a 17-chunk/two-document corpus. Human claim support,
unsupported-claim and abstention labels are still pending; the blind pack is
`reports/quality-review-pack.jsonl` and the unblinding key is kept outside the
repository at `/private/tmp/docchat-quality-review-key.json`. The source-marker
audit checks marker membership only, not grounding. Queue wait is not yet
isolated per request; AWQ/GPTQ have vLLM waiting-gauge snapshots, while FP16
does not.

The newly added tooling and existing suite pass: `ruff check .` clean;
`venv/bin/python -m pytest -m "not eval" -q` reports 435 passed, 8 deselected.
The temporary pod `xurcmwnkzwdkat` was terminated; a subsequent pod lookup
returned 404. RunPod's pod-billing endpoint reported $0.638 in posted charges
through the bucket ending 11:00 UTC, which may lag and is not a final invoice.
