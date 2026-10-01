#!/usr/bin/env python3
"""Phase 2 — inference performance benchmark.

Measures TTFT, decode throughput, and cost across a concurrency sweep for
whichever providers are named on the command line, using the same
`chat_stream` seam the app itself calls (`app/services/llm.py`). Defaults to
the bare query set from `eval/cases.py` (no context, 20-90 tokens); pass
`--prompts-file data/bench_prompts.jsonl` (eval/capture_bench_prompts.py's
output) to size the sweep to DocChat's real request shape instead — real
retrieval context pushes prompts to 3752-6801 input tokens, ~40-100x larger.
The first two sweeps (2026-09-30) used the bare queries and measured a
workload the app never actually sends; see eval/BENCHMARK_RESULTS.md.

This script measures PERFORMANCE only, never answer quality — that's the
critic eval harness's job (`eval/benchmark.py`), kept deliberately separate
per the design spec so a regression in either is easy to isolate.

Usage:
    python eval/inference_benchmark.py --providers groq,openai,local \\
        --gpu-cost-per-hr 0.50 --openai-model gpt-4.1

Requires the relevant provider's API key / LOCAL_* settings to already be
configured in .env. A run against `local` is a manual, deliberate, billed
action against a rented GPU — never wire this into CI or a schedule.

Fallback is unconditionally disabled for every run of this script (see
`_run_provider`) — a benchmark whose provider identity can silently change
mid-run (e.g. Groq falling back to OpenAI on a rate limit) is not measuring
what it claims to measure. A failed request is recorded as an error, never
silently retried against a different provider.

`--openai-model` matters: the configured production default
(`settings.openai_chat_model`) may be a reasoning model. A reasoning model can
spend its entire `--max-tokens` budget on hidden reasoning tokens and return
zero visible content — measured directly on 2026-09-30, see
`eval/BENCHMARK_RESULTS.md`. Pass a non-reasoning model here for a real
throughput measurement; this only overrides the setting for the duration of
this script's own run, production is untouched.

`--groq-model` is the same fix for Groq. The configured production default
(`settings.chat_model`, `openai/gpt-oss-120b`) is also a reasoning model --
diagnosed but not fixed during the second live sweep (2026-09-30, see
`eval/BENCHMARK_RESULTS.md` and tasks/lessons.md). Pass a non-reasoning Groq
model here to separate "wrong model" from "real rate limit" the same way
`--openai-model` does; production is untouched either way.

Always exits 0 once measurement starts — it measures, it does not assert.
(A missing required flag like `--gpu-cost-per-hr` for `local` is a usage
error and is reported before anything runs, not a measurement outcome.)
Raw per-request measurements are appended to a JSONL file so a later run
(e.g. the quantization-comparison phase) can diff against this one.

CACHE BUSTING (default ON, see --allow-prefix-cache): every request gets a
unique `request_id: <uuid4>` line prepended to its first message, so no two
requests in a sweep share an identical prefix. Without this, identical
prompts cycled across concurrency levels (the previous behavior) can be
served from a KV-cache/prefix-cache hit instead of fresh compute -- see
eval/BENCHMARK_RESULTS.md's 2026-09-30 "Third sweep" entry, where this was
flagged as the likely explanation for a physically-implausible TTFT.

VLLM METRICS (local only): scraped from `/metrics` every ~1s while a cell
runs. The candidate names in _VLLM_METRIC_CANDIDATES were VERIFIED against a
live vLLM v0.30.0 `/metrics` endpoint on 2026-09-30 (see the fourth sweep,
`docchat-vllm-cachebust-sweep4`). One candidate was wrong and fixed as a
result: this version exposes KV cache usage as `vllm:kv_cache_usage_perc`,
not the older `vllm:gpu_cache_usage_perc` (kept as a fallback candidate).
`prefix_cache_queries_total`, `prefix_cache_hits_total`,
`num_preemptions_total`, `num_requests_waiting`, `num_requests_running` all
matched their first-guess candidate name as-is. If a metric name is wrong on
some other vLLM version, `_scrape_vllm_metrics` degrades to None for that
field rather than crashing.

SERIAL MODE (--serial, Phase 4 batching proof, default off): runs each
concurrency level's requests one at a time instead of together, so the
resulting wall time is a true no-batching baseline at that batch size,
directly comparable to a normal (concurrent) run at the same concurrency.
Each output row is tagged with `mode` ("serial" or "concurrent") so the two
can be told apart once both exist in the same JSONL file. See
docs/superpowers/specs/2026-10-01-batching-proof-design.md.
"""

import argparse
import asyncio
import json
import math
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Invoked as a script (`python eval/inference_benchmark.py`), sys.path[0] is
# eval/, not the repo root — so `app` and `eval` are unimportable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.services import llm  # noqa: E402
from eval.cases import CASES  # noqa: E402

_RULE = "─" * 78

