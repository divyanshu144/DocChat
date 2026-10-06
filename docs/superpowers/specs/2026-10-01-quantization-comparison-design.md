# Phase 3 — Quantization Comparison Design Spec

**Date:** 2026-10-01
**Branch:** `chore/inference-complete-and-hardening`
**Status:** Authorized live measurements completed 2026-10-02. See
[report](../../../reports/quantization-2026-10-01/README.md) for results and departures
from this original plan: GPTQ used a replacement host; original AWQ backend/memory
log and FP16/AWQ revisions were unavailable. The proposal below is retained as provenance.
**Related:** `eval/inference_benchmark.py` (the harness this reuses as-is),
`eval/BENCHMARK_RESULTS.md` (Fourth sweep, the FP16 numbers on real prompts),
`eval/benchmark.py` (the critic quality harness this borrows for the regression check),
`eval/corruptions.py` (the generated corruption set), `eval/positive_control.py`
(required before trusting any sweep run here).

## Overview

Phases 1-4 of the original inference-benchmarking spec cover: the `local` provider
(done), the benchmark harness (done), and two measurements still open. This spec covers
the first of those two: comparing FP16 against a quantized build (AWQ, and GPTQ if a
maintained one is cheap to find) of the same model, on both speed and answer quality.
Speed alone is not the point. A quantized model that is faster but measurably worse at
answering is not a win, and the only way to know is to run DocChat's own quality gate
against it, not just read a perplexity number from somewhere else.

## Why this needs its own spec

The existing harness already measures TTFT, decode throughput, and cost. Running it
against a quantized server costs nothing extra to build. What is missing is the quality
side: nothing today runs `eval/benchmark.py` against a `local` vLLM server at all, FP16
or quantized, so there is no existing baseline to compare the quantized numbers against.
A quantization comparison that only measures speed and skips quality would answer half
the question and invite a bad trade dressed up as a win.

## Decisions

**Model and quantization format.** Qwen2.5-7B-Instruct stays the model (locked in the
original spec, for exactly this reason: it has a maintained AWQ build). AWQ is the
primary comparison, expected to be `Qwen/Qwen2.5-7B-Instruct-AWQ`, the official Qwen
release repo, confirmed to exist on Hugging Face before the pod is created, not assumed.
GPTQ is attempted only if a maintained GPTQ build of the same model (expected
`Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4`) is similarly confirmed to exist; if not, GPTQ is
skipped and the results file says why, rather than spending pod time quantizing a model
from scratch for a portfolio measurement.

**One pod, three sequential servings.** Rather than creating three pods, the plan is one
pod, FP16 served first, then the vLLM server process restarted with `--quantization awq`
pointed at the AWQ build, then (if available) GPTQ the same way. This is the same GPU
paying for three measurements instead of three GPUs each paying for one. Each serving
gets its own positive control run before its sweep, since cache-busting proof does not
carry over between server restarts.

**Harness reuse, no new sweep code.** Same `eval/inference_benchmark.py`, same
invocation shape as the Fourth sweep: `--providers local --prompts-file
data/bench_prompts.jsonl`, cache busting ON (default), 5-minute per-cell timeout and
preemption tracking already built in from that sweep. Concurrency levels: `1,16,64`
rather than the Fourth sweep's full `1,4,16,64,128` — three points is enough to show the
curve shape across three servings without tripling the already-multiplied cost of
repeating the sweep three times.

**Quality regression check is the new piece.** `python eval/benchmark.py` run against
`LLM_PROVIDER=local` for each serving (FP16, AWQ, GPTQ if present), using
`critic_rejection_log` off (this is a quality measurement, not data collection).
Reports Layer A precision/recall/F1 on the hand-written edge cases plus the generated
corruption set's recall, the same numbers the existing critic-accuracy history already
tracks. There is no existing FP16-on-`local` baseline for these numbers anywhere in this
repo (the recorded 5/5, 1.00/1.00, 15/15 history was measured against Groq's hosted
model, not Qwen2.5-7B-Instruct) — the FP16 serving's run against `eval/benchmark.py` is
therefore not a sanity check, it is the baseline this phase's entire quality comparison
rests on, and it must run as or before the corresponding harness sweep for the AWQ/GPTQ
numbers to mean anything.

**New code: `eval/quantization_compare.py`.** A small script that takes two or three
result rows (one per serving, already-written JSONL from `eval/inference_benchmark.py`
plus `eval/benchmark.py`'s own output) and produces a comparison table: for each
concurrency level, TTFT/decode-tok-s/cost delta between quantization formats, plus the
critic precision/recall/F1 delta. Pure data transformation, no network calls, so it is
fully unit-testable without a pod:

- `_load_summary_rows(jsonl_path, provider="local") -> list[dict]` — filters
  `data/inference_benchmark.jsonl` to the rows from one sweep run (matched by a
  caller-supplied timestamp range or run label, not by guessing).
- `_compare_rows(baseline: dict, variant: dict) -> dict` — percentage deltas for
  `ttft_p50`, `decode_tok_s_p50`, `aggregate_tok_s`, `cost_usd`, `None` for any field
  either side marked `insufficient_samples`, never a delta computed from missing data.
- `_fmt_comparison_table(rows: list[dict]) -> str` — the printed report.

These three functions are what get dry-run tested in this item (no live server, no
pod). The script's own `main()` that reads real JSONL files and prints the report is
exercised manually once real sweep data exists, same bar as the rest of this harness
family.

## Cost and safety

Same rules as every prior pod session: state GPU, hourly rate, expected duration, and a
total cost cap before creating anything; Terminate, never Stop; confirm `list-pods`
empty at the end. Three sequential servings on one pod, three concurrency levels each,
plus three `eval/benchmark.py` runs (20 cases each at most) is a few GPU-hours at most,
most of it idle time between servings while vLLM restarts and the positive control
reruns — the actual cost estimate will be stated for approval before any pod exists, not
assumed here.

## Verification

1. `ruff check .` clean.
2. `pytest -m "not eval" -q` green, including new tests for the three
   `eval/quantization_compare.py` functions above.
3. Stop here and ask for a go before creating any pod, stating the GPU, rate, expected
   duration, and cost cap.
4. After a live run: `eval/BENCHMARK_RESULTS.md` gets a dated entry with the same level
   of caveats as the Fourth sweep (what was measured, what was not, which numbers used
   placeholder rates if any do).

## What this spec does not cover

- **Phase 4** (serial vs. concurrent throughput curve) — separate spec, see
  `2026-10-01-batching-proof-design.md`.
- **Phase 5** (write-up) — depends on this phase's real numbers existing first.
- Quantizing a model from scratch if no maintained AWQ/GPTQ build exists. If
  Qwen2.5-7B-Instruct's AWQ build turns out to be stale or missing by the time this
  runs, that is a stop-and-ask, not a silent substitution of a different model.
