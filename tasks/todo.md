## Active: AWS platform follow-up fixes (2026-10-22, second pass) - DONE (offline); see HANDOFF.md

Rules: no terraform plan/apply, no AWS, no AWS-dependent tests. No commit, never `git add -A`. Do not touch
app/services/llm.py, tests/test_llm_provider_seam.py, reports/, "Claude outputs/", docs/project-walkthrough.md.
Local backends stay the default. Plain English, no em-dashes. A test for every behaviour change.
Baseline now: ruff clean, 778 passed (634 at the start of the first pass = 629 at HEAD + 5 uncommitted llm-seam tests).

### 1 Scale-in kills running jobs (required)
- [x] ecs.tf: scale-in alarm uses metric math: visible + not-visible (`ApproximateNumberOfMessagesNotVisible`), per minute, 15 periods.
- [x] New `app/worker/protection.py`: ECS scale-in protection via the agent endpoint (`ECS_AGENT_URI/task-protection/v1/state`, PUT
      `ProtectionEnabled` with expiry). Injected client so tests use a fake. Fail safe: endpoint missing or error means
      no protection and a content-free warning, never a crash. Enabled while jobs are in flight, released when idle, renewed
      during long jobs, released on shutdown.
- [x] Wire into Worker (`_run_one` counter). Tests: on at first job, off at last, renewed, fake down, no env var (local).
- [x] IAM: task-protection calls use the task role (agent endpoint), check which permission applies (`ecs:UpdateTaskProtection`)
      and add it to the worker task role only, scoped to this cluster's tasks.
- [x] Defaults: ingest_job_timeout_s vs visibility vs max attempts. Document that an interrupted job still uses a receive
      count, and the rule: max attempts >= 3 and timeout well under visibility x attempts. Add a config check where cheap.
- [x] docs/aws/operations.md section.

### 2 RDS rotated password (required)
- [x] Read the AWS docs on managed master secret rotation (7-day schedule, password changed in place?) and record findings
      in docs/aws/security.md. The design below is only kept if the docs show new connections break.
- [x] If so: `app/core/db_secret.py` secrets reader (boto3, injected client, short TTL cache, retry once on auth failure);
      database.py passes it to asyncpg via `connect_args={"password": callable}`; setting `DATABASE_PASSWORD_SECRET_ARN`
      (env `DATABASE_PASSWORD` stays for local). ecs.tf passes the ARN instead of injecting the password; task roles get
      `secretsmanager:GetSecretValue` on the DB secret only (worker keeps DB secret only). Tests with a fake client that rotates.
- [x] Open point: SQLAlchemy pool_pre_ping plus asyncpg password callable support; check the installed versions first.

### 3 Dual-write gap, stuck queued jobs (required)
- [x] Setting `INGEST_QUEUED_STALE_S` (default 600).
- [x] enqueue.py: dedupe ignores `queued` jobs older than the threshold (running jobs keep the lease rule).
- [x] Worker sweeper: every N seconds, find jobs `queued` and stale, re-send their message (needs the message fields:
      PDF storage key is derivable from job id; URL jobs need the URL, which is not stored. Decision needed, see questions).
- [x] Tests: crash between commit and send, sweeper re-sends once per interval, dedupe skips a stale job, duplicate send is harmless.

### 4 Concurrency tests on real Postgres (required)
- [x] `pg` marker in pytest.ini; fixture reads `TEST_DATABASE_URL`, skips cleanly if unset or unreachable.
- [x] Tests: two workers claim one job (exactly one wins), source_lock serialises two writers of one source, lease expiry vs redelivery.
- [x] ci.yml: `postgres` job with a postgres:16 service container and `TEST_DATABASE_URL`. Run locally against a throwaway
      Docker Postgres (docker run only; stop/rm may be denied).

### 5 Build once, scan, deploy the same image
- [x] ci.yml builds and scans, uploads the image tar as an artifact (or deploy builds once, scans, then pushes the same image).
- [x] deploy.yml: reuse CI result, load that image, push, record digest, register task definition with `repo@sha256:...`.
      Keep the checks gate, OIDC, SHA pins. actionlint.

### 6 Qdrant hardening
- [x] App: `QDRANT_API_KEY` setting, passed to QdrantClient and the health probe header. Tests.
- [x] secrets.tf container, ecs.tf secret on API and worker, instance gets the key at boot from Secrets Manager (instance role read on that one secret).
- [x] ECR repo for the Qdrant mirror, instance pulls from ECR by digest (instance role: auth token + pull on that repo only).
- [x] deployment.md: mirroring steps (pull, verify digest, push). Hygiene tests updated.