# $ per 1M output tokens for the hosted providers this repo talks to.
#
# PLACEHOLDER RATES — not fetched live, and not verified against each
# provider's current pricing page as of this writing (Groq's pricing page
# doesn't list per-model rates; OpenAI's blocked an automated fetch). Treat
# these as illustrative order-of-magnitude figures only. Verify against the
# provider's live pricing page before quoting a cost number anywhere outside
# this script — the same "measured, not guessed" bar the rest of this repo
# holds itself to.
_HOSTED_COST_PER_1M_OUTPUT_TOKENS: dict[str, float] = {
    "groq": 0.20,     # openai/gpt-oss-120b class
    "openai": 10.00,  # gpt-5-class flagship
    "mistral": 0.60,  # mistral-small-latest class
}

_DEFAULT_CONCURRENCY_LEVELS = [1, 4, 16, 64]
_DEFAULT_MAX_TOKENS = 256

# Candidate Prometheus metric names, tried in order, for each field vLLM's
# /metrics exposes. VERIFIED against a live vLLM v0.30.0 server on
# 2026-09-30 (see the Fourth sweep in eval/BENCHMARK_RESULTS.md and the
# module docstring above). A different vLLM version may use different
# names -- these are not guaranteed to hold outside v0.30.0, check a real
# /metrics response before trusting a sweep against another version. First
# match wins; None if none of a field's candidates appear.
_VLLM_METRIC_CANDIDATES: dict[str, list[str]] = {
    # Matched "vllm:prefix_cache_queries_total" as-is on v0.30.0.
    "prefix_cache_queries": [
        "vllm:prefix_cache_queries_total",
        "vllm:gpu_prefix_cache_queries_total",
        "vllm:gpu_prefix_cache_queries",
    ],
    # Matched "vllm:prefix_cache_hits_total" as-is on v0.30.0.
    "prefix_cache_hits": [
        "vllm:prefix_cache_hits_total",
        "vllm:gpu_prefix_cache_hits_total",
        "vllm:gpu_prefix_cache_hits",
    ],
    # v0.30.0 exposes this as vllm:kv_cache_usage_perc (renamed from
    # vllm:gpu_cache_usage_perc in older vLLM) -- confirmed against a live
    # v0.30.0 /metrics endpoint 2026-09-30. Old name kept as a fallback for
    # other versions.
    "gpu_cache_usage_perc": ["vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"],
    # Matched as-is on v0.30.0.
    "num_requests_waiting": ["vllm:num_requests_waiting"],
    # Matched as-is on v0.30.0.
    "num_requests_running": ["vllm:num_requests_running"],
    # Matched "vllm:num_preemptions_total" as-is on v0.30.0.
    "num_preemptions": [
        "vllm:num_preemptions_total",
        "vllm:num_preemptions",
        "vllm:preemption_total",
    ],
}

# Cells with fewer successful requests than this don't get percentiles --
# see _summarize's insufficient_samples handling.
_MIN_SAMPLES_FOR_PERCENTILES = 4

# Above this prefix-cache hit rate, with busting supposedly ON, something is
# wrong -- either busting isn't reaching the server or the metric names are
# misread. See the warning in _run_provider.
_PREFIX_CACHE_HIT_RATE_WARN_THRESHOLD = 0.10

# A single concurrency-level cell taking longer than this aborts the sweep
# (see _CellTimeoutError / _run_provider) rather than blocking indefinitely.
_CELL_TIMEOUT_S = 300


class _CellTimeoutError(Exception):
    """Raised by _run_provider when one concurrency-level cell exceeds
    _CELL_TIMEOUT_S. Carries `rows`: the already-summarized rows for every
    earlier cell in this sweep, safe to save even though the sweep as a
    whole is being aborted -- the caller should write `rows`, then stop
    (terminate infrastructure, report) rather than continue the loop.
    """

    def __init__(self, concurrency: int, rows: list[dict]):
        super().__init__(
            f"cell concurrency={concurrency} exceeded {_CELL_TIMEOUT_S}s, aborting sweep"
        )
        self.concurrency = concurrency
        self.rows = rows


# ---------------------------------------------------------------------------
# Pure logic — unit tested in tests/test_inference_benchmark_metrics.py
# ---------------------------------------------------------------------------


def _bust_prompt(messages: list[dict]) -> list[dict]:
    """Return a NEW messages list with a unique `request_id: <uuid4>` line
    prepended to the first message's content -- system message when one
    exists (the --prompts-file case), otherwise the lone user message (the
    default eval/cases.py case). Does not mutate the input list, since the
    same `prompts` list is reused across every concurrency level and cycled
    within each one (see _run_concurrency_level) -- two calls must produce
    two different unique lines even for "the same" prompt.
    """
    busted = [dict(m) for m in messages]
    unique_line = f"request_id: {uuid.uuid4()}\n"
    busted[0] = {**busted[0], "content": unique_line + busted[0]["content"]}
    return busted


