# Harness improvements: implementation plan (2026-10-06, Phase 1)

Spec: `docs/superpowers/specs/2026-10-06-harness-improvements-design.md`. TDD: write the failing tests, make them pass,
keep `ruff check .` clean and `pytest -m "not eval" -q` green after each task. No commits, no spend.

1. p99 in `serving_load.summarize` and `capacity_plan`  (tests: threshold, null below it, capacity worst-repeat, old runs)
2. Cost per request and per 1K tokens in `capacity_plan`  (tests: values, skipped on null cost, no change to existing fields)
3. `serving_metrics`: engine prefixes (vllm/sglang, sglang unverified) and `prefix_cache_summary`; `--engine`  (tests: both
   prefixes, default unchanged, reset and missing series, sglang refuses)
4. Per-cell `prefix_cache` event field and `compare_prefix_caching`  (tests: hit-rate math, refusals, bust control note,
   unchanged on old runs)
5. `compare_batching` for legacy rows  (tests: ratios, refusals, duplicates, mode default for old rows)
6. `eval/failure_behaviour.py` plus the `failure-behaviour` subcommand  (tests: analysis windows, time to first error,
   recovery definition, health documented-behaviour, no-hosted-fallback record, command hashing, no `run_summary`)
7. Docs: one section per addition in `docs/benchmarking.md`; `docs/serving-observability.md` where metrics change
8. HANDOFF, lessons, final gates, diff summary; STOP for approval before Phase 2
