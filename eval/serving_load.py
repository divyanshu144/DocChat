"""Sustained workloads for `python -m eval.inference_benchmark sustained`.

Schema v2 is separate from historical burst rows. Never rewrites previous results.
"""
import argparse
import asyncio
import hashlib
import json
import math
import statistics
import subprocess
import time
import uuid
from contextlib import aclosing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.core.telemetry import request_trace
from app.services import llm
from eval.workloads import load_workloads
from eval.serving_metrics import (ENGINE_METRIC_PREFIXES, ENGINE_METRIC_STATUS, counter_changes, parse_engine_metrics,
                                  prefix_cache_summary)


class ArtifactWriter:
    def __init__(self, directory, manifest):
        # Refuse overwrite, including failed/partial experiments.
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
        self.file = (directory / "events.jsonl").open("x")
        self.run_id = manifest["run_id"]

    def write(self, record):
        self.file.write(json.dumps({"schema_version": 2, "run_id": self.run_id, **record},
                                   allow_nan=False) + "\n")
        self.file.flush()

    def close(self):
        self.file.close()


P99_MIN_SAMPLES = 100  # p99 needs at least this many successes (and at least min_samples); fewer is just the maximum


def percentile(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * p) - 1)] if values else None


def summarize(rows, wall_s, *, min_samples=100, latency_slo=None):
    successful = [row for row in rows if row["status"] == "ok"]
    latencies = [row["total_s"] for row in successful]
    known = [row for row in successful if row.get("output_tokens") is not None]
    sufficient = len(successful) >= min_samples
    def p95(key):
        values = [r[key] for r in successful if r.get(key) is not None]
        return percentile(values, .95) if len(values) >= min_samples else None
    p99_floor = max(min_samples, P99_MIN_SAMPLES)

    def p99(values):
        return percentile(values, .99) if len(values) >= p99_floor else None
    return {
        "offered": len(rows), "completed_ok": len(successful),
        "errors": sum(r["status"] == "error" for r in rows),
        "timeouts": sum(r["status"] == "timeout" for r in rows),
        "empty": sum(r["status"] == "empty" for r in rows),
        "cancelled": sum(r["status"] == "cancelled" for r in rows),
        "load_generator_rejected": sum(r["status"] == "rejected" for r in rows),
        "error_rate": (len(rows) - len(successful)) / len(rows) if rows else None,
        "wall_s": wall_s, "successful_requests_per_second": len(successful) / wall_s if wall_s > 0 else None,
        "latency_p50_s": percentile(latencies, .5),
        "latency_p95_s": percentile(latencies, .95) if sufficient else None,
        "ttft_p95_s": p95("ttft_s"), "first_answer_p95_s": p95("first_answer_s"),
        "latency_p99_s": p99(latencies), "ttft_p99_s": p99([r["ttft_s"] for r in successful if r.get("ttft_s") is not None]),
        "p99_min_samples": p99_floor,
        "insufficient_samples": not sufficient, "min_percentile_samples": min_samples,
        "known_output_usage_requests": len(known),
        "output_tokens_per_second": (sum(r["output_tokens"] for r in known) / wall_s
                                     if successful and len(known) == len(successful) and wall_s > 0 else None),
        "truncated": sum(r.get("finish_reason") == "length" for r in rows),
        "slo_goodput_requests_per_second": (sum(r["total_s"] <= latency_slo for r in successful) / wall_s
                                           if latency_slo is not None and wall_s > 0 else None),
    }


async def replay_request(case, identifier, cache_mode):
    messages = [message.model_dump() for message in case.messages]
    if cache_mode == "bust":
        # Same cache-control method as the historical harness, with no mutation.
        messages[0] = {**messages[0], "content": f"request_id: {identifier}\n" + messages[0]["content"]}
    sink = {}
    first = last = None
    chunks = 0
    started = time.perf_counter()
    with request_trace(identifier, transport="benchmark"):
        async with aclosing(llm.chat_stream(messages, max_tokens=case.max_tokens, usage_sink=sink)) as stream:
            async for text in stream:
                if not text:
                    continue
                last = time.perf_counter()
                first = last if first is None else first
                chunks += 1
    output = sink.get("completion_tokens")
    output = output if type(output) is int and output >= 0 else None
    input_tokens = sink.get("prompt_tokens")
    input_tokens = input_tokens if type(input_tokens) is int and input_tokens >= 0 else None
    return {"status": "ok" if chunks else "empty", "ttft_s": first - started if first is not None else None,
            "first_answer_s": None, "input_tokens": input_tokens, "output_tokens": output,
            "usage_source": "provider" if output is not None else "unknown", "content_chunks": chunks,
            "finish_reason": sink.get("finish_reason"),
            "decode_tokens_per_second_estimate": ((output - 1) / (last - first)
                if output is not None and output > 1 and first is not None and last > first else None)}