def _parse_prometheus_metrics(text: str) -> dict[str, float]:
    """Parse a Prometheus text-exposition body into {metric_name: value},
    taking the first sample per metric name. Fine for vLLM's single-value
    gauges/counters; a metric exposed with multiple label combinations would
    need more care, not needed for the fields this scraper reads.
    """
    values: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        name_with_labels, raw_value = parts
        name = name_with_labels.split("{", 1)[0]
        if name in values:
            continue
        try:
            values[name] = float(raw_value)
        except ValueError:
            continue
    return values


def _resolve_metric(values: dict[str, float], candidates: list[str]) -> float | None:
    for name in candidates:
        if name in values:
            return values[name]
    return None


def _summarize_vllm_metrics(samples: list[dict[str, float | None]]) -> dict:
    """Reduce a cell's raw /metrics samples (one dict per ~1s poll, each
    shaped like _VLLM_METRIC_CANDIDATES's keys) to what the summary row
    reports: prefix-cache hit rate as a DELTA over the cell (counters are
    monotonic, so first-sample vs last-sample, not an average of ratios),
    and peak (max) KV usage / waiting / running, since those are gauges that
    can spike mid-cell and a single start/end read would miss that.
    `num_preemptions` is also a monotonic counter (total preemptions since
    server start), so it's reported as `preemptions_during_cell`, a DELTA
    (last-first) over the cell -- not a "peak", since a counter has no peak,
    only a running total. This is the count of requests that got preempted
    (evicted and re-queued, usually for KV space) during this cell specifically.

    All fields None if nothing was collected (no samples, or a field never
    appeared in any sample) -- never a fabricated 0.0, which would read as a
    measured "no caching happened" rather than "we don't know."
    """
    empty = {
        "prefix_cache_hit_rate": None,
        "peak_gpu_cache_usage_pct": None,
        "peak_num_requests_waiting": None,
        "peak_num_requests_running": None,
        "preemptions_during_cell": None,
    }
    if not samples:
        return empty

    def _delta(field: str) -> float | None:
        vals = [s[field] for s in samples if s[field] is not None]
        if len(vals) < 2:
            return None
        return vals[-1] - vals[0]

    queries = [s["prefix_cache_queries"] for s in samples if s["prefix_cache_queries"] is not None]
    hits = [s["prefix_cache_hits"] for s in samples if s["prefix_cache_hits"] is not None]
    hit_rate = None
    if len(queries) >= 2 and len(hits) >= 2:
        query_delta = queries[-1] - queries[0]
        hit_delta = hits[-1] - hits[0]
        if query_delta > 0:
            hit_rate = hit_delta / query_delta

    kv = [s["gpu_cache_usage_perc"] for s in samples if s["gpu_cache_usage_perc"] is not None]
    waiting = [s["num_requests_waiting"] for s in samples if s["num_requests_waiting"] is not None]
    running = [s["num_requests_running"] for s in samples if s["num_requests_running"] is not None]

    return {
        "prefix_cache_hit_rate": hit_rate,
        "peak_gpu_cache_usage_pct": max(kv) if kv else None,
        "peak_num_requests_waiting": max(waiting) if waiting else None,
        "peak_num_requests_running": max(running) if running else None,
        "preemptions_during_cell": _delta("num_preemptions"),
    }


