#!/usr/bin/env python3
"""Positive control for eval/inference_benchmark.py's cache-busting +
vLLM /metrics instrumentation.

Before trusting a full concurrency sweep's prefix-cache-hit-rate numbers,
this proves the instrumentation itself works: send the same prompt twice
with busting OFF (expect a high hit rate -- the second request should hit
the first's cached prefix), then twice with busting ON (expect ~0% -- each
request's unique `request_id` line breaks the prefix). If busting doesn't
change the measured hit rate, the metric names in
eval.inference_benchmark._VLLM_METRIC_CANDIDATES are wrong for this server,
or busting isn't reaching it -- and the sweep's numbers can't be trusted.

Usage:
    python eval/positive_control.py --prompts-file data/bench_prompts.jsonl

Exit code 0: the expected OFF-high / ON-low split was observed.
Exit code 1: it wasn't -- do not proceed to the full sweep.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.config import settings
from app.services import llm
from eval.inference_benchmark import (
    _VLLM_METRIC_CANDIDATES,
    _load_prompts,
    _parse_prometheus_metrics,
    _resolve_metric,
    _run_request,
)

_RULE = "-" * 78

# Above this, an OFF-phase hit rate counts as "high" (a real hit was seen).
_OFF_HIT_RATE_FLOOR = 0.10
# Below this, an ON-phase hit rate counts as "near zero" (busting worked).
_ON_HIT_RATE_CEILING = 0.10


async def _scrape_raw(metrics_url: str) -> dict[str, float]:
    """Like _scrape_vllm_metrics but returns the raw {name: value} map (not
    resolved to candidate keys) -- the control needs to print which literal
    metric names it actually found, not just the resolved figure."""
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(metrics_url)
        resp.raise_for_status()
        return _parse_prometheus_metrics(resp.text)


def _hit_rate(before: dict[str, float], after: dict[str, float]) -> tuple[float | None, str, str]:
    """Delta hit rate between two raw scrapes, plus which literal metric name
    matched for queries/hits (for the printed report)."""
    q_name = next((n for n in _VLLM_METRIC_CANDIDATES["prefix_cache_queries"] if n in after), "NOT FOUND")
    h_name = next((n for n in _VLLM_METRIC_CANDIDATES["prefix_cache_hits"] if n in after), "NOT FOUND")
    q0 = _resolve_metric(before, _VLLM_METRIC_CANDIDATES["prefix_cache_queries"])
    h0 = _resolve_metric(before, _VLLM_METRIC_CANDIDATES["prefix_cache_hits"])
    q1 = _resolve_metric(after, _VLLM_METRIC_CANDIDATES["prefix_cache_queries"])
    h1 = _resolve_metric(after, _VLLM_METRIC_CANDIDATES["prefix_cache_hits"])
    if q0 is None or h0 is None or q1 is None or h1 is None:
        return None, q_name, h_name
    dq = q1 - q0
    dh = h1 - h0
    if dq <= 0:
        return None, q_name, h_name
    return dh / dq, q_name, h_name


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts-file", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=200)
    args = parser.parse_args()

    if args.prompts_file:
        prompts = _load_prompts(args.prompts_file)
    else:
        prompts = [[{"role": "user", "content": "What is the capital of France?"}]]
    prompt = prompts[0]

    if not settings.local_base_url:
        print("LOCAL_BASE_URL is not set -- cannot run the positive control.", file=sys.stderr)
        sys.exit(1)

    metrics_url = settings.local_base_url.removesuffix("/v1") + "/metrics"

    settings.llm_provider = "local"
    settings.fallback_llm_provider = "none"
    llm._client = None
    llm._client_provider = None

    print(_RULE)
    print("Positive control: proving cache-busting + /metrics instrumentation works")
    print(_RULE)

    before_off = await _scrape_raw(metrics_url)
    for _ in range(2):
        await _run_request(prompt, args.max_tokens, bust_cache=False)
    after_off = await _scrape_raw(metrics_url)
    off_rate, q_name, h_name = _hit_rate(before_off, after_off)

    print(f"\nMetric names found on this server: queries={q_name}  hits={h_name}")
    print(f"Busting OFF (2x identical prompt): prefix cache hit rate = {off_rate}")

    before_on = await _scrape_raw(metrics_url)
    for _ in range(2):
        await _run_request(prompt, args.max_tokens, bust_cache=True)
    after_on = await _scrape_raw(metrics_url)
    on_rate, _, _ = _hit_rate(before_on, after_on)

    print(f"Busting ON  (2x unique prompt):    prefix cache hit rate = {on_rate}")
    print(_RULE)

    off_ok = off_rate is not None and off_rate > _OFF_HIT_RATE_FLOOR
    on_ok = on_rate is not None and on_rate < _ON_HIT_RATE_CEILING

    if off_ok and on_ok:
        print("PASS: OFF showed a real cache hit, ON showed near-zero. Instrumentation verified.")
        sys.exit(0)
    else:
        print("FAIL: expected OFF high / ON near-zero, did not observe it.")
        print("Do NOT proceed to the full sweep -- see module docstring.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
