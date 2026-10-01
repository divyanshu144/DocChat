# DocChat — Session Handoff

**Branch:** `chore/inference-complete-and-hardening` (off `feat/openai-sse-chat-quality`,
which is merged into `master`)
**Last updated:** 2026-10-01
**Status:** Working through the Part 1 (inference) and Part 2 (codebase hardening)
checklist in `tasks/todo.md`, one commit per item, nothing pushed or merged yet.
**No GPU pod is running** — `omqg1cxehw89xi` (L40S 48GB, $1.09/hr, `US-TX-3`) was
terminated after the fourth sweep; `list-pods` confirmed empty. Lifetime ~9 minutes
(18:20:39–~18:29:40 UTC), cost ~$0.16 (RunPod's billing API had not posted the record
yet at check time — this is a computed estimate from the real create/terminate
timestamps, not a guess at the rate). **The network volume (`owdj19ss50`, 50GB,
`US-TX-3`) was used for the first time this session** — `HF_HOME` pointed at it, the
model wasn't cached there yet (fresh 24.2s download), but Qwen2.5-7B-Instruct's weights
are now cached on it for any future pod in `US-TX-3`. Still incurring its own small
ongoing storage cost until deleted.

---

## Current State

### Built in this branch (2026-10-01) — --groq-model override

Mirrors `--openai-model` exactly. Groq's configured default (`settings.chat_model`,
`openai/gpt-oss-120b`) is also a reasoning model, same problem the OpenAI override was
built to work around (see the Second sweep entry below). The override only touches
`settings.chat_model` for the duration of `_run_provider`'s own run, restored in the
`finally` block, and only applies when `provider == "groq"`. Two new tests mirroring the
existing OpenAI override tests. `pytest -m "not eval" -q` 257 to 259 passed, `ruff check .`
clean.

### Fixed in this branch (2026-10-01) — Part 2 A, step 1: auth on ingest and folders

Every route in `app/api/ingest.py` (9 routes) and `app/api/folders.py` (4 routes) had
zero authentication. Any caller, logged in or not, could ingest, delete, or list sources,
and create, rename, delete, or list folders. Added `Depends(get_current_user)` to all
13 routes. Folders are not yet scoped per user (that is the next commit, since it needs
a schema change); this step only requires that the caller is authenticated at all.

13 new tests (9 for ingest, 4 for folders) asserting 401 with no Authorization header,
using a client with no dependency override so the real auth check runs. The existing
happy-path tests for both files now override `get_current_user` (mirroring the pattern
`app/api/conversations.py`'s tests already used), since without the override they would
now 401 instead of testing what they are meant to test.

`ruff check .` clean, `pytest -m "not eval" -q` 276 to 289 passed.

### Part 1 (inference track) closed out for now (2026-10-01)

Asked about network volume `owdj19ss50` (50GB, `US-TX-3`, still holds cached
Qwen2.5-7B-Instruct weights from the Fourth sweep). User chose to keep it, since Phase
3/4's live sweeps would reuse the cached weights. Not deleted, still incurring its own
small storage cost.

**Part 1 status:** items 1 (`--groq-model`), 2 (blocked e2e check), 3 (metric-name
comment fix), 5 (write-up), and 6 (this cleanup) are done. Item 4 (Phase 3 quantization
comparison, Phase 4 batching proof) is spec-plus-dry-run-tests complete and explicitly
stopped, waiting for a go with GPU, hourly rate, duration, and cost cap before any pod
is created for either sweep. Moving on to Part 2 (codebase review fixes) now; will
surface the Phase 3/4 pod request again once Part 2 reaches a natural stopping point.

### Built in this branch (2026-10-01) — Phase 5 write-up

`docs/inference-writeup.md`: a short engineering write-up built only from numbers
already in `eval/BENCHMARK_RESULTS.md`, no new claim added. Tells the measurement
mistakes in order (wrong workload, a wall-time bug that inflated one throughput number
over 6x, cache-contaminated latency), the corrected findings (hosted rate limits bind
before latency, self-hosting trades the account-tier ceiling for a KV-cache one you can
see and size yourself, cost is idle-time-dominated, decode slowdown under load matches a
memory-bandwidth calculation), what was never tested (the A100's real KV limit,
quantization, a direct serial-vs-concurrent proof, a second serving engine, a clean Groq
baseline at real prompt sizes), and which cost figures used placeholder rates. Updated
the README's "Inference benchmarking" section to match the corrected framing (dropped
the "no such ceiling" overclaim) and link to the new write-up. `ruff check .` clean,
`pytest -m "not eval" -q` 276 passed (no code changed).