### 7 URL fetcher limits
- [x] `WEB_MAX_BYTES` (default 5 MiB) and total deadline across redirects; stream with a cap. Tests: oversize, slow body, redirect chain.
- [x] DNS rebinding: connect to the validated IP with Host header and `sni_hostname` extension in httpx. Expected to be feasible; if tests show it is not, keep the guard and document why.

### 8 Cost-lean demo profile
- [x] `demo` variable (default false): worker Fargate Spot, worker min 0 with scale-out alarm at 1 visible, db.t4g.micro single AZ, 7-day logs.
- [x] AWS Budget with email (limit and email variables).
- [x] NAT-less demo: decided NOT to build (docs/aws/cost.md explains why).
- [x] docs/aws/teardown.md, cost.md (estimates only), dev.tfvars.example.

### 9 Smaller items
- [x] security.md: lock pins pillow 13 / old pyasn1 against declared caps, resolver fails on the lock, how it is verified (pip check allowlist, tests on the lock). PyJWT move planned as a separate step, not now.
- [x] Logging: the `request` telemetry event already carries method, route template, status, duration and request id, so the disabled uvicorn access log is covered. Add a test that proves it, and a small line only if the proof fails.
- [x] cloudwatch.tf: alarm on the `IngestDeadLettered` metric.
- [x] limitations.md: explain 629 at HEAD / 634 with uncommitted llm tests / current count.

### Closing
- [x] ruff, pytest -m "not eval", pg tests, terraform fmt/init/validate, Trivy config, both Docker builds, actionlint. Say what could not run.
- [x] HANDOFF.md, tasks/lessons.md, CLAUDE.md baseline.

### Answered (2026-10-22): 1) no URL storage, send-then-insert + stale dedupe, no sweeper; 2) yes, read secret at connect time; 3) skip NAT-less; 4) API key, no TLS, keep ECR mirror
### Original questions
1. Item 3: URL jobs do not store the URL (kept out of the DB on purpose). For the sweeper to re-send, either store the URL in the job row (encrypted-at-rest DB, never logged) or mark stale URL jobs as failed and let the user resubmit. I prefer storing it. OK?
2. Item 2: if the AWS docs show rotation breaks new connections, the app reads the password from Secrets Manager at connect time. This adds boto3 to the DB path in AWS mode only. OK?
3. Item 8, NAT-less demo: tasks in public subnets with public IPs is workable (no inbound, egress-only security groups), but Qdrant and RDS stay private and Qdrant then needs ECR/SSM reachability, which means VPC endpoints that cost about as much as a NAT. My lean is not to implement the NAT-less part and say why. Agree?
4. Item 6: Qdrant API key over plain HTTP is sent unencrypted inside the VPC. Accept that and document it, or add TLS (more work)?

## Previous pass: AWS platform (2026-10-22)

Plan: docs/superpowers/plans/2026-10-22-aws-platform.md. No `terraform apply`, no live AWS, no secrets, no AWS-dependent tests.
Baseline before work: ruff clean, 634 passed (uncommitted llm.py work already in tree; not mine, do not stage).