class SSEProtocolError(ValueError):
    pass


async def api_request(client, case, identifier):
    """Consume the actual chat contract; progress is not first answer and 200 isn't success."""
    first = None
    content = False
    done = False
    event = "message"
    data = []
    data_size = 0
    started = time.perf_counter()
    async with client.stream("POST", "chat", json={"query": case.query, "source_ids": case.source_ids},
                             headers={"X-Request-Id": identifier}) as response:
        response.raise_for_status()
        if "text/event-stream" not in response.headers.get("content-type", ""):
            raise SSEProtocolError("Expected SSE")
        async for line in response.aiter_lines():
            if line == "":
                value = "\n".join(data)
                if event == "error":
                    raise SSEProtocolError("Chat returned an error event")
                if event == "token" and value:
                    content = True
                    if first is None:
                        first = time.perf_counter() - started
                if event == "done":
                    if value != "[DONE]":
                        raise SSEProtocolError("Invalid completion marker")
                    done = True
                    break
                event, data, data_size = "message", [], 0
            elif line.startswith("event:"):
                event = line[6:].lstrip(" ")
            elif line.startswith("data:"):
                value = line[5:]
                value = value[1:] if value.startswith(" ") else value
                data_size += len(value)
                if data_size > 1_000_000:
                    raise SSEProtocolError("Oversized SSE event")
                data.append(value)
    if not done:
        raise SSEProtocolError("Missing completion marker")
    return {"status": "ok" if content else "empty", "first_answer_s": first, "ttft_s": None,
            "input_tokens": None, "output_tokens": None, "usage_source": "unavailable_over_chat_sse",
            "finish_reason": None, "decode_tokens_per_second_estimate": None}


async def run_cell(cases, request, *, concurrency, duration_s, max_requests, timeout_s,
                   write, cell_id, arrival_rate=None, phase="measurement", min_samples=100,
                   latency_slo=None):
    """Bounded closed-loop workers or paced arrivals; record every offered request."""
    if not cases or concurrency < 1 or min(duration_s, max_requests, timeout_s) <= 0:
        raise ValueError("Cases and positive load limits are required")
    if arrival_rate is not None and arrival_rate <= 0:
        raise ValueError("arrival_rate must be positive")
    started = time.perf_counter()
    started_wall = datetime.now(timezone.utc)  # wall clock, only used to align external samples
    deadline = started + duration_s
    rows = []
    next_index = 0
    pending = set()
    interrupted = False

    def base(index):
        case = cases[index % len(cases)]
        return case, {"event": "request", "cell_id": cell_id, "phase": phase,
                      "request_id": str(uuid.uuid4()), "case_id": case.id,
                      "split": case.split, "category": case.category}

    def save(row):
        rows.append(row)
        write(row)

    async def execute(case, row, scheduled):
        dispatched = time.perf_counter()
        result = {}
        try:
            async with asyncio.timeout(timeout_s):
                result = await request(case, row["request_id"])
        except (TimeoutError, httpx.TimeoutException):
            result = {"status": "timeout", "error_type": "TimeoutError"}
        except asyncio.CancelledError:
            result = {"status": "cancelled", "error_type": "CancelledError"}
            raise
        except Exception as exc:
            result = {"status": "error", "error_type": type(exc).__name__}
            if isinstance(exc, httpx.HTTPStatusError):
                result["http_status"] = exc.response.status_code
        finally:
            ended = time.perf_counter()
            save({**row, **result, "scheduled_offset_s": scheduled - started,
                  "dispatch_offset_s": dispatched - started, "schedule_lag_s": dispatched - scheduled,
                  "service_s": ended - dispatched, "total_s": ended - scheduled})

    async def worker():
        nonlocal next_index
        while next_index < max_requests and time.perf_counter() < deadline:
            index = next_index
            next_index += 1
            case, row = base(index)
            await execute(case, row, time.perf_counter())

    try:
        if arrival_rate is None:
            pending = {asyncio.create_task(worker()) for _ in range(concurrency)}
            await asyncio.gather(*pending)
        else:
            while next_index < max_requests:
                scheduled = started + next_index / arrival_rate
                if scheduled >= deadline:
                    break
                await asyncio.sleep(max(0, scheduled - time.perf_counter()))
                for task in pending:
                    if task.done():
                        task.result()  # surface writer failures before pruning
                pending = {task for task in pending if not task.done()}
                case, row = base(next_index)
                next_index += 1
                lag = time.perf_counter() - scheduled
                if len(pending) >= concurrency or lag >= 1 / arrival_rate:
                    save({**row, "status": "rejected", "error_type": (
                        "load_generator_capacity" if len(pending) >= concurrency else "missed_schedule"),
                        "scheduled_offset_s": scheduled - started, "schedule_lag_s": lag,
                        "total_s": lag, "service_s": 0})
                else:
                    pending.add(asyncio.create_task(execute(case, row, scheduled)))
            await asyncio.gather(*pending)
    except BaseException:
        interrupted = True
        raise
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        wall = time.perf_counter() - started
        ended_wall = datetime.now(timezone.utc)
        summary = {"event": "cell_summary", "cell_id": cell_id, "phase": phase,
                   "window": {"started_at": started_wall.isoformat(), "ended_at": ended_wall.isoformat(),
                              "clock": "benchmark_client_wall_clock_utc"},
                   "interrupted": interrupted, "concurrency": concurrency, "arrival_rate": arrival_rate,
                   "duration_limit_s": duration_s, "request_limit": max_requests,
                   "stop_reason": "interrupted" if interrupted else (
                       "request_limit" if next_index >= max_requests else "duration"),
                   "summary": summarize(rows, wall, min_samples=min_samples, latency_slo=latency_slo),
                   "categories": {category: summarize([r for r in rows if r["category"] == category], wall,
                                      min_samples=min_samples, latency_slo=latency_slo)
                                  for category in sorted({case.category for case in cases})},
                   "splits": {split: summarize([r for r in rows if r["split"] == split], wall,
                                      min_samples=min_samples, latency_slo=latency_slo)
                              for split in sorted({case.split for case in cases})}}
        write(summary)
    return summary