### Built in this branch (2026-10-01) — Phase 4 spec: batching proof

Spec: `docs/superpowers/specs/2026-10-01-batching-proof-design.md`. Every sweep so far
only ever showed vLLM's concurrent throughput climbing with load, which is evidence
continuous batching does something but never a direct before/after at the same batch
size. New `--serial` flag on `eval/inference_benchmark.py`: runs a concurrency level's
requests strictly one at a time (`_run_concurrency_level` gained a `serial: bool` param
that awaits in a loop instead of `asyncio.gather`), so the resulting wall time is a true
no-batching baseline directly comparable to a normal run at the same concurrency. Each
output row is now tagged `mode: "serial"` or `"concurrent"` so the two can be told apart
in `data/inference_benchmark.jsonl`.

4 new tests, including one that actually proves serial mode prevents overlap (tracks a
live in-flight counter, asserts it never exceeds 1) rather than just counting calls, plus
a sanity check that concurrent mode does overlap (so the serial test's methodology means
something). Stopped after the spec and these dry-run tests, no pod, per the task's own
instruction. `pytest -m "not eval" -q` 272 to 276 passed, `ruff check .` clean.

**Both Phase 3 and Phase 4 are now spec-plus-dry-run-complete. Waiting for a go before
any pod is created for either live sweep.**

### Built in this branch (2026-10-01) — Phase 3 spec: quantization comparison

Spec: `docs/superpowers/specs/2026-10-01-quantization-comparison-design.md`. Compares
FP16 against AWQ (and GPTQ if a maintained build exists) on Qwen2.5-7B-Instruct, one pod
serving all three sequentially rather than three pods. The quality side is the point:
there is no existing local-FP16 baseline for `eval/benchmark.py`'s critic accuracy
numbers anywhere in this repo (the recorded 5/5 precision/recall history used Groq's
hosted model), so the FP16 serving's own `eval/benchmark.py` run is the baseline this
whole phase's quality comparison rests on, not a sanity check.

New `eval/quantization_compare.py`: reads two servings' rows out of
`data/inference_benchmark.jsonl` by timestamp window (the same provider name, `local`,
writes every serving to the same file) and prints a speed/cost delta table. Pure data
transformation, no network calls. 13 new tests. Stopped after the spec and these
dry-run tests, per the task's own instruction, waiting for a go before any pod.
`pytest -m "not eval" -q` 259 to 272 passed, `ruff check .` clean.

### Fixed in this branch (2026-10-01) — stale "unverified" comment on vLLM metric names

The module docstring already said the `_VLLM_METRIC_CANDIDATES` names were verified
against a live vLLM v0.30.0 server (from the Fourth sweep), but the comment directly
above the constant still said "UNVERIFIED against a live v0.30.0 server", left over from
before that sweep ran. Fixed to say verified, noted which names matched as-is versus
the one that needed a fallback (`kv_cache_usage_perc`), and added an explicit warning
that these names are specific to v0.30.0, not guaranteed on another vLLM version. No
test or behavior change, comment only.

### Ran in this branch (2026-10-01) — blocked e2e chat check, found source_chunks was empty

The current code only ever queries the `source_chunks` Qdrant collection (confirmed:
`app/agent/nodes/retriever.py` has no legacy fallback). That collection did not exist on
the local Qdrant instance yet, even though the old `pdf_chunks`/`youtube_chunks`/
`web_chunks` collections still had the data from an earlier session (257/5/23 points).
Those legacy collections are only read by `/sources` listing and deletion cleanup, not
by retrieval, so from the current code's point of view the index was empty. Stopped and
asked per the task's own instruction instead of faking a result.