- [x] 1 config: backends, DB parts, prod validation
- [x] 2 blob stores (local, s3) + tests
- [x] 3 queue (message, sqs) + tests
- [x] 4 ingest_jobs columns, runner, claim/idempotency, retries + tests
- [x] 5 ingest API wired to queue backend; gate startup recovery/migrations
- [x] 6 worker loop, graceful shutdown, health/metrics server + tests
- [x] 7 JSON logging + redaction, /health/live, worker metrics + tests
- [x] 8 Dockerfile (api, worker), build + run read-only check
- [x] 9 Terraform + fmt/validate
- [x] 10 GitHub Actions
- [x] 11 docs/aws/*, HANDOFF, lessons
- [ ] 12 full gates, diff security review  (gates green: ruff clean, 778 passed; diff review in progress)

## Active: close the remaining inference-serving gaps (2026-10-06, third session)

Goal: honestly measured evidence for (A) GPU utilization, (B) a failure test, (C) a stronger benchmark harness.
No spend, pod or paid API without explicit approval. No commit. Do not stage raw logs or `Claude outputs/`.

Phase 0: offline readiness (no spend)
- [x] Baseline ruff + pytest (re-run: ruff clean, 547 passed)
- [x] Review gpu_sampler / gpu_utilization / serving_load; offline dress rehearsal against a fake server (done)
- [x] Fix only real bugs, with tests (1 found: sampler period drift; fixed + 2 tests)
- [x] Live-session run plan: docs/superpowers/plans/2026-10-06-live-gpu-session.md  -> STOPPED, awaiting approval

Phase 1: harness improvements (offline, TDD)  [approved 2026-10-06; spec + plan written]
Spec: docs/superpowers/specs/2026-10-06-harness-improvements-design.md  Plan: docs/superpowers/plans/2026-10-06-harness-improvements.md
- [x] 1 p99 latency/TTFT in cell summaries and capacity_plan
- [x] 2 cost per request and per 1K output tokens in capacity_plan (skip when cost null)
- [x] 3 engine prefixes (vllm verified on v0.30.0 / sglang UNVERIFIED) + prefix_cache_summary + --engine
- [x] 4 per-cell prefix_cache event field + compare_prefix_caching (on vs off)
- [x] 5 compare_batching: fixed-batch serial vs concurrent (legacy rows)
- [x] 6 failure-behaviour test mode (no hosted fallback added; named failure-behaviour, per the owner)
- [x] 7 docs/benchmarking.md updated per addition
- [x] 8 HANDOFF, lessons, gates, diff summary -> STOPPED; awaiting approval before Phase 2

Phase 2: live GPU session  [DONE 2026-10-06, pod terminated, report at reports/gpu-live-2026-10-06.md; was: Phase 1 committed locally as f6efb01; plan revised + live quote given 2026-10-06; AWAITING EXPLICIT GO. cap $4.00 hard, stop-and-ask $2.50]   Phase 3: report  [after Phase 2]

## Active: GPU utilization review pass (2026-10-06, second session)

Review and tighten before any real GPU. Small fixes only; offline; no commit; do not touch capacity_plan.py or
comparability logic. Fake numbers are labelled as illustrations.

- [x] Check 1 findings gathered (git add list + message given in the final report)
- [x] Check 2: offset sign documented once + sign-flip test; runbook step to measure offset (labelled example);
      short-window warning when offset is assumed zero
- [x] Check 3: scan docs/attach output for overclaiming words; add the "share of sample period" sentence; add the
      "how to read it" table (uses "may")
- [x] Check 4 (--dry-check built, about 23 lines): first-live-run section (statuses, healthy result, three likely failures + fixes); --dry-check only if
      under about 30 lines
- [x] HANDOFF: "built, reviewed, offline-tested, live run pending"; lessons added
- [x] ruff, pytest (547 passed vs 534: +13), git diff --stat + git add list

## Active: GPU utilization in the serving benchmark (2026-10-06)

Closes one named gap: the sustained benchmark records TTFT, p95, tokens/sec, queue wait and KV-cache
pressure but not GPU utilization. Optional field; offline-tested only; no GPU launched. No commit.
Spec: docs/superpowers/specs/2026-10-06-gpu-utilization-design.md

- [x] Spec in docs/superpowers/specs/2026-10-06-gpu-utilization-design.md
- [x] Record wall-clock window in cell_summary (additive) + test
- [x] eval/gpu_sampler.py (pynvml, nvidia-smi, unavailable fallback) + tests
- [x] eval/gpu_utilization.py attach + load helper + tests (normal, warmup, missing, too few, offset, multi-GPU)
- [x] Optional comparison column; absent-field and comparability tests; capacity unchanged
- [x] Docs: benchmarking.md section + runbook; serving-observability.md meaning/limits
- [x] HANDOFF.md refresh (fix stale header; GPU utilization "built, offline-tested, live run pending"); lessons if any
- [x] ruff, pytest (534 passed vs 493 baseline: +41), git diff --stat; no commit

## Active: LLM-assisted answer-quality review (2026-10-05)

Labels are LLM-assisted, not human-verified. Judge never sees model/split/case id/file names.

- [x] eval/judge_prompt.py: versioned prompt, evidence-only message builder, strict validator
- [x] eval/judge_answer_review_pack.py: resumable blinded judge runner (--dry-run, --limit, --judge-model)
- [x] eval/aggregate_judge_labels.py: unblind only at aggregation (key: /private/tmp/docchat-quality-review-key.json)
- [x] Tests for prompt leakage, validator, runner resume/retry/overwrite, aggregation, 120 unique ids
- [x] Dry-run --limit 3 + real --limit 5 done (5/120 judged, reports/quality-judge-labels.jsonl). STOP: awaiting user review before the other 115.
- [ ] Report/HANDOFF wording (LLM-assisted; no "human evaluation"/"validated"/"significant")

## Active: Phase 2 benchmarks and metrics (2026-10-04)

- [x] Review Phase 1 interfaces and establish baseline.
- [x] Expose bounded Prometheus metrics from request and model telemetry.
- [x] Add versioned sustained replay/API workloads and incremental run artifacts.
- [x] Verify scheduling, errors, SSE parsing, usage and metrics offline: 428 passed, 8 deselected.
- [x] Document monitoring/benchmarks and update handoff; Ruff clean, CLI validation offline.
- [ ] Live acceptance remains pending; no paid run authorized by this implementation task.

## Phase 1 checkpoint (2026-10-04)

- [x] Review architecture and establish baseline: 368 passed, 8 deselected.
- [x] Formalize local adapter and configuration-aware client lifecycle.
- [x] Trace request lifecycle, graph stages and model attempts.
- [x] Add serving readiness and deployment documentation.
- [x] Verify offline tests/lint and update handoff: 398 passed, 8 deselected; Ruff clean.
- [ ] Live GPU acceptance (pending approved endpoint; no GPU launched).
- [x] Phase 2 implementation: sustained workload benchmarks and Prometheus metrics (live acceptance pending).

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
      276 passed. **Phase 3 subsequently authorized; Phase 4 remains deferred.**
- [x] 5. `docs/inference-writeup.md` written from `eval/BENCHMARK_RESULTS.md` numbers
      only. README's Inference benchmarking section updated to match (dropped the "no
      such ceiling" overclaim, linked the write-up). 276 passed, no code changed.
- [x] 6. Asked about network volume `owdj19ss50`. User chose to keep it (Phase 3/4
      would reuse its cached weights). Not deleted.

**Part 1 status: items 1, 2, 3, 5, 6 done. Item 4 tooling/specs complete.
Phase 3 live measurements are complete; Phase 4 remains deferred.**

**Phase 3 live measurements COMPLETE (2026-10-02), with documented limitations.**
Original pod was absent on resume. FP16/AWQ artifacts were recovered locally; GPTQ
ran on replacement `54caxtprn07c1r` in EUR-IS-2, then it was terminated. Empty pod
list confirmed. Retained network volume is untouched. Original pod charge reported
$0.5284245586954057; replacement billing had no records yet (not zero-cost evidence).

- [x] Replacement GPU/CUDA verified; same original image/driver/versions.
- [x] FP16 positive control + critic diagnostic + corrected sweep retained (87/88; c=64 disconnect).
- [x] AWQ positive control + critic diagnostic + sweep retained (88/88).
- [x] GPTQ positive control + critic diagnostic + sweep completed (88/88 speed; 8/20 critic parse failures).
- [x] Comparison report using explicit windows, benchmark entry and write-up completed.
- [x] Available logs/revision saved; original AWQ log and FP16/AWQ revisions missing and disclosed.
- [x] Replacement terminated, empty pod list confirmed, billing readback saved. Network volume retained.

Artifacts: `reports/quantization-2026-10-01/`. Initial 8192-context attempt excluded.
GPTQ's replacement host prevents a controlled same-host speed comparison. The critic
diagnostic is not end-to-end answer quality. 13 comparison tests passed; no production
code changed. Phase 4 remains deferred.

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

- Phase 3 evidence gaps: original AWQ backend/memory log and FP16/AWQ revisions unavailable;
  GPTQ ran on another host. Reported transparently; no additional paid run planned.
- GPU Phase 4 live sweep: deferred. Specs and offline tooling are done.
- Grounding-verdict and context-aware critic implementations, plus their paid
  latency/quality and critic-on/off ablations: original plan stops at the specs.
  Review the two dated specs before giving a separate implementation/run go.
- Network volume `owdj19ss50`: retained then; deleted 2026-10-06 on the owner's explicit request (204; lists empty).

Historical checklists and handoff logs live under `tasks/archive/`; their counts and
unchecked items are provenance, not new work.

- [x] Phase 3 report written (reports/gpu-live-2026-10-06.md); README, inference-writeup, HANDOFF updated
- [x] Owner decisions made: volume owdj19ss50 deleted; session artifacts committed (small files only, events.jsonl local)
- [ ] Phase 3 follow-up note (not built): local-to-hosted fallback is a production decision
