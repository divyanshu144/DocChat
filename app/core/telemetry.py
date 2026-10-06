"""Content-free JSON timing records; no external exporter or prompt capture.

ContextVars carry identity across async graph tasks. The mutable request record is
shared only by children of that request; span identity stays task-local.
"""
import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import contextmanager, nullcontext, aclosing
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps

logger = logging.getLogger(__name__)


@dataclass
class Trace:
    request_id: str
    started: float = field(default_factory=lambda: time.perf_counter())
    outcome: str = "ok"
    first_answer_s: float | None = None
    llm_attempts: int = 0
    route: str | None = None
    status_code: int = 500


_trace: ContextVar[Trace | None] = ContextVar("docchat_trace", default=None)
_current_span: ContextVar[dict | None] = ContextVar("docchat_span", default=None)


def emit(record: dict) -> None:
    # A logging/exporter failure must never break generation or mask its exception.
    try:
        from app.core.metrics import metrics
        metrics.observe(record)
    except Exception:
        pass
    try:
        logger.info(json.dumps(record, separators=(",", ":")))
    except Exception:
        pass


def request_id() -> str | None:
    trace = _trace.get()
    return trace.request_id if trace else None


def mark_error() -> None:
    if trace := _trace.get():
        trace.outcome = "error"


def annotate(**fields) -> None:
    if current := _current_span.get():
        current.update(fields)


def record_usage(usage, finish_reason=None, backend_request_id=None) -> None:
    """Accept SDK or JSON usage without stringifying unknown objects or secrets."""
    fields = {}
    for name in ("prompt_tokens", "completion_tokens"):
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if type(value) is int and value >= 0:
            fields[name] = value
    if isinstance(finish_reason, str):
        fields["finish_reason"] = finish_reason[:64]
    if isinstance(backend_request_id, str):
        fields["backend_request_id"] = backend_request_id[:128]
    annotate(**fields)


@contextmanager
def request_trace(identifier: str | None = None, **fields):
    trace = Trace(identifier or str(uuid.uuid4()))
    token = _trace.set(trace)
    parent_token = _current_span.set(None)
    emit({"event": "request_started", "request_id": trace.request_id, **fields})
    try:
        yield trace
    except (asyncio.CancelledError, GeneratorExit):
        trace.outcome = "cancelled"
        raise
    except BaseException:
        trace.outcome = "error"
        raise
    finally:
        emit({"event": "request", "request_id": trace.request_id,
              "duration_s": time.perf_counter() - trace.started,
              "first_answer_s": trace.first_answer_s, "outcome": trace.outcome,
              "route": trace.route, "status_code": trace.status_code, **fields})
        _current_span.reset(parent_token)
        _trace.reset(token)


@contextmanager
def span(name: str, **fields):
    parent = _current_span.get()
    record = {"event": "span", "name": name, "request_id": request_id(),
              "span_id": str(uuid.uuid4()),
              "parent_span_id": parent["span_id"] if parent else None,
              "outcome": "ok", **fields}
    if name == "llm.attempt" and (trace := _trace.get()):
        trace.llm_attempts += 1
        record["attempt_index"] = trace.llm_attempts
    token = _current_span.set(record)
    started = time.perf_counter()
    try:
        yield record
    except (asyncio.CancelledError, GeneratorExit):
        record["outcome"] = "cancelled"
        raise
    except BaseException as exc:
        record.update(outcome="error", error_type=type(exc).__name__)
        raise
    finally:
        record["duration_s"] = time.perf_counter() - started
        _current_span.reset(token)
        emit(record)


def traced_node(name):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(state):
            with span(name, iteration=state.get("iteration", 0) + 1):
                return await fn(state)
        return wrapped
    return decorate


class RequestTelemetryMiddleware:
    """Pure ASGI middleware: finish after the stream, not after response headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        from app.core.config import settings
        if scope["type"] != "http" or scope.get("path", "").rstrip("/") == f"{settings.api_prefix}/metrics":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        identifier = supplied if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", supplied) else None
        with request_trace(identifier, transport="http", method=scope["method"]) as trace:
            status = 500
            complete = False
            sse = False
            tail = b""

            async def observed_receive():
                message = await receive()
                if message["type"] == "http.disconnect" and not complete:
                    trace.outcome = "cancelled"
                return message

            async def observed_send(message):
                nonlocal status, complete, sse, tail
                if message["type"] == "http.response.start":
                    status = message["status"]
                    outgoing = [(k, v) for k, v in message.get("headers", [])
                                if k.lower() != b"x-request-id"]
                    sse = any(k.lower() == b"content-type" and b"text/event-stream" in v
                              for k, v in outgoing)
                    outgoing.append((b"x-request-id", trace.request_id.encode("ascii")))
                    message = {**message, "headers": outgoing}
                await send(message)
                if message["type"] == "http.response.body":
                    body = tail + message.get("body", b"")
                    if sse and trace.first_answer_s is None and b"event: token\n" in body:
                        trace.first_answer_s = time.perf_counter() - trace.started
                    tail = body[-32:]
                    if not message.get("more_body", False):
                        complete = True

            try:
                await self.app(scope, observed_receive, observed_send)
            finally:
                if trace.outcome == "ok":
                    if status >= 400:
                        trace.outcome = "error"
                    elif not complete:
                        trace.outcome = "cancelled"
                # Route template only: never log query strings or user resource IDs.
                route = getattr(scope.get("route"), "path", None)
                trace.route = route
                trace.status_code = status
                emit({"event": "http_response", "request_id": trace.request_id,
                      "route": route, "status_code": status, "complete": complete})


async def observe_stream(generator, *, provider: str, model: str, usage: dict | None = None):
    """Time content deltas, not SSE envelopes. Missing token usage stays missing."""
    from contextlib import aclosing

    with span("llm.attempt", provider=provider, model=model, streaming=True,
              ttft_s=None, queue_wait_s=None) as record:
        started = time.perf_counter()
        first = last = None
        chunks = 0
        try:
            async with aclosing(generator):
                async for text in generator:
                    if text:
                        last = time.perf_counter()
                        if first is None:
                            first = last
                            record["ttft_s"] = first - started
                        chunks += 1
                        yield text
        finally:
            record["content_chunks"] = chunks
            record["content_duration_s"] = last - first if first is not None else None
            record_usage(usage, (usage or {}).get("finish_reason"))
            # Chunks need not align with tokens. Do not claim exact decode throughput.
            tokens = (usage or {}).get("completion_tokens")
            record["decode_tokens_per_second_estimate"] = (
                (tokens - 1) / (last - first)
                if type(tokens) is int and tokens > 1 and first is not None and last > first
                else None
            )


def traced_generation(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        context = nullcontext() if _trace.get() else request_trace(transport="internal")
        with context, span("llm.call"):
            return await fn(*args, **kwargs)
    return wrapped


def traced_stream_call(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        context = nullcontext() if _trace.get() else request_trace(transport="internal")
        with context, span("llm.call"):
            async with aclosing(fn(*args, **kwargs)) as stream:
                async for text in stream:
                    yield text
    return wrapped