User chose to ingest the leftover PDF in `uploads/` (all 4 files there turned out to be
byte-identical, MD5 `58c085...`, so they dedupe to 1 source by DocChat's content-hash
`source_id`) plus one real web page for a second distinct source
(`https://en.wikipedia.org/wiki/Retrieval-augmented_generation`).

Ran a real end-to-end check: started a host-side `uvicorn` instance of the current
branch's code (not the stale 19-hour-old Docker container, which predates the
RAG-normalization merge and still writes the old per-type collections) with
`QDRANT_HOST=localhost` and `DATABASE_URL` pointed at the host-exposed Postgres port
(5433), signed up a real user, ingested both sources through the real HTTP endpoints,
then sent a real `/api/v1/chat` query touching both sources on `LLM_PROVIDER=groq`.

Result: all 5 pipeline stages ran (planner, retriever, synthesizer, grounding, critic).
No planner or critic JSON parse failures and no context-length errors in the logs. One
transient Groq `429` happened mid-run and the SDK's own retry logic handled it
automatically (3 second backoff, succeeded on retry), visible in the log, not masked.
The critic correctly let through an answer that admitted the PDF had no relevant
content for the question, instead of guessing. This is one real run, not exhaustive, so
it confirms the happy path works but does not rule out a rarer parse failure on
different input. Host-side test server stopped after the check; the two real sources
stay ingested in `source_chunks` for later work (useful for item G's retrieval eval).

### Built in this branch (2026-09-30) — cache-busting, vLLM metrics, insufficient_samples

Triggered by a review of the Third sweep: c=64 `local` TTFT of 0.5-0.85s is physically
implausible for ~320k prefill tokens with no caching (~10k prefill tok/s on an A100
implies tens of seconds). Verdict from code inspection: **likely** cache-inflated, not
confirmed (no `/metrics` counters existed at the time) — see
`eval/BENCHMARK_RESULTS.md`'s prominent warning on the Third sweep entry.

- **Cache busting, default ON** — `_bust_prompt()` prepends a unique `request_id: <uuid4>`
  line to the first message of every request (system message when one exists, else the
  lone user message), so no two requests in a sweep share a prefix. `--allow-prefix-cache`
  disables it. Applies to every provider (OpenAI/Groq cache long prompts too, not just
  vLLM).
- **vLLM `/metrics` polling** (local only) — scraped every ~1s during each cell via
  `_poll_metrics_during`; `summary["vllm_metrics"]` gets prefix-cache hit rate (as a
  delta over the cell, not an averaged ratio — counters are monotonic), peak KV cache
  usage %, peak requests waiting/running. **The exact Prometheus metric names are
  UNVERIFIED against a live vLLM v0.30.0 server** — this work was explicitly code-only,
  no pod. First live run must confirm/correct the candidate names in
  `_VLLM_METRIC_CANDIDATES`. A loud warning prints if hit rate exceeds 10% while
  busting is ON — that combination means busting isn't reaching the server or the
  metric names are wrong.
- **`insufficient_samples`** — cells with `n_ok < 4` now get `None` (not omitted, not a
  percentile of 1-3 points) for `ttft_p*`/`latency_p*`/`decode_tok_s_p50`/
  `aggregate_tok_s`, flagged explicitly. `cost_per_request_local` added
  (`gpu $/hr × wall time / n_ok`).
- **28 new tests**, `pytest -m "not eval" -q` 213 → 241 passed, `ruff check .` clean.
  (Further extended to 246 in the Fourth-sweep entry below.)
- **`eval/BENCHMARK_RESULTS.md`'s Third-sweep entry corrected**: prominent cache-warning
  banner added; OpenAI cells with `n_ok < 4` nulled instead of showing numbers computed
  from 0-1 samples; Groq-failure-mode claim walked back (the earlier smoke test used a
  reasoning model, inconclusive, not "identical failure mode"); added the KV-headroom
  caveat (A100 never came close to full) and a quantitative memory-bandwidth check on
  the decode-speed slowdown (predicted 2.2x, measured 2.06x — close match); noted TTFT
  includes real UK-to-pod-region network time.
- **Next**: a fourth sweep, cache-busted + metrics-instrumented, to actually confirm or
  rule out the caching hypothesis with real counter data. Planned, not yet run — needs
  an explicit go before any pod is created.

### Built in this branch (2026-09-30) — Fourth sweep: verdict CONFIRMED, pod + live run

User gave explicit go with 5 added constraints (positive control before trusting the
sweep, L40S-only capped at $1.20/hr, 5-min per-cell timeout, preemption tracking, drop
`HF_HOME` if the network volume gets dropped in a fallback). All five honored.

- **Code**: `preemptions_during_cell` added to `_summarize_vllm_metrics` (delta over the
  cell, since `num_preemptions` is a monotonic counter — "peak" doesn't apply to a
  counter, documented as a deliberate reinterpretation of the ask). `_CellTimeoutError` +
  a 300s `asyncio.wait_for` around each cell — on timeout, finished cells' rows are saved
  and the sweep aborts cleanly instead of hanging or crashing. New
  `eval/positive_control.py`: sends one prompt 2x busting-OFF then 2x busting-ON, prints
  the literal `/metrics` names it matched, exits 1 (refuses to let the sweep proceed) if
  it doesn't see OFF-high/ON-low. 246 tests passing (241 → 246), `ruff check .` clean.
- **Pod**: `omqg1cxehw89xi`, L40S 48GB Secure, `US-TX-3`, $1.09/hr (under the $1.20 cap),
  network volume `owdj19ss50` mounted, `HF_HOME` on it. Startup clean, no CUDA/driver
  errors, `Application startup complete` at ~2min (well under the 6-min kill rule).
  Health checks (`/v1/models` + a real completion) passed.
- **A real metric-name bug was caught before it could corrupt the sweep**: this
  server's `/metrics` exposes KV usage as `vllm:kv_cache_usage_perc`, not the
  `vllm:gpu_cache_usage_perc` name `_VLLM_METRIC_CANDIDATES` had guessed. Fixed with the
  old name kept as a fallback candidate. `prefix_cache_queries_total`,
  `prefix_cache_hits_total`, `num_preemptions_total`, `num_requests_waiting`,
  `num_requests_running` all matched their first-guess name as-is.
- **Positive control: PASSED.** Busting OFF → 49.9% prefix-cache hit rate (real hit on
  repeat). Busting ON → 0.0%. Proceeded to the sweep.
- **Sweep**: local only, concurrency 1/4/16/64/128, real prompts, busting ON, no cell
  hit the 5-min timeout (longest wall time: 104.6s at c=128). **Prefix-cache hit rate was
  0.0% at every cell** in the real sweep too. TTFT climbed 805ms → 32.9s, c=1→128 (vs.
  the Third sweep's suspiciously flat ~0.5-0.85s) — **the caching-inflation hypothesis is
  now CONFIRMED, not just likely.** At c=128, KV cache hit 99.4% full and 13/128
  requests failed with client-side `ReadTimeout`/`PoolTimeout` — genuine queueing
  pressure near capacity, 0 preemptions throughout (vLLM used the waiting queue, not
  eviction). Full table + analysis: `eval/BENCHMARK_RESULTS.md`'s new "Fourth sweep"
  entry; the Third sweep's entry now has an updated banner pointing to it.
- **Network volume actually used for the first time**: model wasn't cached on it yet
  (fresh download, 24.2s), but is now — a future pod in `US-TX-3` mounting this volume
  should skip the download.
- **Wrap-up**: pod terminated, `list-pods` confirmed empty. Lifetime ~9 min, cost ~$0.16
  (computed from real timestamps; RunPod's billing API hadn't posted the record yet).

### Built in this branch (2026-09-30) — real-prompts sweep, and the actual headline finding

`eval/inference_benchmark.py` gained `--prompts-file` (loads `eval/capture_bench_prompts.py`'s
JSONL output, sends each row's real captured `messages` as-is instead of a bare query —
`_run_request`/`_run_concurrency_level`/`_run_provider` refactored from `query: str` to
`messages: list[dict]` throughout). 3 new tests (`_load_prompts`). Ran it for real
against a pod (A100 SXM, `cr5nqn5cek9d18`, $1.59/hr, terminated after) with
`--max-tokens 1400` (matching `synthesizer_node`'s real call) — full writeup in
`eval/BENCHMARK_RESULTS.md` ("Third sweep").

**Every prior sweep measured the wrong workload** — `eval/cases.py`'s bare queries carry
no context (20-90 tokens); real DocChat prompts are 3752-6801 tokens. Sized correctly,
the finding changes: **both OpenAI (`gpt-4.1`) and Groq hit real `429` rate limits at
low concurrency** — OpenAI 100% error at concurrency 4, 94-98% at 16/64, confirmed
`HTTPStatusError: 429` in the raw JSONL, not a bug. `local` had 0% error at every level
through 64 concurrent real-sized requests. **This is the actual argument for
self-hosting** — a rented GPU has no account-level per-minute quota, which is a more
concrete story than a throughput or cost number. `local`'s cost-per-token still improved
~18x from idle to loaded ($6.24 → $0.34 per 1M tokens, c=1→c=64), same shape as before
but now against a real workload.

### Built in this branch (2026-09-30) — Part B, realistic prompt capture

**`eval/capture_bench_prompts.py`** — runs the real planner→retriever→synthesizer
pipeline for the 8 `eval/cases.py` queries against real ingested Qdrant data
(`pdf_chunks` 257, `youtube_chunks` 5, `web_chunks` 23), capturing the exact messages
`synthesizer_node` would send via a `chat_complete` patch (same interception pattern
`tests/test_llm_temperature.py` already used — zero app code changes). Real input-token
counts via the `tokenizers` package loading Qwen2.5's tokenizer. Output:
`data/bench_prompts.jsonl`, overwritten each run (a snapshot against the current index,
not an append-only log like the benchmark's JSONL). 6 new tests
(`tests/test_capture_bench_prompts.py`) for the pure logic.

**The headline finding: Phase 2's benchmark numbers describe the wrong workload.**
Real DocChat prompts are **3752–6801 input tokens** (planner-selected sources +
8–21 real retrieved chunks + conversation-history formatting); Phase 2 benchmarked
`eval/cases.py`'s bare queries directly with **zero context, 20–90 tokens**. Every
TTFT/throughput/cost number from Phase 2 was measured against a workload roughly
40–100x smaller than what the app actually sends. Before trusting any of those numbers
for a real capacity or cost claim, they need re-measuring against prompts this size —
tracked as a follow-up, needs a pod.

Also fixed along the way: `.env`'s `QDRANT_HOST=qdrant` only resolves inside the
docker-compose network, not on the host running this script directly — see
`tasks/lessons.md`. And `.env`'s `LLM_PROVIDER` was still `local`, pointing at the
terminated pod from the last session; switched to `groq` so the planner step's real LLM
call works. `local` needs a live pod again before it's usable.

### Built in this branch (2026-09-30) — live re-run found and fixed 2 more bugs

The harness fixes below were unit-tested but never run live (explicitly out of scope
for that task — no pod). This session did the live re-run: real pod
(`nkypvybb62jggb`, A100 SXM, $1.59/hr, terminated after), real sweep, real bugs the
unit tests couldn't have caught because they only exist when a real provider is on the
other end. Full writeup: `eval/BENCHMARK_RESULTS.md` ("Second sweep" entry).

1. **`_groq_stream`'s `stream_options` request crashed the installed Groq SDK** —
   `TypeError: AsyncCompletions.create() got an unexpected keyword argument
   'stream_options'`. 100% Groq error rate on first attempt. Fixed with a
   catch-and-retry-without-it in `app/services/llm.py` — degrades to no usage data for
   Groq rather than failing the request over a capability gap.
2. **`wall_time_s = max(total_s)` was wrong for the new sequential concurrency=1
   case** — correct for concurrent requests, wrong once concurrency=1 started running
   every query sequentially (this session's own earlier fix): sequential requests don't
   overlap, so real wall time is close to their *sum*, not their max. Silently
   inflated `local`'s concurrency=1 throughput 6.6x (592 → 89.7 tok/s after the fix).
   Caught by the number being implausibly *higher* at c=1 than c=4. Fixed by measuring
   real wall-clock time with `time.monotonic()` at the call site instead of inferring
   it from request data after the fact. See `tasks/lessons.md` for the full writeup —
   this is a "measure, don't infer" lesson worth internalizing, not just patching.
3. **Diagnosed, not yet fixed: Groq's configured model (`openai/gpt-oss-120b`) is also
   a reasoning model** — same signature as the OpenAI bug below (`output_tokens=256`
   per real usage, `finish_reason=length`, zero visible content). A `--groq-model`
   override mirroring `--openai-model` is the natural fix.
4. **Also confirmed, not a bug**: at concurrency=64, Groq genuinely rate-limits
   (`429 RateLimitError`, RPM/TPM on the `on_demand` tier) — correctly surfaced as
   visible errors instead of masked by fallback, validating the earlier decision to
   disable fallback for benchmark runs.

Corrected numbers (1 new test, `pytest -m "not eval" -q` 203 → 204): `local` still beats
both hosted providers on TTFT at every concurrency level, and the headline finding is
now sharper than before the fix — `local`'s **$/1M output tokens improves 44x from c=1
to c=64** ($4.93 → $0.11), showing self-hosted GPU cost is idle-time-dominated and only
cheap under real concurrent load. The pre-fix numbers hid this entirely (flat, wrong
cost at every level).

### Built in this branch (2026-09-30) — measurement-bug fixes to the benchmark harness

Triggered by re-reading the first sweep's own results: half of `openai`'s requests at
c=16/c=64 had `output_tokens=0`. Root-caused (not guessed) by sending each of the 8 eval
queries directly to `gpt-5.6-luna` with `max_tokens=128` and reading `finish_reason` +
`usage.completion_tokens_details.reasoning_tokens`: 6/8 spent the *entire* 128-token
budget on hidden reasoning and got truncated (`finish_reason: length`) before emitting
one visible character. Not a benchmark bug — a reasoning model with a budget too small
to survive its own reasoning phase.

- **`app/services/llm.py`** — `chat_stream()` and each private `_*_stream` gained an
  optional `usage_sink: dict | None = None` parameter, filled in-place with
  `prompt_tokens`/`completion_tokens`/`finish_reason` when provided. Purely additive —
  every existing caller passes nothing and sends no extra request field; verified with
  dedicated tests (`tests/test_llm_usage_sink.py`) asserting the exact payload sent
  with and without it. Also fixed a latent bug this surfaced: the OpenAI/local streaming
  parsers indexed `choices[0]` unconditionally, which would IndexError on the
  usage-bearing final chunk (`choices: []`) — guarded now.
- **`eval/inference_benchmark.py`** rewritten:
  - Fallback is **unconditionally disabled** for every benchmark run
    (`settings.fallback_llm_provider = "none"` scoped inside `_run_provider`) — a
    benchmark whose provider identity can silently change mid-run isn't measuring what
    it claims to. A failed request is recorded as `status="error"` with `error_type`,
    never silently retried against a different provider.
  - New per-request schema: `status` (ok/error/empty), `error_type`, `finish_reason`,
    `input_tokens`, `output_tokens` (real `usage.completion_tokens`, not a chunk-count
    proxy — falls back to the proxy only when a provider doesn't return usage),
    `ttft_s`/`total_s` (`ttft_s` is `None`, not guessed, for anything that isn't "ok").
  - `_summarize()` computes percentiles/throughput on `status=="ok"` requests only;
    `error_rate`/`empty_rate` are separate top-level fields, checked before trusting any
    percentile above them. Added `aggregate_tok_s` (throughput under load — total tokens
    over wall time, not summed per-request rates) and `decode_tok_s_p50` (post-TTFT
    generation speed, excluding non-positive decode windows). Old `avg_tokens_per_sec`
    kept as `legacy_avg_tokens_per_sec`, explicitly labelled as the weaker statistic.
  - `--gpu-cost-per-hr` is now a CLI flag (was a hardcoded placeholder constant);
    `cost_per_1m_output_tokens_local` derived from measured `aggregate_tok_s`, `None`
    (not 0 or inf) when nothing was generated.
  - `--openai-model` override flag, since the configured default can be a reasoning
    model unsuitable for a throughput benchmark (see above) — only affects this
    script's own run, production `settings.openai_chat_model` is untouched.
  - `concurrency=1` now runs every query in the set sequentially instead of firing just
    one request — n=1 can't produce a percentile, which was the root of the earlier
    `local` concurrency=1 rows only having one sample.
- **29 new tests** across `tests/test_llm_usage_sink.py`,
  `tests/test_inference_benchmark_metrics.py` (rewritten for the new schema),
  `tests/test_inference_benchmark_live_logic.py` (new — mocks `llm.chat_stream` to
  verify ok/empty/error classification and that `_run_provider` disables fallback and
  restores every setting it touches, even on exception).
- **Not yet done:** Part B of this task (`eval/capture_bench_prompts.py`, capturing
  realistic DocChat-sized prompts via the real retriever→synthesizer pipeline) is
  blocked on real ingested Qdrant sources — user is ingesting some. No live re-run of
  the fixed harness against a real pod has happened yet either (explicitly out of scope
  for this task — no RunPod pod was created).

### Built in this branch (2026-09-30) — Phase 2, inference benchmark harness

- **`eval/inference_benchmark.py`** — TTFT / output-tokens-per-sec / cost across a
  concurrency sweep (default 1/4/16/64), reusing `eval/cases.py`'s queries rather than a
  second corpus. Talks to whichever provider(s) are named via the same `chat_stream`
  seam the app itself uses, temporarily flipping `settings.llm_provider` per provider
  under test (client cache reset each time, same pattern the provider-seam tests use).
  Raw per-request results append to a JSONL file; deliberately measures performance
  only, never answer quality (that stays the critic eval harness's job).
- **16 new unit tests** (`tests/test_inference_benchmark_metrics.py`) for the pure logic
  — `_percentile`, `_summarize`, `_cost_for_run`, `_fmt_row`. No live call in the suite,
  same bar as `eval/benchmark.py`.
- **First real sweep collected 2026-09-30.** Full results, methodology, and caveats in
  `eval/BENCHMARK_RESULTS.md`. Headline: `local` (self-hosted vLLM/L40S) held
  per-request throughput roughly flat (37.3 → 33.6 tok/s) across a 1→64 concurrency
  sweep — continuous batching visibly absorbing the load — with lower TTFT than both
  Groq and OpenAI at every concurrency level. **Groq's numbers from that run are not
  trustworthy** — 61% of Groq requests silently fell back to OpenAI mid-sweep (most
  likely real rate-limiting under burst concurrency); see the results file for the
  full caveat before citing a Groq number from it.
- **Cost table uses placeholder rates** for Groq/OpenAI/Mistral (`$/1M output tokens` in
  `eval/inference_benchmark.py`) — not fetched live, not fully verified (Groq's pricing
  page doesn't list per-model rates; OpenAI's blocked an automated fetch). Verify before
  quoting a cost number from this externally.

**Two operational findings from getting the pod up, both now fixed in docs/lessons:**

1. `docker compose restart` does **not** reload `.env` — it restarts the existing
   container, whose environment is frozen from whenever it was created. Must use
   `docker compose up -d <service>` to actually pick up an `.env` change. Caught because
   two real `/api/v1/chat` queries kept hitting `api.openai.com` instead of the local
   pod despite `.env` and a restart both being "done." See `tasks/lessons.md`
   2026-09-29. Recreating `app` this way cascaded into recreating `postgres` and
   `qdrant` too, which surfaced **pre-existing WAL/ID-tracker corruption** in
   `postgres_data`/`qdrant_data` that had sat dormant for two months (neither process
   had done a real restart-recovery sequence in that time). Both were wiped (personal
   project, user accepted the data loss) and reinitialized empty — **local dev DB and
   Qdrant collections are now empty, 0 ingested sources.**
2. **RunPod bills GPU time for a `Stopped`/`EXITED` pod, not just a running one** —
   real billing data showed $1.87 charged for a pod that crashed in ~2 minutes but sat
   `EXITED` (not yet `Terminated`) for ~2.5 hours. `docs/vllm_setup.md` §6 corrected:
   use **Terminate**, not Stop, as the actual cost control. See `tasks/lessons.md`
   2026-09-30.

**Also changed this session:** the global `~/.claude/hooks/pre-tool-use.sh`
(`swarm-safety`) guard now asks for approval on `rm -rf` instead of hard-blocking it
(other guarded categories — force-push, `DROP TABLE`, etc. — still hard-block,
unchanged). Not part of this repo, but relevant to anyone continuing this work with the
same agent setup.

### Built in this branch (2026-09-28 → 2026-09-29) — `local` inference provider

Goal: use this repo as a portfolio piece for LLM **inference-engineering** roles
(vLLM/serving-infra), not just LLM application engineering. Spec:
`docs/superpowers/specs/2026-09-28-inference-benchmarking-design.md`. Phase 1 only —
Phases 2–5 (benchmark harness, quantization comparison, batching proof, write-up) are
still ahead and each gets its own spec before code.

- **`app/services/llm.py` gained a fourth provider, `local`** — a self-hosted model
  served by vLLM's OpenAI-compatible server, reachable via `LLM_PROVIDER=local`. New
  settings: `local_base_url`, `local_chat_model`, `local_api_key` (bearer header sent
  only when the key is set).
- `_local_complete` / `_local_stream` mirror `_openai_complete` / `_openai_stream` but
  are simpler — vLLM's server takes plain `max_tokens` and doesn't have OpenAI's
  reasoning-model `max_completion_tokens` split or temperature-rejection quirk, so
  there's no drop-and-retry dance.
- **Deliberately not in the fallback chain.** `local` is not added to
  `_can_fallback_to_openai` — it's a benchmarking target on a rented GPU that may not
  even be running, not a reliability path.
- **Structural tests only, same bar as the Mistral path** — mocked httpx, no live GPU
  call in CI. 5 new tests in `tests/test_llm_provider_seam.py`. **Not yet exercised
  against a real vLLM box.**
- **Next:** rent a GPU, serve Qwen2.5-7B-Instruct with vLLM, smoke-test
  `LLM_PROVIDER=local` for real, then Phase 2 — `eval/inference_benchmark.py`
  (TTFT / tokens-per-sec / cost across a concurrency sweep, comparing `local` against
  Groq/OpenAI). Costs real money per hour; never automate a run against it.

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
pytest -m "not eval" -q     # 246 passed, 0 failed
```

Was 241 until the Fourth sweep's preemption-tracking + cell-timeout logic added 5 tests
(2026-09-30). Before that, 213 until cache-busting + vLLM metrics + insufficient_samples
added 28 tests. Before that, 210 until `--prompts-file` support added 3 `_load_prompts`
tests.
Before that, 204 until Part B's prompt capture added 6 tests. Before that, 203
until the live re-run's sequential-wall-time fix added 1 test.
Before that, 174 until the measurement-bug fixes (usage_sink, error/empty status, decode
throughput — see below) added 29 tests (2026-09-30). Before that, 158 until the
inference benchmark harness added 16 tests. Before that, 153 until the `local`
provider seam added 5 tests (2026-09-29). Before that, 109 until the critic
rejection sink added 5 tests (2026-08-15).

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
