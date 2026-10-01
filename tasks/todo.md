# Task: inference completion + codebase hardening (chore/inference-complete-and-hardening)

Plan file: `/Users/divyanshu/.claude/plans/silly-forging-deer.md` (full context and
rationale). This is the checklist version. Branch: `chore/inference-complete-and-hardening`,
off `feat/openai-sse-chat-quality`. One commit per item. Nothing pushed, nothing merged.

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

## Part 2 - codebase review fixes, in order

### A. Auth gaps
- [ ] `Depends(get_current_user)` on all `app/api/ingest.py` + `app/api/folders.py` routes.
- [ ] `decisions.md` entry 003 (corrects 001's "any authenticated user" wording).
- [ ] `Folder.user_id` column + `_migrate()` extension (mirror `conversations.user_id`).
- [ ] Scope folder queries by user; conversation-move verifies folder ownership.
- [ ] Startup refusal if `jwt_secret_key` is still the shipped default and debug=false.
- [ ] Tests: 401 on every newly-guarded route, cross-user folder isolation.

### B. Chat streaming and formatting
- [ ] `chat.py`: whitespace-preserving split (`re.findall(r"\S+\s*|\s+", answer)`).
- [ ] `_sse()` frames multi-line payloads as multiple `data:` lines per SSE spec.
- [ ] `frontend/src/api.ts`: join consecutive `data:` lines with `\n` before yielding.
- [ ] Delete `normalizeMessageText` in `ChatPanel.tsx` and its call sites entirely.
- [ ] Backend test (newline round-trip) + frontend test (stream reconstruction).
- [ ] `npm run build` into `app/static`.

### C. Retrieval correctness
- [ ] Wire `retrieval_min_score` into `retriever.py`; empty-context path says sources
      don't contain the answer instead of synthesizing from nothing.
- [ ] `chat_history_limit` actually drives `chat.py`'s history query.
- [ ] Remove dead `youtube_api_key` setting.
- [ ] `context_max_chars`: log drops, truncate whole-chunk from the low-ranked end.
- [ ] Lazy Qdrant base URL + one reused httpx client in `retriever.py`.

### D. Planner query overwrite
- [ ] `original_query` added to `AgentState`, set once at state construction (chat.py,
      mcp_server.py), never touched by the planner.
- [ ] Synthesizer answers `original_query`; critic judges against `original_query`.
- [ ] Tests: replan loop doesn't lose the original question.
- [ ] Re-run `eval/benchmark.py` only after explicit approval (API cost).

### E. Ingestion robustness
- [ ] web.py/youtube.py: embedding + upsert off the event loop, batched.
- [ ] Delete-by-`source_id` before upsert (shared helper with `delete_source`). Test.
- [ ] Configurable upload size limit, 413 past it.
- [ ] Startup: mark stuck `queued`/`running` ingest jobs as `error`.
- [ ] Fix unawaited `create_task` progress-update race in `_run_pdf_ingest_job`.
- [ ] Late chunking: rename `embed_late` to something honest (recommended: smaller
      change than implementing it for real), strip false claims from docs.

### F. Smaller hardening
- [ ] `/health` checks Postgres + Qdrant, non-200 when either is down.
- [ ] Basic rate limiting on `/auth/login`, `/auth/signup`, `/chat`.
- [ ] Refresh-token reuse detection revokes the user's whole token family. Test.
- [ ] `critic.py` logs a warning on JSON-parse failure.

### G. Retrieval measurement (report only)
- [ ] `eval/retrieval_eval.py`: golden set (20-30 Qs) against the real corpus. STOP and
      ask which documents if the local index is empty.
- [ ] Report recall@k/MRR: dense-only, current lexical rerank, cross-encoder rerank.
      Unit tests on the metric logic only, no live calls in the suite.
- [ ] Do not change the production retriever from this without showing numbers first.

### H. Needs a spec and approval before any code
- [ ] Grounding redesign spec (verdict + sentences-to-drop instead of full rewrite),
      latency/quality plan via `eval/e2e_pipeline.py`. Stop after the spec.
- [ ] Critic-context spec + critic-loop on/off ablation plan. Stop, ask for go (API cost).

### I. Documentation reconciliation (last)
- [ ] Fix "three collections" claims (CLAUDE.md, agent_memory.md, README,
      `.claude/skills/langgraph/SKILL.md`, `.claude/skills/ingestion/SKILL.md`).
- [ ] Fix README's stale default model (`llama-3.3-70b-versatile` -> `openai/gpt-oss-120b`).
- [ ] Mark `reports/docchat-audit.md` historical, matching `docs/claude_onboarding.md`.
- [ ] Update every quoted test count via grep, not memory.
- [ ] Trim HANDOFF.md to current and shorter than its ~660 lines today.

---

# Task: Inference-engineering portfolio work — status (prior session, context)

Spec: `docs/superpowers/specs/2026-09-28-inference-benchmarking-design.md`
Runbook: `docs/vllm_setup.md`

## Cache-busting + vLLM metrics + insufficient_samples (DONE, 2026-09-30)

- [x] Part A (read-only): verdict on Third sweep's cache-inflation hypothesis —
      **likely, not confirmed** (no /metrics counters existed at the time; structural
      evidence strong — identical prompts reused, `enable_prefix_caching=True` never
      disabled). See `tasks/lessons.md`.
- [x] Part B: `_bust_prompt()` (unique `request_id` per request, default ON,
      `--allow-prefix-cache` to disable, applies to all providers), vLLM `/metrics`
      polling for `local` (`_poll_metrics_during`/`_summarize_vllm_metrics` — **metric
      names UNVERIFIED against a live server**, needs first-real-run confirmation),
      >10% hit-rate warning, `insufficient_samples` (n_ok<4 nulls percentiles/decode/agg),
      `cost_per_request_local`. 28 new tests, `pytest -m "not eval" -q` 213 → 241
      passed, `ruff check .` clean.
- [x] Part C: `eval/BENCHMARK_RESULTS.md`'s Third-sweep entry corrected — cache warning
      banner, nulled OpenAI n_ok<4 cells, Groq claim walked back, KV-headroom caveat,
      quantitative decode-slowdown check (predicted 2.2x, measured 2.06x), UK-network
      TTFT caveat.
- [x] Part D plan proposed; user gave go with 5 extra constraints (positive control
      before sweep, L40S-only + $1.20/hr cap, 5-min cell timeout, preemption tracking,
      drop HF_HOME if volume dropped).
- [x] Added `preemptions_during_cell` (delta, v0.30.0's `vllm:num_preemptions_total`)
      and the 5-minute-per-cell `_CellTimeoutError` safety net, both tested.
- [x] Created `eval/positive_control.py` — proves busting+/metrics work before trusting
      a sweep. Live run: OFF 49.9% hit rate, ON 0.0% — **PASSED**.
- [x] Pod created: `omqg1cxehw89xi`, L40S Secure, `US-TX-3`, $1.09/hr, network volume
      `owdj19ss50` mounted. Fixed a real metric-name bug found via the live server:
      v0.30.0 uses `vllm:kv_cache_usage_perc`, not `vllm:gpu_cache_usage_perc`.
- [x] **Fourth sweep complete.** Verdict on the Third sweep's caching hypothesis:
      **CONFIRMED**. 0.0% prefix-cache hit rate at every cell (busting worked), TTFT
      805ms→32.9s c=1→128 (vs. the Third sweep's flat ~0.5-0.85s), KV cache hit 99.4% at
      c=128 causing 13/128 genuine client-side timeouts, 0 preemptions. No cell hit the
      5-min timeout. Pod terminated, `list-pods` confirmed empty, ~9 min lifetime,
      ~$0.16 (computed from timestamps — RunPod billing API hadn't posted yet). 246
      tests passing, `ruff check .` clean. Full writeup: `eval/BENCHMARK_RESULTS.md`'s
      "Fourth sweep" entry; Third sweep's banner updated to point to it.
- [ ] Not yet done: delete the network volume if it's no longer wanted (still incurring
      small storage cost; now holds cached model weights from this sweep).
- [ ] Not yet done: commit this session's diffs (explicitly deferred — task said "do not
      commit anything").

## Phase 1 — `local` inference provider (DONE, 2026-09-29)

- [x] `app/core/config.py` / `app/services/llm.py` — `local` provider added, tested,
      verified against a real vLLM pod (both structurally and live).
- [x] `pytest -m "not eval" -q` — 153 → 158 passed.

## Phase 2 — benchmark harness (DONE, 2026-09-30 — real sweep collected)

- [x] `eval/inference_benchmark.py` — TTFT/tokens-per-sec/cost across a concurrency
      sweep, reusing `eval/cases.py` queries, JSONL output.
- [x] Real sweep run against a live L40S pod — `groq,openai,local` × 1/4/16/64.
      Results + methodology + caveats: `eval/BENCHMARK_RESULTS.md`. Raw data:
      `data/inference_benchmark.jsonl`. Headline: `local` held per-request throughput
      roughly flat 1→64 concurrency (continuous batching working).
- [x] Pod `gjyx6ey1sabps0` terminated. Network volume `owdj19ss50` (50GB, `US-TX-3`)
      still exists, set up for a future pod to reuse.

## Measurement-bug fixes (DONE, 2026-09-30)

Triggered by the first sweep's own contamination: 50% of `openai` requests at c=16/64
had `output_tokens=0`. Root-caused: `gpt-5.6-luna` is a reasoning model that can spend
its whole `max_tokens` budget on hidden reasoning and return zero visible content — see
`tasks/lessons.md` 2026-09-30.

- [x] `app/services/llm.py` — additive `usage_sink` param on `chat_stream`/`_*_stream`
      (real `finish_reason`/token counts), zero effect on any existing caller. Also
      fixed a latent IndexError on the usage-bearing empty-`choices` final chunk.
- [x] `eval/inference_benchmark.py` rewritten: fallback unconditionally disabled per
      run, `status` (ok/error/empty) per request, real token counts, `error_rate`/
      `empty_rate`, `aggregate_tok_s`/`decode_tok_s_p50`, `--gpu-cost-per-hr` and
      `--openai-model` CLI flags, concurrency=1 runs every query sequentially.
- [x] 30 new tests (`test_llm_usage_sink.py`, rewritten `test_inference_benchmark_metrics.py`,
      new `test_inference_benchmark_live_logic.py`). `pytest -m "not eval" -q` —
      174 → 204 passed. `ruff check .` clean.
- [x] **Live re-run done, 2026-09-30** (pod `nkypvybb62jggb`, A100 SXM, $1.59/hr,
      terminated after). Found and fixed two more real bugs live: Groq's SDK version
      doesn't accept `stream_options` (crashed 100%), and `wall_time_s` was wrong for
      the new sequential concurrency=1 case (inflated `local`'s c=1 throughput 6.6x).
      Both fixed, verified, and documented in `tasks/lessons.md` + `eval/BENCHMARK_RESULTS.md`.
- [x] Diagnosed (not fixed) a fourth issue: Groq's configured model
      (`openai/gpt-oss-120b`) is also a reasoning model — same signature as the OpenAI
      bug. A `--groq-model` override (mirroring `--openai-model`) is the natural fix,
      not yet built.

## Part B — capture realistic prompts (DONE, 2026-09-30)

- [x] User ingested real sources: `pdf_chunks` 257, `youtube_chunks` 5, `web_chunks` 23.
- [x] `eval/capture_bench_prompts.py` — runs the real planner→retriever→synthesizer
      pipeline for the 8 eval queries, captures exact messages via a `chat_complete`
      patch (same pattern `tests/test_llm_temperature.py` uses — no app code changes).
      Real token counts via the `tokenizers` package loading Qwen2.5's tokenizer.
- [x] Run for real against ingested Qdrant data — 8/8 captured, `data/bench_prompts.jsonl`.
      **Realistic prompts are 40–100x larger than what Phase 2 benchmarked**:
      3752–6801 input tokens (real retrieval context) vs. the bare 20–90 token queries
      `eval/cases.py` sends with no context. Phase 2's numbers describe a
      short-prompt workload, not DocChat's real one — worth a follow-up sweep sized to
      these real prompts before trusting Phase 2's TTFT/throughput numbers for
      production-shaped traffic.
- [x] 6 new tests (`test_capture_bench_prompts.py`). `pytest -m "not eval" -q` —
      204 → 210 passed. `ruff check .` clean.
- [x] Fixed `.env`'s `QDRANT_HOST=qdrant` not resolving on the host (docker-compose-only
      hostname) — see `tasks/lessons.md`. Also switched `.env`'s `LLM_PROVIDER` from
      `local` (pointed at the now-terminated pod) to `groq` so the planner step's LLM
      call actually works; `local` needs a live pod again before it's usable.

## Real-prompts sweep (DONE, 2026-09-30)

- [x] `eval/inference_benchmark.py` gained `--prompts-file` (loads
      `eval/capture_bench_prompts.py`'s JSONL, sends each row's real captured
      `messages` instead of a bare query). `_run_request`/`_run_concurrency_level`/
      `_run_provider` refactored `query: str` → `messages: list[dict]` throughout.
- [x] 3 new tests (`_load_prompts`). `pytest -m "not eval" -q` — 210 → 213 passed.
      `ruff check .` clean.
- [x] **Run for real** against a pod (A100 SXM `cr5nqn5cek9d18`, $1.59/hr, terminated
      after), `openai` (`gpt-4.1`) + `local`, `--max-tokens 1400` matching production.
      Results: `eval/BENCHMARK_RESULTS.md` ("Third sweep").
- [x] **The actual headline finding**: both OpenAI and Groq hit real `429` rate limits
      at low concurrency once prompts are real-sized (OpenAI 100% error at c=4, 94-98%
      at c=16/64 — confirmed `HTTPStatusError: 429` in the raw data, not a bug).
      `local` had 0% error through c=64. This is the concrete argument for
      self-hosting — no account-level rate ceiling, not just a cost/throughput number.

## Still open / not started

- [ ] **Blocked step from Phase 1 verification** — a real `/api/v1/chat` query with 2+
      sources, checking planner/critic JSON parsing and context-length errors in the
      logs. Ingestion blocker is gone now (real sources exist) — this can be done
      whenever, doesn't need a pod (works fine on `groq`).
- [ ] **Phase 3** — quantization comparison (FP16 vs AWQ/GPTQ on Qwen2.5-7B-Instruct),
      checked against the critic eval harness for quality regression. Not specced yet.
- [ ] **Phase 4** — continuous-batching proof (serial vs concurrent throughput curve),
      optionally a second serving engine (TGI/SGLang) for an engine comparison table.
      Not specced yet.
- [ ] **Phase 5** — write-up / resume bullet. Real numbers now exist and the headline
      finding is strong (rate limits, not just cost/throughput) — this is close to
      write-up-ready.
- [ ] **`--groq-model` override** — same fix as `--openai-model`, for Groq's
      reasoning-model default. Would let a Groq run separate "wrong model" from "real
      rate limit" the same way the OpenAI fix did. Small, doesn't need a pod.
