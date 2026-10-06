# Phase 3 quantization comparison — 2026-10-01 / 2026-10-02

All three servings were measured. AWQ improved aggregate throughput over FP16
at each measured concurrency on the original pod; its advantage narrowed under
load. GPTQ was measured on a replacement host and is not a controlled same-host
speed comparison. None of these critic diagnostics establishes end-to-end answer
quality or the benefit of the critic retry loop.

## Setup and provenance

Qwen2.5-7B-Instruct, official FP16 / AWQ / GPTQ-Int4 repositories; L40S 48GB,
vLLM 0.30.0, float16 compute, max_model_len=16384, gpu_memory_utilization=0.90,
prefix caching ON, client cache busting ON, max_tokens=1400 for speed,
concurrency 1/16/64, eight real captured prompts from `data/bench_prompts.jsonl`.
Each serving passed a positive control: 49.924% cache hits with busting off,
0% with busting on. Fallback was disabled. Transport was a localhost-only SSH
tunnel. Quality used the existing 150-token critic diagnostic at temperature 0.

FP16 and AWQ ran on pod `ryy03s0132en85` in US-MO-1 on October 1. On resumption,
that pod returned 404 and the pod list was empty. AWQ artifacts already existed
although the handoff said AWQ had not started. GPTQ ran on replacement
`54caxtprn07c1r` in EUR-IS-2 on October 2. GPU, driver 580.159.03, CUDA 13.0,
PyTorch 2.13.0+cu130 and image digest matched, but host/network/data-center and
run time changed. This particularly confounds TTFT comparisons.

See `setup.json` and `resume-state.json`. The old FP16 server log is retained;
the old AWQ server log and exact FP16/AWQ model revisions were not saved and
cannot be recovered from the absent pod. AWQ's actual kernel is therefore unknown.
GPTQ revision: `e9c932ac1893a49ae0fc497ad6e1e86e2e39af20`; server selected
`auto_gptq` / `MarlinLinearKernel` for `AutoGPTQLinearMethod`, with FlashAttention 2.

The initial 8192-context attempt is preserved in `initial-8192-context/` and
excluded from every table here. `gptq-control-sandbox-blocked.log` records a local
connection failure before measurements; the authorized retry passed. Historical
Fourth-sweep BF16 measurements are not this FP16 baseline.

## Speed

| Format | Concurrency | OK/total | TTFT p50 (s) | Decode tok/s p50 | Aggregate tok/s | Peak KV occupancy |
|---|---:|---:|---:|---:|---:|---:|
| FP16 | 1 | 8/8 | 0.982 | 48.5 | 40.6 | 1.7% |
| FP16 | 16 | 16/16 | 7.280 | 17.2 | 142.5 | 21.7% |
| FP16 | 64 | 63/64 | 26.624 | 5.7 | 180.6 | 72.0% |
| AWQ | 1 | 8/8 | 0.878 | 119.9 | 83.5 | 1.1% |
| AWQ | 16 | 16/16 | 6.078 | 29.3 | 227.3 | 15.0% |
| AWQ | 64 | 64/64 | 25.735 | 6.0 | 208.3 | 55.4% |
| GPTQ | 1 | 8/8 | 0.600 | 126.2 | 93.7 | 1.2% |
| GPTQ | 16 | 16/16 | 3.905 | 31.5 | 279.6 | 15.0% |
| GPTQ | 64 | 64/64 | 16.022 | 8.0 | 290.1 | 53.4% |

FP16 c=64 includes one `RemoteProtocolError: Server disconnected without sending
a response`; it was preserved, not silently removed or rerun. Percentiles describe
successful requests. All nine cells measured 0% prefix-cache hits and zero
preemptions; AWQ and GPTQ had no speed-request errors or empty outputs. Check per-cell errors in the raw rows before interpreting
throughput. Peak KV occupancy is a fraction of each server's allocated cache,
not total GPU memory, and the cache capacity differs by format.

## Critic diagnostic, separate from speed

| Format | Edge cases correct | Edge P/R/F1 (valid verdicts) | Edge errors | Corruptions caught / all | Corruption errors |
|---|---:|---|---:|---:|---:|
| FP16 | 1/5 | 0.20/1.00/0.33 | 0 | 15/15 | 0 |
| AWQ | 3/5 | 0.33/1.00/0.50 | 0 | 15/15 | 0 |
| GPTQ | 1/5 | 0.33/1.00/0.50 | 2 | 9/15 | 6 |

GPTQ returned Markdown-fenced JSON in eight cases; the current critic's strict
JSON parser rejected those responses (2 edge cases, 6 corruptions). Raw responses
are retained. The harness reports corruption recall 1.00 over valid verdicts,
which excludes errors: the operational caught/all rate is **9/15 = 60%**.
FP16 and AWQ each caught 15/15 corruptions without parse failures. FP16 falsely
rejected all four acceptable edge answers; AWQ falsely rejected two. GPTQ falsely
rejected two and returned no valid verdict on the other two acceptable answers.
These are tiny, deliberately difficult diagnostics, not production accuracy
estimates. No parser or production model configuration was changed to improve a score.

## Memory, cost, and limitations

The retained FP16 log records 14.29 GiB for model loading and 22.94 GiB available
KV cache (429,552 tokens). GPTQ records 5.27 GiB and 32.87 GiB (615,456 tokens).
These are server-reported allocations on different hosts, not matched peak-memory
measurements. AWQ allocation evidence is missing; no AWQ memory-saving figure is claimed.

Per-cell costs in the raw rows and comparison text are measured batch wall time
multiplied by $1.09/hour, excluding startup, downloads, diagnostics and idle time.
Output lengths vary across models, so cost-per-cell changes do not describe identical
output work. These are single sweeps with no confidence intervals. See
`resume-state.json` for lifecycle/billing evidence; account charges are distinct from
per-cell modeled costs. The replacement pod was terminated by 2026-10-02
00:39:23 UTC and an empty pod list confirmed. The original pod has $0.5284245586954057
reported charges; replacement billing records had not appeared at the final check
(they do not establish zero cost). The unrelated retained network volume remains untouched.

## Reproduce the report

`comparison-input.jsonl` is the concatenation of the three corrected speed files.
`fp16-awq-comparison.txt` and `fp16-gptq-comparison.txt` were produced by
`eval/quantization_compare.py` with the explicit half-open UTC windows below:

- fp16: [2026-10-01T17:39:00+00:00, 2026-10-01T17:40:00+00:00)
- awq: [2026-10-01T17:50:00+00:00, 2026-10-01T17:51:00+00:00)
- gptq: [2026-10-02T00:34:00+00:00, 2026-10-02T01:00:00+00:00)

Run the comparison tool with `--jsonl reports/quantization-2026-10-01/comparison-input.jsonl`,
`--baseline-label fp16`, `--variant-label awq` (or `gptq`), and the respective
`--baseline-since/--baseline-until/--variant-since/--variant-until` values above.
Quality comes from the separate `*-quality.json` files. Available server logs,
control logs and sweep logs are retained beside them. Phase 4 remains deferred.
