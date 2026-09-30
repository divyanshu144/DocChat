# Self-Hosted Inference Benchmarking — Design Spec

**Date:** 2026-09-28
**Branch:** TBD — recommend a new branch off `master` (e.g. `feat/local-inference-benchmark`);
unrelated to the in-flight `feat/openai-sse-chat-quality` work.
**Status:** Draft. Not implemented.
**Related:** `app/services/llm.py` (the provider seam this extends), `eval/benchmark.py`
(the harness convention this follows), `HANDOFF.md` "Open Questions" (the precedent for
not claiming a number nobody measured).

---

## Overview

Every LLM call in this codebase today goes to a **hosted API** (Groq, OpenAI, Mistral).
That's a solid showcase of LLM *application/platform* engineering — provider abstraction,
streaming, fallback, tracing, eval-driven quality — but it demonstrates nothing about
**inference serving**: continuous batching, KV-cache management, quantization, GPU
throughput/latency tradeoffs. That's the core of what "LLM inference engineer" hiring
loops test, and it's the actual goal of this work — using DocChat as a portfolio piece for
that specific role family.

This spec covers adding a **`local` provider** — a self-hosted model served by vLLM on a
rented GPU, wired into the existing provider seam — and a **benchmark harness** that
measures it against the hosted providers on latency, throughput, and cost. Quantization
comparison, the batching-proof charts, and the write-up are later phases with their own
specs; this one only has to produce trustworthy numbers to build on.

## Why now

`app/services/llm.py`'s own docstring states the extension contract: "Adding a provider
means: a branch in `_build_client`, a `_*_complete`, a `_*_stream`, and an entry in each
dispatch. Nothing outside this module changes." That was true before this spec and is the
reason this is cheap: no architectural change, just filling in a seam that was already cut
for exactly this.

## Decisions

**Model.** One open-weight instruct model, 7–8B, with a maintained AWQ (or GPTQ) build —
needed for the quantization-comparison phase later, so the model choice has to be made
once, here, not revisited per phase. Default: **Qwen2.5-7B-Instruct** (Apache-2.0, no
gating, strong AWQ/GPTQ community support). Llama-3.1-8B-Instruct is the fallback if
license gating on HF isn't a problem — noted here so a later phase doesn't silently
re-litigate the choice.

**Serving engine.** vLLM in OpenAI-compatible server mode (`vllm serve <model>`), exposing
`/v1/chat/completions` in the same JSON shape OpenAI uses. That means `_local_complete` /
`_local_stream` can mirror `_openai_complete` / `_openai_stream` almost line-for-line and
reuse `_text()`, `_temperature_kwargs()`, `_mentions_temperature()` as-is — the smallest
possible diff for the largest possible inference-engineering surface (vLLM is what brings
continuous batching and PagedAttention KV-cache management, which is the point).

**New settings** (`app/core/config.py`, following the existing per-provider pattern):

```python
local_base_url: str = ""       # e.g. http://<gpu-host>:8000/v1 — blank disables the provider
local_chat_model: str = ""     # model name/path registered with vLLM
local_api_key: str = ""        # optional bearer token if vLLM is started with --api-key
```

`llm_provider: Literal["groq", "mistral", "openai"]` gains `"local"`.

**Client construction.** `_build_client("local")` returns an `httpx.AsyncClient` pointed at
`settings.local_base_url`, mirroring the existing `_build_client("openai")` branch exactly
(bearer header if `local_api_key` is set, 60s timeout).

**Fallback chain — deliberately excluded.** `local` is **not** added to
`_can_fallback_to_openai` / the Groq→OpenAI retry chain. It's a benchmarking target, not a
reliability path: the GPU box is rented on demand and may not even be running when the app
starts. Reachable only via explicit `LLM_PROVIDER=local`.

**Testing.** Same bar as the Mistral provider — "verified structurally, not live." Mocked
httpx tests assert the request URL and payload shape match vLLM's OpenAI-compatible schema
(model, messages, max_tokens, stream). No live GPU call runs in CI or in
`pytest -m "not eval"`. A manual smoke check against a real running box is a documented
command, not a test.

## Benchmark harness (`eval/inference_benchmark.py`)

- **Workload:** reuses the existing query set from `eval/cases.py` rather than inventing a
  second corpus — keeps numbers comparable to the quality-eval work already in the repo
  and avoids maintaining two datasets.
- **Metrics per request:** TTFT (time to first streamed token), total latency, output
  tokens/sec.
- **Concurrency sweep:** 1, 4, 16, 64 concurrent requests via `asyncio.gather`, p50/p95/p99
  captured per level. A single-request latency number says nothing about batching; the
  sweep is what actually demonstrates understanding of the thing being tested.
- **Cost:** looked up from a small static `$/1M tokens` table for the hosted providers;
  for `local`, cost is the rented GPU's `$/hr` divided into throughput at that concurrency
  level — made explicit rather than treated as free, since "free" would be a wrong number,
  not a missing one.
- **Output:** raw JSONL per run (kept for the quantization phase to diff against) plus a
  stdout summary table, following `eval/benchmark.py`'s existing convention of "always
  exits 0, prints a report."
- **Explicitly out of scope for this script:** answer quality. Scoring correctness is the
  critic eval harness's job (reused as-is in the quantization phase); this script's only
  job is performance, and conflating the two would make a regression in either one harder
  to isolate.

## Cost and safety

Rented GPU time is billed per hour and is not something to automate. Any run against
`LLM_PROVIDER=local` is a manual, deliberate sequence — start the GPU, run the harness,
stop the GPU — never wired into CI, a cron job, or anything unattended.

## Verification

1. `ruff check .` clean.
2. `pytest -m "not eval" -q` green, including the new mocked `local` provider tests —
   count goes from 153 to 153+N.
3. Manual, with a real vLLM box running: `python eval/inference_benchmark.py
   --providers local,groq,openai` and sanity-check the numbers land in a plausible range
   for a 7–8B model on a single rentable GPU (L4/A10G) — sub-second TTFT, tens-to-low-
   hundreds output tokens/sec at low concurrency, visible throughput gain from batching
   as concurrency rises.
4. `HANDOFF.md` updated with whatever the harness actually measured — not a projected
   number. If a number in a later resume bullet can't be traced back to a harness run
   recorded here, don't write the bullet.

## What this spec does not cover

- **Quantization comparison** (FP16 vs AWQ/GPTQ on the same model, checked against the
  existing critic eval harness for quality regression) — Phase 3, separate spec, depends
  on this one existing first.
- **Continuous-batching-proof charts** and any second serving engine (TGI/SGLang) for an
  engine-vs-engine table — Phase 4, separate spec.
- **The write-up / resume bullet** — Phase 5, written only after Phases 1–4 produce real
  numbers, in the same spirit as the still-open gap in `HANDOFF.md`'s "Open Questions."