async def poll_engine(client, url, write, cell_id, stop, ready=None, engine="vllm"):
    first = last = None
    failed = 0
    resets = set()
    async def sample():
        nonlocal first, last, failed
        try:
            response = await client.get(url, timeout=2)
            response.raise_for_status()
            values = parse_engine_metrics(response.text, ENGINE_METRIC_PREFIXES[engine])
            if not values:
                raise ValueError(f"No {engine} series")
            if last is not None:
                for row in counter_changes(last, values):
                    if row["reset"]:
                        resets.add((row["name"], tuple(sorted(row["labels"].items()))))
            first = values if first is None else first
            last = values
            record = {"status": "ok", "samples": values}
        except Exception as exc:
            failed += 1
            record = {"status": "error", "error_type": type(exc).__name__}
        write({"event": "engine_metrics", "cell_id": cell_id,
               "timestamp": datetime.now(timezone.utc).isoformat(), **record})
    try:
        await sample()
    finally:
        if ready is not None:
            ready.set()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            await sample()
    await sample()
    changes = counter_changes(first, last) if first is not None and last is not None else None
    for row in changes or []:
        if (row["name"], tuple(sorted(row["labels"].items()))) in resets:
            row.update(reset=True, delta=None)
    write({"event": "engine_counter_changes", "cell_id": cell_id, "failed_scrapes": failed,
           "changes": changes, "prefix_cache": prefix_cache_summary(changes, engine)})


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be positive and finite")
    return number


def http_url(value):
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise argparse.ArgumentTypeError("Use an HTTP(S) URL without credentials, query or fragment")
    return value


