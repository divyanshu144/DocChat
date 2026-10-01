# Phase 4 — Batching Proof Design Spec

**Date:** 2026-10-01
**Branch:** `chore/inference-complete-and-hardening`
**Status:** Draft. Not implemented in its live-sweep form. Needs a go before any pod.
**Related:** `eval/inference_benchmark.py` (the harness this adds one flag to),
`eval/BENCHMARK_RESULTS.md` (Fourth sweep, which already shows concurrent throughput
climbing with load, but not against a serial baseline at the same batch size).

## Overview

Every sweep so far has shown vLLM's concurrent throughput climbing with load (70.8 to
1313.9 tok/s, c=1 to c=64, in the Fourth sweep). That is evidence continuous batching is
doing something, but it is not a direct proof: it never shows what the same N requests
would have cost without batching, at the same N, on the same server. This phase adds
that direct comparison: take a fixed batch size N, run N requests strictly one at a time
(no overlap, by construction) and then the same N requests concurrently, and show the
wall-time ratio. That ratio is the actual batching proof, not an inference from a
throughput curve that only ever showed the concurrent side.

## Decisions

**New `--serial` flag on the existing harness**, not a separate script. The request
plumbing, cost accounting, metrics polling, and output format are all already correct;
the only thing missing is a mode that awaits each request before starting the next
instead of firing them together.

**`_run_concurrency_level` gets a `serial: bool = False` parameter.** When `True` and
`concurrency > 1`, it awaits `_run_request` in a loop instead of `asyncio.gather`,
cycling through `prompts` the same way the concurrent path already does. `concurrency
== 1` is unaffected either way, since it is already sequential by construction (see the
existing special case for why: a single sample can't produce a percentile).

**`_run_provider` and the output row gain a `mode` field** (`"serial"` or
`"concurrent"`, default `"concurrent"` so old rows in `data/inference_benchmark.jsonl`
stay valid without the field). Without this, a serial run and a concurrent run at the
same concurrency level would be indistinguishable in the JSONL once both exist.

**The comparison itself is just the two wall times.** `wall_time_s` from a `concurrency
= N, mode = serial` row divided by `wall_time_s` from a `concurrency = N, mode =
concurrent` row at the same N is the batching speedup factor at that batch size. No new
analysis script needed: `eval/quantization_compare.py`'s window-based row loader from
the Phase 3 spec already does exactly this kind of two-run comparison and can be reused
here with `mode` as the discriminator instead of a timestamp window, or the two numbers
can just be read directly off the printed rows and put in the results file by hand,
whichever is less code once real numbers exist.

**Concurrency levels for the live run:** `4,16,64` — a serial run at c=128 would take
roughly 128 times a single request's latency with zero batching benefit to offset it
(the Fourth sweep's single-request latency was in the 3-5 second range, so a serial
c=128 run could run into the harness's own 5-minute per-cell timeout by design; that
timeout exists specifically so a cell like this fails safely rather than hanging). A
smaller top end avoids spending pod time hitting a timeout that would prove nothing new.

## Cost and safety

Same rules as every prior pod session: state GPU, hourly rate, expected duration, and a
total cost cap before creating anything; Terminate, never Stop; confirm `list-pods`
empty at the end. A serial run at c=64 is, by definition, roughly as slow as the
concurrent benefit it is trying to measure, so the serial half of this sweep is the more
expensive half in wall-clock time even though it does the same amount of real work.

## Verification

1. `ruff check .` clean.
2. `pytest -m "not eval" -q` green, including new tests proving `serial=True` actually
   prevents overlapping requests (not just that it calls `_run_request` the same number
   of times), and that `mode` is tagged correctly on the output row.
3. Stop here and ask for a go before creating any pod, stating the GPU, rate, expected
   duration, and cost cap.
4. After a live run: `eval/BENCHMARK_RESULTS.md` gets a dated entry with the wall-time
   ratio at each shared concurrency level and the same level of caveats as the Fourth
   sweep.

## What this spec does not cover

- **A second serving engine** (TGI/SGLang) for an engine-vs-engine table. Optional,
  separate work, not needed to prove continuous batching's own effect on a single
  engine, which is what this phase is actually about.
- **Phase 3** (quantization comparison) — separate spec,
  `2026-10-01-quantization-comparison-design.md`.
- **Phase 5** (write-up) — depends on this phase's real numbers existing first.
