#!/usr/bin/env python3
"""Run identical prompts through the native and the LiteLLM backend and compare them.

Both backends talk to the same local mock OpenAI-compatible server over loopback, through the `local`
provider (the only provider whose address both backends let us redirect). Nothing leaves the machine and no
credentials are used. So this checks the contract (text, usage, finish reason, spans, errors) and measures
overhead against a server that answers instantly; it says nothing about real provider behaviour.

Needs the optional package:  pip install -r requirements-litellm.txt
Usage:  python -m eval.llm_backend_parity [--calls 200] [--output reports/llm-backend-parity.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.core import telemetry
from app.core.config import settings
from app.services import llm

PROMPTS = [
    [{"role": "system", "content": "Answer from the context only."}, {"role": "user", "content": "What is RAG?"}],
    [{"role": "user", "content": "Summarise the declaration in one line."}],
    [{"role": "user", "content": "What is the Slack incident ID?"}],
]


class _Mock(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][-1]["content"]
        if "fail" in prompt:
            data = json.dumps({"error": {"message": "overloaded", "type": "x"}}).encode()
            self.send_response(503)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        words = f"Answer to: {prompt}".split()
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for word in words:
                event = {"id": "c1", "object": "chat.completion.chunk", "model": body["model"],
                         "choices": [{"index": 0, "delta": {"content": word + " "}}]}
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            final = {"id": "c1", "object": "chat.completion.chunk", "model": body["model"],
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            usage = {"id": "c1", "object": "chat.completion.chunk", "model": body["model"], "choices": [],
                     "usage": {"prompt_tokens": 11, "completion_tokens": len(words), "total_tokens": 11 + len(words)}}
            self.wfile.write(f"data: {json.dumps(final)}\n\ndata: {json.dumps(usage)}\n\ndata: [DONE]\n\n".encode())
            return
        data = json.dumps({"id": "r1", "object": "chat.completion", "model": body["model"], "choices": [
            {"index": 0, "message": {"role": "assistant", "content": " ".join(words) + " "}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": len(words), "total_tokens": 11 + len(words)}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _Spans:
    """Capture span records without exporting them anywhere."""
    def __init__(self):
        self.records = []

    def __enter__(self):
        self._original = telemetry.emit
        telemetry.emit = self.records.append
        return self

    def __exit__(self, *exc):
        telemetry.emit = self._original


def _attempt_fields(records):
    keep = ("provider", "model", "streaming", "outcome", "prompt_tokens", "completion_tokens", "finish_reason")
    return [{key: r.get(key) for key in keep} for r in records if r.get("name") == "llm.attempt"]


async def _complete(messages):
    with _Spans() as spans:
        started = time.perf_counter()
        text = await llm.chat_complete(messages, max_tokens=64)
        elapsed = time.perf_counter() - started
    return {"text": text, "attempts": _attempt_fields(spans.records)}, elapsed


async def _stream(messages):
    sink: dict = {}
    with _Spans() as spans:
        started = time.perf_counter()
        first = None
        parts = []
        async for token in llm.chat_stream(messages, max_tokens=64, usage_sink=sink):
            first = first or time.perf_counter() - started
            parts.append(token)
        elapsed = time.perf_counter() - started
    return {"text": "".join(parts), "usage_sink": dict(sink), "attempts": _attempt_fields(spans.records)}, elapsed, first


async def _error(messages):
    try:
        await llm.chat_complete(messages, max_tokens=64)
    except Exception as exc:  # the type differs by design; the status code is what callers classify on
        return {"raised": True, "status_code": getattr(getattr(exc, "response", None), "status_code", None)
                or getattr(exc, "status_code", None), "retryable": llm._is_retryable_llm_error(exc)}
    return {"raised": False}


async def measure(backend: str, base_url: str, calls: int) -> dict:
    settings.llm_backend = backend
    settings.llm_provider = "local"
    settings.local_base_url = base_url
    settings.local_chat_model = "parity-model"
    settings.local_api_key = ""
    settings.local_stream_completions = False
    llm._clients.clear()
    out: dict = {"complete": [], "stream": [], "error": await _error([{"role": "user", "content": "please fail"}])}
    for messages in PROMPTS:
        result, _ = await _complete(messages)
        out["complete"].append(result)
        result, _, _ = await _stream(messages)
        out["stream"].append(result)
    times, ttfts, stream_times = [], [], []
    for index in range(calls):
        messages = PROMPTS[index % len(PROMPTS)]
        times.append((await _complete(messages))[1])
        _, total, first = await _stream(messages)
        stream_times.append(total)
        ttfts.append(first)
    await llm.close_llm_clients()
    out["timing_ms"] = {name: {"median": round(statistics.median(values) * 1000, 3),
                               "p95": round(sorted(values)[int(len(values) * 0.95) - 1] * 1000, 3)}
                        for name, values in {"complete": times, "stream_total": stream_times, "ttft": ttfts}.items()}
    return out


async def main_async(calls: int) -> dict:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Mock)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    started = time.perf_counter()
    import litellm  # noqa: F401  (imported once up front so its cold import cost is reported on its own)
    import_s = time.perf_counter() - started
    results = {"native": await measure("native", base_url, calls), "litellm": await measure("litellm", base_url, calls)}
    server.shutdown()
    same = {
        "completion_text": [a["text"] for a in results["native"]["complete"]] == [a["text"] for a in results["litellm"]["complete"]],
        "stream_text": [a["text"] for a in results["native"]["stream"]] == [a["text"] for a in results["litellm"]["stream"]],
        "stream_usage_sink": [a["usage_sink"] for a in results["native"]["stream"]] == [a["usage_sink"] for a in results["litellm"]["stream"]],
        "attempt_spans": [a["attempts"] for a in results["native"]["complete"] + results["native"]["stream"]]
                         == [a["attempts"] for a in results["litellm"]["complete"] + results["litellm"]["stream"]],
        "error_classified_the_same": results["native"]["error"]["retryable"] == results["litellm"]["error"]["retryable"],
    }
    return {"calls": calls, "litellm_cold_import_s_in_this_process": round(import_s, 2),
            "identical": same, "native": results["native"], "litellm": results["litellm"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(main_async(args.calls))
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
