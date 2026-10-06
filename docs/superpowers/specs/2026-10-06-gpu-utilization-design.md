# GPU utilization in the serving benchmark: design (2026-10-06)

## Problem

The schema-v2 sustained benchmark reports TTFT, p95 latency, tokens/sec, KV-cache pressure (from vLLM
`/metrics`) and, where known, queue wait. It does not report GPU compute utilization. vLLM's `/metrics`
does not expose it, and the benchmark client can run on a different machine from the GPU.

## Constraints

- A separate source on the GPU host: a small standalone sampler writing timestamped JSONL.
- Attach, per measured concurrency cell, the samples inside that cell's window (warmup excluded) and report mean,
  p95, max and sample count. Never fill in or estimate a value; record `unavailable` with a reason instead.
- Optional field. Old artifacts must still load; comparison mode and the capacity tool must be unchanged when it
  is absent; it must not influence which runs are comparable. Schema stays v2.
- Content-free (no prompts, answers, process lists, names or hostnames). Settings through `app.core.config`.
- Proven offline with fixtures only. No GPU is launched or rented; live acceptance is pending an approved endpoint.

## Design

1. `eval/gpu_sampler.py`: stdlib-only, no repo imports. Backends in order: `pynvml`, then `nvidia-smi` CSV query,
   otherwise an explicit "unavailable" header and a non-zero exit. JSONL: a `sampler_start` header (backend, clock
   source `gpu_host_wall_clock_utc`, interval) and one `gpu_sample` per GPU per tick (`ts`, `gpu`, `util_pct`,
   `mem_used_mib`, `mem_total_mib`, `power_w` or null). Refuses to overwrite; flushes per tick; stops on SIGINT/SIGTERM.
2. `run_cell` adds an optional `window` (`started_at`, `ended_at`, `clock`) to `cell_summary`, spanning the same
   interval as `wall_s`. The measurement cell is a separate call from warmup, so warmup is excluded by construction.
3. `eval/gpu_utilization.py attach RUN_DIR SAMPLES.jsonl`: post-run (the file is copied back after the sweep).
   Writes `RUN_DIR/gpu-utilization.json` (never modifies `events.jsonl` or `manifest.json`). Per cell and per GPU:
   `n_samples`, `mean_pct`, `p95_pct` (nearest-rank), `max_pct`. Records the clock sources and the applied
   `clock_offset_s` with its provenance. Status `ok`, `partial` or `unavailable` (missing file, sampler unavailable,
   no window recorded, too few samples, or samples not covering the window).
4. `eval/quantization_compare.py` adds a `gpu_utilization` key per cell row only when at least one run has the
   file. It is not part of any comparability check. `eval/capacity_plan.py` is unchanged.

## What the number means

GPU utilization is the share of the sample period in which at least one kernel was running, so 100 percent does not
mean the GPU is fully used. It shows the GPU was busy, not that it was efficient: a memory-bound decode loop can read
high while delivering little throughput, and a low reading does not show where a limit was.
It is one more signal beside KV-cache usage and queue depth, not a replacement. It does not measure memory
bandwidth, achieved FLOPs, or per-request GPU time.

## Non-goals

No live measurement, GPU provisioning, automatic clock synchronisation, cross-GPU averaging, estimation of missing
values, schema bump, change to capacity planning, or change to which runs are judged comparable.

## Risks

- Clock skew between the GPU host and the benchmark client: handled by an operator-supplied offset, recorded as
  `operator_supplied` or `assumed_zero_not_measured`; nothing is auto-corrected.
- Short cells yield few samples at a 1 s interval: below `--min-samples` (default 10) the cell is `unavailable`.
- Sampler stopped early or started late: the coverage rule marks the cell `unavailable` rather than report a biased mean.
- A multi-GPU host: statistics are per GPU; a GPU-count mismatch with the manifest is flagged, not corrected.
