# Benchmark harness improvements: design (2026-10-06, Phase 1)

Six additive improvements to the schema-v2 sustained benchmark and its analysis tools. Schema stays v2: every new field
is optional, old runs still load, and the comparability checks in `compare_sustained_runs` and the capacity tool's
SLO gating are unchanged. Offline only; nothing here is a measurement.

## 1. p99 latency and p99 TTFT
`summarize` adds `latency_p99_s` and `ttft_p99_s`, available only when successes reach `max(min_samples, 100)`,
otherwise null (nearest-rank, as for p95). With 100 samples p99 is the second-largest value, so it is descriptive.
`capacity_plan` reports the worst repeat p99 per level and never uses it for SLO gating. `repeat_summary` statistics
are untouched, so run-to-run comparison cannot gain a key that older runs lack.

## 2. Cost per request and per 1K output tokens
`capacity_plan` adds `cost_per_request_usd` (conservative requests/s of the selected level) and
`cost_per_1k_output_tokens_usd` (mean token rate) from `hourly_cost_usd`. Both are skipped when the cost is null or the
rate is unknown. Basis: GPU rental only, linear scaling; storage, egress and idle time excluded.

## 3. Prefix caching on versus off
Each cell's `engine_counter_changes` event gains an optional `prefix_cache` summary (queries, hits, hit rate) from the
`/metrics` counters, with `unavailable` plus a reason on missing series or counter resets. A new
`compare_prefix_caching` first runs the existing comparability checks, then additionally requires the same model and
quantization and an explicit `prefix_caching` true (baseline) versus false (variant) in the deployment manifests. It adds a
per-cell hit-rate column for each side. With `cache_mode: bust` both arms are expected near 0%, so it says that result is a
control, not an effect. No causal claim; one run per arm.

## 4. Fixed-batch serial versus concurrent
The legacy burst harness already has `--serial` and tags rows with `mode`. What was missing is the comparison the
batching-proof spec describes: for each batch size N present in both modes, wall-time speedup (serial wall divided by
concurrent wall) and the throughput ratio. A pair is comparable only with equal request counts and no failures on either
side; otherwise ratios are null with a reason. Duplicate rows for the same N and mode are refused as ambiguous.

## 5. Engine-agnostic request path
The replay request path already speaks an OpenAI-compatible `/v1/chat/completions`, so the same workload and prompts run
against any such server. What was vLLM-specific is metrics parsing. A `--engine {vllm,sglang}` option (default vllm) selects
the metric-name prefix and is recorded in the manifest. vLLM's names were observed on v0.30.0 by the earlier harness;
SGLang's `sglang:` prefix is **unverified** and is marked so in code, artifacts and docs, and cache-hit-rate summaries
refuse for it. Cross-engine comparison still refuses (engine mismatch); relaxing that is a separate decision.

## 6. Failure-behaviour test
A separate `failure-behaviour` mode: a fixed-concurrency closed loop while the operator-supplied
commands inject and then restore a fault. It records error rates before, during and after the fault, time to first error,
time to recovery (first request dispatched after the restore that succeeds), requests that were in flight when the
fault hit (kept out of the baseline), the `/health/serving` timeline against its
documented behaviour (503 when the probe fails, 200 when the model is listed), and whether any request succeeded during
the fault. For `LLM_PROVIDER=local` the documented behaviour is that there is **no hosted fallback**; the test confirms
failures surface to the caller and does not add one. Commands are never recorded, only their hashes and exit codes. The
output directory deliberately has no `run_summary`, so the comparison and capacity tools refuse it.

## Non-goals
No change to planner, retriever, grounding or critic; no local-to-hosted fallback; no SGLang-specific request code; no
cross-engine comparison; no live measurement.
