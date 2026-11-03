#!/usr/bin/env python3
"""Send the same real requests to Groq through the native backend and the LiteLLM backend, and compare them.

This is the live counterpart of `llm_backend_parity.py`, which only talks to a local mock server. It calls the real
Groq API with the key from the environment (never printed), so it spends a small amount of the Groq quota: about
`--reps` x 3 prompts x 2 modes x 2 backends calls, each capped at `--max-tokens`.

The fallback to OpenAI is switched off, so every answer comes from Groq. The two backends are called alternately for
each prompt, so a slow minute on Groq hits both arms. A model that is not deterministic at temperature 0 can give
different words each time, so the text is compared for *shape* (non-empty, finish reason, token counts in range) and the
exact-match rate is reported, not required.

Needs:  pip install -r requirements-litellm.txt   and GROQ_API_KEY
Usage:  python -m eval.llm_backend_live_parity [--reps 5] [--max-tokens 400] [--output reports/llm-backend-live-parity.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from app.core import telemetry
from app.core.config import settings
from app.services import llm

PROMPTS = [
    [{"role": "system", "content": "Answer in one short sentence."}, {"role": "user", "content": "What does RAG stand for in AI?"}],
    [{"role": "user", "content": "Name the capital of France. One word."}],
    [{"role": "user", "content": "Is 17 a prime number? Answer yes or no, then one reason."}],
]


class _Spans:
    def __enter__(self):
        self.records: list[dict] = []
        self._original = telemetry.emit
        telemetry.emit = self.records.append
        return self

    def __exit__(self, *exc):
        telemetry.emit = self._original


def _attempts(records):
    keep = ("provider", "model", "streaming", "outcome", "prompt_tokens", "completion_tokens", "finish_reason")
    return [{k: r.get(k) for k in keep} for r in records if r.get("name") == "llm.attempt"]


def _status(exc: Exception):
    return getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)


async def _one(mode: str, messages, max_tokens: int) -> dict:
    """One real call. Failures are recorded as data, never skipped."""
    sink: dict = {}
    started = time.perf_counter()
    first = None
    text = ""
    try:
        with _Spans() as spans:
            if mode == "complete":
                text = await llm.chat_complete(messages, max_tokens=max_tokens, temperature=0)
            else:
                parts = []
                async for token in llm.chat_stream(messages, max_tokens=max_tokens, usage_sink=sink):
                    first = first if first is not None else time.perf_counter() - started
                    parts.append(token)
                text = "".join(parts)
        return {"ok": bool(text.strip()), "text": text, "elapsed_s": time.perf_counter() - started, "ttft_s": first,
                "usage_sink": dict(sink), "attempts": _attempts(spans.records)}
    except Exception as exc:
        return {"ok": False, "text": "", "elapsed_s": time.perf_counter() - started, "ttft_s": first,
                "error": type(exc).__name__, "status": _status(exc), "retryable": llm._is_retryable_llm_error(exc),
                "attempts": []}


async def _error_cases() -> dict:
    """Bad request cases that must raise the same status on both backends and must not fall back."""
    out = {}
    real_key, real_model = settings.groq_api_key, settings.chat_model
    for name, key, model in (("bad_key", "gsk_invalid_key_for_parity_test", real_model), ("unknown_model", real_key, "no/such-model")):
        settings.groq_api_key, settings.chat_model = key, model
        llm._clients.clear()
        out[name] = await _one("complete", PROMPTS[1], 16)
        out[name].pop("text", None)
    settings.groq_api_key, settings.chat_model = real_key, real_model
    llm._clients.clear()
    return out


def _stats(values):
    values = [v for v in values if v is not None]
    return {"n": len(values), "median_s": round(statistics.median(values), 3) if values else None,
            "max_s": round(max(values), 3) if values else None}


async def run(reps: int, max_tokens: int) -> dict:
    settings.llm_provider = "groq"
    settings.fallback_llm_provider = "none"  # a fallback would make a Groq failure look like a success
    if not settings.groq_api_key:
        raise SystemExit("GROQ_API_KEY is not set")
    rows: dict[str, dict[str, list[dict]]] = {b: {"complete": [], "stream": []} for b in ("native", "litellm")}
    for rep in range(reps):
        for messages in PROMPTS:
            for mode in ("complete", "stream"):
                for backend in (("native", "litellm") if rep % 2 == 0 else ("litellm", "native")):
                    settings.llm_backend = backend
                    llm._clients.clear()
                    rows[backend][mode].append({**await _one(mode, messages, max_tokens), "prompt": messages[-1]["content"], "rep": rep})
                    if rows[backend][mode][-1].get("status") == 429:
                        await asyncio.sleep(5)
    errors = {}
    for backend in ("native", "litellm"):
        settings.llm_backend = backend
        errors[backend] = await _error_cases()
    await llm.close_llm_clients()

    summary = {}
    for backend, modes in rows.items():
        summary[backend] = {}
        for mode, items in modes.items():
            okay = [r for r in items if r["ok"]]
            summary[backend][mode] = {
                "calls": len(items), "ok": len(okay), "errors": sorted({f"{r.get('error')}:{r.get('status')}" for r in items if not r["ok"]}),
                "finish_reasons": sorted({a["finish_reason"] for r in okay for a in r["attempts"]}),
                "elapsed": _stats([r["elapsed_s"] for r in okay]),
                **({"ttft": _stats([r["ttft_s"] for r in okay])} if mode == "stream" else {}),
                "usage_recorded": sum(bool(a.get("completion_tokens")) for r in okay for a in r["attempts"]),
                "models": sorted({a["model"] for r in okay for a in r["attempts"]}),
            }
    pairs = {}
    for mode in ("complete", "stream"):
        both = [(a, b) for a, b in zip(rows["native"][mode], rows["litellm"][mode], strict=True) if a["ok"] and b["ok"]]
        pairs[mode] = {"pairs_both_ok": len(both),
                       "exact_same_text": sum(a["text"].strip() == b["text"].strip() for a, b in both),
                       "same_finish_reason": sum([x["finish_reason"] for x in a["attempts"]] == [x["finish_reason"] for x in b["attempts"]] for a, b in both),
                       "same_provider_and_model": sum([(x["provider"], x["model"]) for x in a["attempts"]] == [(x["provider"], x["model"]) for x in b["attempts"]] for a, b in both)}
    for backend in rows.values():  # drop the answer text from the saved report; the metrics above are what matter
        for items in backend.values():
            for r in items:
                r["text_chars"] = len(r.pop("text"))
    return {"reps": reps, "max_tokens": max_tokens, "provider": "groq", "model": settings.chat_model, "summary": summary,
            "paired": pairs, "error_cases": errors, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run(args.reps, args.max_tokens))
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(json.dumps({k: report[k] for k in ("summary", "paired", "error_cases")}, indent=2, default=str))


if __name__ == "__main__":
    main()