def read_token(path):
    value = path.read_text().strip() if path else ""
    if "\n" in value or "\r" in value or (path and not value):
        raise ValueError("Token file must contain one nonempty line")
    return {"Authorization": f"Bearer {value}"} if value else {}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--target", choices=["replay", "api"], default="replay")
    parser.add_argument("--provider", choices=["groq", "mistral", "openai", "local"], default="local")
    parser.add_argument("--api-base-url", type=http_url, default="http://127.0.0.1:8081/api/v1/")
    parser.add_argument("--auth-token-file", type=Path)
    parser.add_argument("--metrics-url", type=http_url)
    parser.add_argument("--engine", choices=sorted(ENGINE_METRIC_PREFIXES), default="vllm",
                        help="serving engine, for metric-name parsing only (the request path is OpenAI-compatible); "
                             "sglang names are unverified")
    parser.add_argument("--metrics-token-file", type=Path)
    parser.add_argument("--deployment-manifest", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--concurrency", default="1,4,16,32,64")
    parser.add_argument("--arrival-rates", default=None, help="Comma-separated requests/sec; omit for closed loop")
    parser.add_argument("--duration", type=positive_float, default=60)
    parser.add_argument("--requests", type=positive_int, default=1000)
    parser.add_argument("--timeout", type=positive_float, default=120)
    parser.add_argument("--repeats", type=positive_int, default=3)
    parser.add_argument("--warmup", type=int, default=4)
    parser.add_argument("--min-samples", type=positive_int, default=100)
    parser.add_argument("--latency-slo", type=positive_float)
    parser.add_argument("--cache-mode", choices=["bust", "reuse"], default="reuse")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    if args.warmup < 0:
        parser.error("--warmup must be nonnegative")
    try:
        args.levels = [positive_int(x) for x in args.concurrency.split(",")]
        args.rates = [positive_float(x) for x in args.arrival_rates.split(",")] if args.arrival_rates else [None]
    except (ValueError, argparse.ArgumentTypeError):
        parser.error("Invalid concurrency or arrival-rate list")
    if len(set(args.levels)) != len(args.levels) or len(set(args.rates)) != len(args.rates):
        parser.error("Duplicate load levels are not allowed; use --repeats")
    if args.target == "api" and args.cache_mode == "bust":
        parser.error("API mode preserves queries; use --cache-mode reuse")
    if args.target == "api" and not args.auth_token_file and not args.validate_only:
        parser.error("API benchmarks require --auth-token-file")
    return args


# Only these manifest keys are copied into artifacts (never arbitrary fields, which might hold credentials).
DEPLOYMENT_FIELDS = {"engine", "image_digest", "engine_version", "model_repository", "model_revision",
                         "tokenizer_repository", "tokenizer_revision", "chat_template_sha256", "served_model_name",
                         "gpu_name", "gpu_count", "gpu_memory_mib", "driver", "cuda", "torch", "compute_dtype",
                         "weight_quantization", "quantization_kernel", "kv_cache_dtype", "max_model_len",
                         "gpu_memory_utilization", "prefix_caching", "hourly_cost_usd",
                         "application_revision", "application_config_sha256"}


def source_provenance():
    root = Path(__file__).resolve().parent.parent
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                           stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    digest = hashlib.sha256()
    paths = sorted([*root.glob("app/**/*.py"), *root.glob("eval/**/*.py"), root / "requirements.txt"])
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return {"git_commit": revision, "python_source_sha256": digest.hexdigest()}


def repeat_summary(cells):
    groups = {}
    for cell in cells:
        key = (cell["concurrency"], cell["arrival_rate"])
        groups.setdefault(key, []).append(cell["summary"])
    result = []
    for (concurrency, rate), rows in groups.items():
        stats = {}
        for metric in ("successful_requests_per_second", "output_tokens_per_second", "latency_p95_s", "error_rate"):
            values = [row[metric] for row in rows if row.get(metric) is not None]
            stats[metric] = {"available_repeats": len(values), "mean": statistics.mean(values) if values else None,
                             "min": min(values) if values else None, "max": max(values) if values else None,
                             "stdev": statistics.stdev(values) if len(values) > 1 else None}
        result.append({"concurrency": concurrency, "arrival_rate": rate, "repeats": len(rows), "statistics": stats})
    return result


async def main(argv=None):
    args = parse_args(argv)
    workloads = load_workloads(args.workloads, args.target)
    deployment = json.loads(args.deployment_manifest.read_text()) if args.deployment_manifest else None
    if deployment is not None and not isinstance(deployment, dict):
        raise ValueError("Deployment manifest must be a JSON object")
    # Do not copy arbitrary manifest fields (which might include credentials).
    deployment_hash = hashlib.sha256(args.deployment_manifest.read_bytes()).hexdigest() if args.deployment_manifest else None
    if args.validate_only:
        print(json.dumps({"valid": True, "cases": len(workloads.cases), "workload_sha256": workloads.fingerprint(),
                          "categories": sorted({c.category for c in workloads.cases})}))
        return
    auth = read_token(args.auth_token_file)
    metric_auth = read_token(args.metrics_token_file)
    run_id = str(uuid.uuid4())
    manifest = {"schema_version": 2, "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(), "target": args.target,
                "provider": args.provider if args.target == "replay" else "remote_application",
                "engine_family": args.engine, "engine_metrics_status": ENGINE_METRIC_STATUS[args.engine],
                "workload_sha256": workloads.fingerprint(), "corpus_sha256": workloads.corpus_sha256,
                "corpus_fingerprint_source": "workload_manifest; not checked against live index",
                "deployment_sha256": deployment_hash, "deployment_verified_by_runner": False,
                "deployment": {key: value for key, value in (deployment or {}).items() if key in DEPLOYMENT_FIELDS},
                "source": source_provenance(),
                "cases": [{"id": c.id, "split": c.split, "category": c.category, "max_tokens": c.max_tokens,
                           "prompt_sha256": hashlib.sha256(json.dumps([m.model_dump() for m in c.messages],
                                                                        sort_keys=True).encode()).hexdigest()}
                          for c in workloads.cases],
                "sampling": "provider defaults (repeated runs are not deterministic)",
                "concurrency": args.levels, "arrival_rates": args.rates, "repeats": args.repeats,
                "duration_s": args.duration, "request_limit": args.requests, "timeout_s": args.timeout,
                "warmup_requests": args.warmup, "cache_mode": args.cache_mode,
                "min_samples": args.min_samples, "latency_slo_s": args.latency_slo,
                "token_policy": "provider_usage_only; unknown stays null",
                "api_output_cap": "server_defined" if args.target == "api" else "per_case",
                "notes": ["Success percentiles exclude errors; inspect error and rejection rates",
                          "Throughput uses cohort wall time including final drain",
                          "Category request rates are contributions to the mixed workload",
                          "No confidence intervals computed; inspect repeated cells",
                          "API mode does not disable server fallback/rate limits or report token usage"]}
    writer = ArtifactWriter(args.out_dir, manifest)
    original = (settings.llm_provider, settings.fallback_llm_provider, settings.groq_fallback_chat_model)
    outcome = "error"
    summaries = []
    try:
        if args.target == "replay":
            await llm.close_llm_clients()
            settings.llm_provider = args.provider
            settings.fallback_llm_provider = "none"
            settings.groq_fallback_chat_model = ""
            writer.write({"event": "backend", "provider": args.provider, "model": llm._active_model()})
            if args.provider == "local":
                llm.validate_local_endpoint()
                if not settings.local_chat_model:
                    raise ValueError("LOCAL_CHAT_MODEL required")
        async with httpx.AsyncClient(base_url=args.api_base_url.rstrip("/") + "/", headers=auth,
                                     timeout=args.timeout, limits=httpx.Limits(
                                         max_connections=max(args.levels), max_keepalive_connections=max(args.levels))) as api_client, \
                   httpx.AsyncClient(headers=metric_auth) as metric_client:
            async def request(case, identifier):
                if args.target == "api":
                    return await api_request(api_client, case, identifier)
                return await replay_request(case, identifier, args.cache_mode)

            for repeat in range(args.repeats):
                for concurrency in args.levels:
                    for rate in args.rates:
                        cell_id = f"r{repeat + 1}-c{concurrency}-rate{rate}"
                        if args.warmup:
                            await run_cell(workloads.cases, request, concurrency=1, duration_s=args.timeout * args.warmup,
                                           max_requests=args.warmup, timeout_s=args.timeout, write=writer.write,
                                           cell_id=cell_id + "-warmup", phase="warmup")
                        stop = asyncio.Event()
                        ready = asyncio.Event()
                        poller = asyncio.create_task(poll_engine(metric_client, args.metrics_url, writer.write,
                                                                cell_id, stop, ready, args.engine)) if args.metrics_url else None
                        try:
                            if poller:
                                await ready.wait()
                                if poller.done():
                                    poller.result()
                            summary = await run_cell(workloads.cases, request, concurrency=concurrency,
                                duration_s=args.duration, max_requests=args.requests, timeout_s=args.timeout,
                                write=writer.write, cell_id=cell_id, arrival_rate=rate,
                                min_samples=args.min_samples, latency_slo=args.latency_slo)
                            summaries.append(summary)
                            print(json.dumps({"cell_id": cell_id, **summary["summary"]}))
                        finally:
                            stop.set()
                            if poller:
                                await poller
        outcome = "complete"
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        settings.llm_provider, settings.fallback_llm_provider, settings.groq_fallback_chat_model = original
        try:
            if args.target == "replay":
                await llm.close_llm_clients()
        finally:
            writer.write({"event": "run_summary", "cells": repeat_summary(summaries)})
            writer.write({"event": "run_end", "outcome": outcome,
                          "timestamp": datetime.now(timezone.utc).isoformat()})
            writer.close()