def _percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile. `p` in [0, 100]. Raises on an empty list —
    there is no sane percentile of nothing, and a silent 0.0 would read as a
    real (impossibly fast) measurement."""
    if not values:
        raise ValueError("no values")
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1))
    return s[k]


def _summarize(results: list[dict], wall_time_s: float) -> dict:
    """Aggregate one concurrency level's raw per-request results.

    Percentiles and throughput are computed on `status == "ok"` requests
    only — an errored or empty (zero-content) request has no real latency or
    token rate to contribute, and folding it in would understate how bad
    the failure/empty rate actually was while also corrupting the timing
    numbers. `error_rate` / `empty_rate` carry that signal instead, and are
    the first thing to check before trusting any percentile below them.

    `wall_time_s` must be the actually-measured elapsed time of the whole
    batch (`time.monotonic()` before/after), not derived from individual
    request timings: for concurrent requests that's close to `max(total_s)`,
    but concurrency=1 now runs every query *sequentially* (see
    `_run_concurrency_level`), where real wall time is closer to
    `sum(total_s)` — inferring it from `max()` would understate a sequential
    batch's real duration and overstate its throughput.

    Percentile/rate keys are omitted (not defaulted to 0.0 or None) when
    there is no data to compute them from — e.g. `ttft_p50` is absent if
    zero requests succeeded. Check with `"ttft_p50" in summary`, not falsy-ness.

    `insufficient_samples` is `True` whenever `n_ok < _MIN_SAMPLES_FOR_PERCENTILES`
    (4) — below that, `ttft_p*`/`latency_p*`/`decode_tok_s_p50`/`aggregate_tok_s`
    are explicitly `None` (not omitted, not computed from the handful of
    samples available) rather than reporting a percentile of 1-3 points that
    would look like a real measurement but isn't one.
    """
    n_total = len(results)
    ok = [r for r in results if r["status"] == "ok"]
    n_ok = len(ok)
    n_error = sum(1 for r in results if r["status"] == "error")
    n_empty = sum(1 for r in results if r["status"] == "empty")
    insufficient_samples = n_ok < _MIN_SAMPLES_FOR_PERCENTILES

    total_output_tokens = sum(r["output_tokens"] or 0 for r in ok)
    aggregate_tok_s = (
        None
        if insufficient_samples
        else (total_output_tokens / wall_time_s if wall_time_s > 0 else 0.0)
    )

    # Legacy per-request-average metric, kept only for backward compatibility
    # with rows written before this schema existed. NOT the same thing as
    # aggregate_tok_s (throughput under load) or decode_tok_s_p50 (decode-only
    # rate) — averaging a per-request ratio is a different, weaker statistic
    # than either, which is why this repo introduced the other two.
    legacy_rates = [r["output_tokens"] / r["total_s"] for r in ok if r["total_s"] > 0]

    summary: dict = {
        "n_total": n_total,
        "n_ok": n_ok,
        "error_rate": (n_error / n_total) if n_total else 0.0,
        "empty_rate": (n_empty / n_total) if n_total else 0.0,
        "wall_time_s": wall_time_s,
        "total_output_tokens": total_output_tokens,
        "aggregate_tok_s": aggregate_tok_s,
        "insufficient_samples": insufficient_samples,
        "legacy_avg_tokens_per_sec": (
            sum(legacy_rates) / len(legacy_rates) if legacy_rates else 0.0
        ),
    }

    if insufficient_samples:
        return summary

    ttfts = [r["ttft_s"] for r in ok if r["ttft_s"] is not None]
    if ttfts:
        summary["ttft_p50"] = _percentile(ttfts, 50)
        summary["ttft_p95"] = _percentile(ttfts, 95)
        summary["ttft_p99"] = _percentile(ttfts, 99)

    totals = [r["total_s"] for r in ok]
    if totals:
        summary["latency_p50"] = _percentile(totals, 50)
        summary["latency_p95"] = _percentile(totals, 95)
        summary["latency_p99"] = _percentile(totals, 99)

    # Decode-only rate: output tokens over the post-TTFT window, i.e. pure
    # generation speed with the "waiting for the first token" cost stripped
    # out. Excludes requests where that window is non-positive (a single-chunk
    # response can have total_s == ttft_s) rather than dividing by ~zero.
    decode_rates = [
        r["output_tokens"] / (r["total_s"] - r["ttft_s"])
        for r in ok
        if r["ttft_s"] is not None
        and r["output_tokens"]
        and (r["total_s"] - r["ttft_s"]) > 0
    ]
    if decode_rates:
        summary["decode_tok_s_p50"] = _percentile(decode_rates, 50)

    return summary


def _cost_for_run(
    provider: str,
    total_output_tokens: int,
    wall_time_s: float,
    local_gpu_cost_per_hr: float | None = None,
) -> float:
    """Dollar cost of one concurrency level's run.

    Hosted providers: tokens x $/1M — cost scales with what was generated.
    `local`: the rented GPU's hourly rate x wall-clock time — the box bills
    for time whether or not it was generating, which is why cost is measured
    at each concurrency level rather than once.
    Returns NaN for an unrecognised provider, or for `local` with no
    `local_gpu_cost_per_hr` given, rather than silently reporting 0.
    """
    if provider == "local":
        if local_gpu_cost_per_hr is None:
            return float("nan")
        return wall_time_s / 3600 * local_gpu_cost_per_hr
    rate = _HOSTED_COST_PER_1M_OUTPUT_TOKENS.get(provider)
    if rate is None:
        return float("nan")
    return total_output_tokens / 1_000_000 * rate


def _local_cost_per_1m_output_tokens(
    aggregate_tok_s: float | None, local_gpu_cost_per_hr: float
) -> float | None:
    """Normalized $/1M output tokens for `local`, derived from measured
    throughput under load — the number that's actually comparable to a
    hosted provider's per-token price. `None` (not 0.0 or inf) when nothing
    was generated (aggregate_tok_s <= 0) or the cell had too few samples to
    report a throughput at all (aggregate_tok_s is None, see
    _summarize's insufficient_samples): an empty or underpowered cell has no
    real rate to report, and either sentinel value would misrepresent it as
    free or as infinitely expensive.
    """
    if aggregate_tok_s is None or aggregate_tok_s <= 0:
        return None
    return local_gpu_cost_per_hr / (aggregate_tok_s * 3600 / 1_000_000)


def _local_cost_per_request(
    wall_time_s: float, local_gpu_cost_per_hr: float, n_ok: int
) -> float | None:
    """$/request for `local`: the rented GPU's hourly rate, converted to a
    per-second rate, times the cell's wall-clock duration, divided across the
    requests that actually succeeded. `None` (not 0 or inf) when n_ok is 0 --
    there were no successful requests to divide the cost across, and either
    sentinel would misrepresent a cell that produced nothing.
    """
    if n_ok <= 0:
        return None
    return local_gpu_cost_per_hr / 3600 * wall_time_s / n_ok


def _fmt_row(
    concurrency: int, summary: dict, cost: float, local_cost_per_1m: float | None
) -> str:
    ttft = f"{summary['ttft_p50'] * 1000:.0f}ms" if "ttft_p50" in summary else "n/a"
    lat = f"{summary['latency_p50']:.2f}s" if "latency_p50" in summary else "n/a"
    decode = f"{summary['decode_tok_s_p50']:.1f}" if "decode_tok_s_p50" in summary else "n/a"
    agg = summary["aggregate_tok_s"]
    agg_str = f"{agg:>6.1f}" if agg is not None else "   n/a"
    line = (
        f"  {concurrency:>4}  n={summary['n_ok']}/{summary['n_total']}  "
        f"err={summary['error_rate'] * 100:>3.0f}% empty={summary['empty_rate'] * 100:>3.0f}%  "
        f"ttft {ttft:>7}  lat {lat:>7}  decode_tok/s {decode:>6}  "
        f"agg_tok/s {agg_str}  cost ${cost:.4f}"
    )
    if summary.get("insufficient_samples"):
        line += "  [insufficient_samples]"
    if local_cost_per_1m is not None:
        line += f"  (${local_cost_per_1m:.4f}/1M tok)"
    return line


# ---------------------------------------------------------------------------
# Live — talks to a real provider via app.services.llm. Not unit tested;
# exercised manually against real endpoints (same bar as eval/benchmark.py).
# ---------------------------------------------------------------------------


async def _run_request(messages: list[dict], max_tokens: int, bust_cache: bool = True) -> dict:
    """One streamed request. `messages` is sent as-is — a bare single-user-turn
    query (the default, from eval/cases.py) or a full captured real prompt
    (system + user, from --prompts-file) look identical from here on.

    `bust_cache` (default True): prepend a unique `request_id: <uuid4>` line
    (see `_bust_prompt`) before sending, so this request shares no prefix with
    any other in the sweep. Pass False (--allow-prefix-cache) only when a
    cache hit is genuinely what's being measured.

    `status`:
      - "ok"    — content arrived and the stream completed without raising.
      - "empty" — the stream completed without raising but yielded zero
                  content chunks (e.g. a reasoning model spending its whole
                  token budget on hidden reasoning — see module docstring).
      - "error" — the stream raised. `error_type` carries the exception
                  class and a truncated message. Never silently retried
                  against a different provider (fallback is disabled by
                  `_run_provider` for the whole benchmark run).

    `output_tokens` / `input_tokens` come from the provider's own reported
    usage (via `usage_sink`) when available — real counts, not a chunk-count
    proxy. `ttft_s` is `None` for anything that isn't "ok": inventing a TTFT
    for a request that produced no content would be a guess, not a
    measurement.
    """
    sent_messages = _bust_prompt(messages) if bust_cache else messages
    usage_sink: dict = {}
    start = time.monotonic()
    ttft: float | None = None
    chunk_count = 0
    status = "ok"
    error_type: str | None = None

    try:
        async for _token in llm.chat_stream(
            sent_messages, max_tokens=max_tokens, usage_sink=usage_sink
        ):
            if ttft is None:
                ttft = time.monotonic() - start
            chunk_count += 1
    except Exception as exc:
        status = "error"
        error_type = f"{type(exc).__name__}: {str(exc)[:200]}"

    total = time.monotonic() - start

    if status == "ok" and chunk_count == 0:
        status = "empty"

    output_tokens = usage_sink.get("completion_tokens")
    if output_tokens is None:
        # Provider didn't return usage (e.g. an error before any chunk, or a
        # provider whose usage_sink support is unverified) — chunk count is
        # the fallback proxy, same approximation the original harness used.
        output_tokens = chunk_count

    return {
        "status": status,
        "error_type": error_type,
        "finish_reason": usage_sink.get("finish_reason"),
        "input_tokens": usage_sink.get("prompt_tokens"),
        "output_tokens": output_tokens,
        "ttft_s": ttft if status == "ok" else None,
        "total_s": total,
    }


async def _run_concurrency_level(
    prompts: list[list[dict]],
    concurrency: int,
    max_tokens: int,
    bust_cache: bool = True,
    serial: bool = False,
) -> list[dict]:
    """Fire `concurrency` requests at once, cycling through `prompts` if
    concurrency exceeds the prompt count.

    concurrency == 1 is special-cased to run every prompt in the set
    sequentially rather than firing just one request — a single sample can't
    produce a percentile, and a "concurrency=1" row with n=1 was exactly the
    degenerate case flagged in the first sweep (2026-09-30).

    `serial` (Phase 4, batching proof): when True and concurrency > 1, awaits
    each request in a loop instead of `asyncio.gather`, so no two requests
    ever overlap -- a true no-batching baseline at the same batch size N,
    directly comparable to the concurrent (default) mode's wall time at that
    same N. concurrency == 1 is unaffected, since it is already sequential.
    """
    if concurrency == 1:
        return [await _run_request(m, max_tokens, bust_cache) for m in prompts]
    if serial:
        return [
            await _run_request(prompts[i % len(prompts)], max_tokens, bust_cache)
            for i in range(concurrency)
        ]
    tasks = [
        _run_request(prompts[i % len(prompts)], max_tokens, bust_cache)
        for i in range(concurrency)
    ]
    return await asyncio.gather(*tasks)


async def _scrape_vllm_metrics(metrics_url: str) -> dict[str, float | None]:
    """One /metrics scrape. Returns None for every field on any failure
    (unreachable, non-200, malformed body) or for any field whose metric name
    wasn't found under the candidates in _VLLM_METRIC_CANDIDATES — those were
    verified against vLLM v0.30.0 (see the comment on that constant), not
    guaranteed to match a different version. A failed scrape must never abort
    the benchmark request it's running alongside.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(metrics_url)
            resp.raise_for_status()
            values = _parse_prometheus_metrics(resp.text)
    except Exception:
        return dict.fromkeys(_VLLM_METRIC_CANDIDATES)
    return {
        key: _resolve_metric(values, candidates)
        for key, candidates in _VLLM_METRIC_CANDIDATES.items()
    }


async def _poll_metrics_during(metrics_url: str, coro):
    """Run `coro` to completion while polling `metrics_url` every ~1s in the
    background. Returns (coro's result, list of samples collected). The
    poller is best-effort: if every scrape fails (see _scrape_vllm_metrics),
    `samples` is a list of all-None dicts, not an empty list -- callers that
    want to tell "never scraped" apart from "scraped but empty" can check
    whether any sample has a non-None value.
    """
    samples: list[dict[str, float | None]] = []
    stop = asyncio.Event()

    async def poller():
        while not stop.is_set():
            samples.append(await _scrape_vllm_metrics(metrics_url))
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    poll_task = asyncio.create_task(poller())
    try:
        result = await coro
    finally:
        stop.set()
        await poll_task
    return result, samples


async def _run_provider(
    provider: str,
    prompts: list[list[dict]],
    concurrency_levels: list[int],
    max_tokens: int,
    local_gpu_cost_per_hr: float | None,
    openai_model_override: str | None,
    bust_cache: bool = True,
    groq_model_override: str | None = None,
    serial: bool = False,
) -> list[dict]:
    """Sweep one provider across every concurrency level.

    Sets `settings.llm_provider` for the duration and resets the cached
    client so `llm._get_client()` rebuilds against the right backend — the
    same reset pattern the provider-seam tests use. Also forces
    `settings.fallback_llm_provider = "none"` for the duration: see the
    module docstring for why a benchmark must never let a request be
    silently served by a different provider than the one under test.

    `groq_model_override` mirrors `openai_model_override`: only affects
    `settings.chat_model` (the setting Groq actually reads, see
    `llm._active_model`) for the duration of this function, restored in the
    `finally` block below regardless of outcome.

    `serial` (Phase 4, batching proof): threaded into `_run_concurrency_level`
    unchanged, and tagged on each output row as `mode` ("serial" or
    "concurrent") so a serial run and a concurrent run at the same
    concurrency level can be told apart once both exist in the same JSONL
    file.

    For `provider == "local"`, each cell's requests run alongside a ~1s
    poll of vLLM's `/metrics` (see `_poll_metrics_during`) — the resulting
    prefix-cache hit rate / peak KV usage / peak queue depth land in
    `summary["vllm_metrics"]`. If `bust_cache` is True and the measured hit
    rate exceeds `_PREFIX_CACHE_HIT_RATE_WARN_THRESHOLD`, a loud warning is
    printed: busting is supposed to make hits near-zero, so a high rate means
    either busting isn't reaching the server or the metric names are wrong.
    """
    original_provider = settings.llm_provider
    original_fallback = settings.fallback_llm_provider
    original_openai_model = settings.openai_chat_model
    original_chat_model = settings.chat_model

    settings.llm_provider = provider
    settings.fallback_llm_provider = "none"
    if provider == "openai" and openai_model_override:
        settings.openai_chat_model = openai_model_override
    if provider == "groq" and groq_model_override:
        settings.chat_model = groq_model_override
    llm._client = None
    llm._client_provider = None

    rows = []
    try:
        for concurrency in concurrency_levels:
            batch_start = time.monotonic()
            try:
                if provider == "local" and settings.local_base_url:
                    metrics_url = settings.local_base_url.removesuffix("/v1") + "/metrics"
                    raw_results, metric_samples = await asyncio.wait_for(
                        _poll_metrics_during(
                            metrics_url,
                            _run_concurrency_level(
                                prompts, concurrency, max_tokens, bust_cache, serial
                            ),
                        ),
                        timeout=_CELL_TIMEOUT_S,
                    )
                    vllm_metrics = _summarize_vllm_metrics(metric_samples)
                else:
                    raw_results = await asyncio.wait_for(
                        _run_concurrency_level(
                            prompts, concurrency, max_tokens, bust_cache, serial
                        ),
                        timeout=_CELL_TIMEOUT_S,
                    )
                    vllm_metrics = None
            except asyncio.TimeoutError:
                print(
                    f"  !!! CELL TIMEOUT: concurrency={concurrency} exceeded "
                    f"{_CELL_TIMEOUT_S}s -- aborting sweep, {len(rows)} finished "
                    "cell(s) will be saved.",
                    file=sys.stderr,
                )
                raise _CellTimeoutError(concurrency, rows) from None
            wall_time_s = time.monotonic() - batch_start
            summary = _summarize(raw_results, wall_time_s)
            if vllm_metrics is not None:
                summary["vllm_metrics"] = vllm_metrics
            cost = _cost_for_run(
                provider,
                summary["total_output_tokens"],
                summary["wall_time_s"],
                local_gpu_cost_per_hr,
            )
            local_cost_per_1m = (
                _local_cost_per_1m_output_tokens(summary["aggregate_tok_s"], local_gpu_cost_per_hr)
                if provider == "local" and local_gpu_cost_per_hr is not None
                else None
            )
            local_cost_per_request = (
                _local_cost_per_request(wall_time_s, local_gpu_cost_per_hr, summary["n_ok"])
                if provider == "local" and local_gpu_cost_per_hr is not None
                else None
            )
            rows.append(
                {
                    "provider": provider,
                    "concurrency": concurrency,
                    "mode": "serial" if serial else "concurrent",
                    "summary": summary,
                    "cost_usd": cost,
                    "cost_per_1m_output_tokens_local": local_cost_per_1m,
                    "cost_per_request_local": local_cost_per_request,
                    "raw": raw_results,
                }
            )
            print(_fmt_row(concurrency, summary, cost, local_cost_per_1m))
            if (
                bust_cache
                and vllm_metrics is not None
                and vllm_metrics["prefix_cache_hit_rate"] is not None
                and vllm_metrics["prefix_cache_hit_rate"] > _PREFIX_CACHE_HIT_RATE_WARN_THRESHOLD
            ):
                print(
                    f"  !!! WARNING: prefix cache hit rate "
                    f"{vllm_metrics['prefix_cache_hit_rate'] * 100:.1f}% at concurrency="
                    f"{concurrency} despite cache-busting being ON. Busting may not be "
                    "reaching the server, or the /metrics field names may be wrong -- "
                    "do not trust this cell's TTFT/latency numbers.",
                    file=sys.stderr,
                )
    finally:
        settings.llm_provider = original_provider
        settings.fallback_llm_provider = original_fallback
        settings.openai_chat_model = original_openai_model
        settings.chat_model = original_chat_model
        llm._client = None
        llm._client_provider = None

    return rows


def _write_jsonl(rows: list[dict], out_path: Path) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with out_path.open("a") as f:
        for row in rows:
            f.write(json.dumps({"timestamp": ts, **row}) + "\n")


def _load_prompts(path: Path) -> list[list[dict]]:
    """Load real captured prompts from eval/capture_bench_prompts.py's output
    (e.g. data/bench_prompts.jsonl). Each row's full `messages` (system prompt
    with real retrieval context + conversation history, plus the user query)
    is used as-is — this is what makes a sweep against this file measure
    DocChat's actual request shape instead of a bare query with no context.
    """
    prompts = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            prompts.append(json.loads(line)["messages"])
    if not prompts:
        raise ValueError(f"{path} contains no prompts")
    return prompts


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers",
        default="groq",
        help="Comma-separated providers to benchmark (groq, openai, mistral, local).",
    )
    parser.add_argument(
        "--concurrency",
        default=",".join(str(c) for c in _DEFAULT_CONCURRENCY_LEVELS),
        help="Comma-separated concurrency levels to sweep.",
    )
    parser.add_argument("--max-tokens", type=int, default=_DEFAULT_MAX_TOKENS)
    parser.add_argument(
        "--out",
        default="data/inference_benchmark.jsonl",
        help="JSONL file to append raw results to.",
    )
    parser.add_argument(
        "--openai-model",
        default=None,
        help=(
            "Override settings.openai_chat_model for this run only. The configured "
            "default can be a reasoning model that spends its whole --max-tokens "
            "budget on hidden reasoning and returns zero visible content -- pass a "
            "non-reasoning model here for a real throughput measurement. Production "
            "is untouched either way."
        ),
    )
    parser.add_argument(
        "--groq-model",
        default=None,
        help=(
            "Override settings.chat_model (the setting Groq reads) for this run "
            "only. The configured default can be a reasoning model that spends its "
            "whole --max-tokens budget on hidden reasoning and returns zero visible "
            "content -- pass a non-reasoning model here for a real throughput "
            "measurement. Production is untouched either way."
        ),
    )
    parser.add_argument(
        "--gpu-cost-per-hr",
        type=float,
        default=None,
        help="Rented GPU's $/hr. Required when 'local' is in --providers.",
    )
    parser.add_argument(
        "--prompts-file",
        default=None,
        help=(
            "JSONL of real captured prompts (eval/capture_bench_prompts.py's output, "
            "e.g. data/bench_prompts.jsonl) to use as the workload instead of "
            "eval/cases.py's bare queries. Each row's full messages (system + user, "
            "with real retrieval context) are sent as-is -- sizes the sweep to "
            "DocChat's actual request shape rather than a context-free query."
        ),
    )
    parser.add_argument(
        "--allow-prefix-cache",
        action="store_true",
        help=(
            "Disable cache-busting (default: ON). Without busting, identical prompts "
            "cycled across concurrency levels can be served from a vLLM/OpenAI prefix "
            "cache instead of fresh compute, making TTFT/decode numbers measure a "
            "cache lookup, not inference -- see eval/BENCHMARK_RESULTS.md's "
            "2026-09-30 'Third sweep' entry, where exactly this was flagged. Only "
            "pass this when a cache hit is genuinely what you want to measure."
        ),
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help=(
            "Phase 4 batching proof: run each concurrency level's requests strictly "
            "one at a time (no overlap) instead of firing them together, so the "
            "resulting wall time is a true no-batching baseline at that batch size -- "
            "directly comparable to a normal (concurrent) run at the same "
            "concurrency. See docs/superpowers/specs/2026-10-01-batching-proof-design.md."
        ),
    )
    args = parser.parse_args()
    bust_cache = not args.allow_prefix_cache

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    concurrency_levels = [int(c.strip()) for c in args.concurrency.split(",") if c.strip()]
    if args.prompts_file:
        prompts = _load_prompts(Path(args.prompts_file))
        print(f"Using {len(prompts)} real captured prompts from {args.prompts_file}")
    else:
        prompts = [[{"role": "user", "content": c.query}] for c in CASES]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if "local" in providers and not settings.local_base_url:
        print(
            "WARNING: 'local' requested but LOCAL_BASE_URL is unset — see "
            "docs/vllm_setup.md. Skipping.",
            file=sys.stderr,
        )
        providers = [p for p in providers if p != "local"]

    if "local" in providers and args.gpu_cost_per_hr is None:
        print(
            "WARNING: 'local' requested but --gpu-cost-per-hr was not given — cost "
            "for 'local' cannot be computed without it. Skipping 'local'.",
            file=sys.stderr,
        )
        providers = [p for p in providers if p != "local"]

    print(
        f"\nInference benchmark — {len(prompts)} prompts, concurrency {concurrency_levels}, "
        f"cache-busting {'ON' if bust_cache else 'OFF (--allow-prefix-cache)'}, "
        f"mode {'serial' if args.serial else 'concurrent'}\n"
    )

    all_rows: list[dict] = []
    timed_out = False
    for provider in providers:
        print(f"\n{provider}")
        print(_RULE)
        try:
            rows = await _run_provider(
                provider,
                prompts,
                concurrency_levels,
                args.max_tokens,
                args.gpu_cost_per_hr,
                args.openai_model,
                bust_cache,
                groq_model_override=args.groq_model,
                serial=args.serial,
            )
        except _CellTimeoutError as exc:
            all_rows.extend(exc.rows)
            timed_out = True
            break
        all_rows.extend(rows)

    _write_jsonl(all_rows, out_path)

    if timed_out:
        print(f"\n{_RULE}", file=sys.stderr)
        print(
            f"  ABORTED: a cell exceeded {_CELL_TIMEOUT_S}s. {len(all_rows)} finished "
            f"cell(s) saved to {out_path}. Sweep did not complete.",
            file=sys.stderr,
        )
        print(_RULE, file=sys.stderr)
        return

    print(f"\n{_RULE}")
    print(f"  Raw results appended to {out_path}")
    print("  Cost figures for hosted providers use the placeholder rates at the top of")
    print("  this file — verify against each provider's live pricing page before")
    print("  quoting externally. Check error_rate/empty_rate before trusting any")
    print("  percentile above them.")
    print(_RULE)


if __name__ == "__main__":
    asyncio.run(main())
