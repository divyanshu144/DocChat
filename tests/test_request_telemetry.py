import asyncio
from unittest.mock import patch

import pytest

from app.core import telemetry


@pytest.fixture
def records(monkeypatch):
    rows = []
    monkeypatch.setattr(telemetry, "emit", lambda row: rows.append(dict(row)))
    return rows


@pytest.mark.asyncio
async def test_concurrent_requests_keep_span_parents_and_identity(records):
    entered = asyncio.Event()
    count = 0

    async def run(identifier):
        nonlocal count
        with telemetry.request_trace(identifier), telemetry.span("outer") as outer:
            count += 1
            if count == 2:
                entered.set()
            await entered.wait()
            with telemetry.span("inner") as inner:
                assert inner["request_id"] == identifier
                assert inner["parent_span_id"] == outer["span_id"]
        assert telemetry.request_id() is None

    await asyncio.gather(run("a"), run("b"))
    assert {r["request_id"] for r in records} == {"a", "b"}
    assert len([r for r in records if r["event"] == "request"]) == 2


@pytest.mark.asyncio
async def test_http_clock_includes_stream_delivery_and_ignores_status_events(records):
    clock = [0.0]
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        clock[0] = 1
        await send({"type": "http.response.body", "body": b"event: status\ndata: working\n\n",
                    "more_body": True})
        clock[0] = 3
        await send({"type": "http.response.body", "body": b"event: tok", "more_body": True})
        clock[0] = 5
        await send({"type": "http.response.body", "body": b"en\ndata: hi\n\n", "more_body": True})
        clock[0] = 8
        await send({"type": "http.response.body", "body": b"event: done\ndata: done\n\n"})

    async def send(message):
        sent.append(message)

    with patch.object(telemetry.time, "perf_counter", side_effect=lambda: clock[0]):
        await telemetry.RequestTelemetryMiddleware(app)(
            {"type": "http", "method": "POST", "headers": [(b"x-request-id", b"known-id")]},
            None, send)
    request = next(r for r in records if r["event"] == "request")
    assert request["duration_s"] == 8
    assert request["first_answer_s"] == 5
    assert request["outcome"] == "ok"
    assert (b"x-request-id", b"known-id") in sent[0]["headers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("sse_error", "error"), ("disconnect", "cancelled"),
                                           ("exception", "error")])
async def test_http_records_failures_after_success_headers(records, mode, expected):
    async def send(message):
        pass

    async def receive():
        return {"type": "http.disconnect"}

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        if mode == "sse_error":
            telemetry.mark_error()
            await send({"type": "http.response.body", "body": b""})
        elif mode == "disconnect":
            await receive()
        else:
            raise RuntimeError("private failure")

    middleware = telemetry.RequestTelemetryMiddleware(app)
    if mode == "exception":
        with pytest.raises(RuntimeError):
            await middleware({"type": "http", "method": "POST"}, receive, send)
    else:
        await middleware({"type": "http", "method": "POST"}, receive, send)
    request = next(r for r in records if r["event"] == "request")
    assert request["outcome"] == expected
    assert telemetry.request_id() is None
    assert "private failure" not in str(records)


def test_logging_failure_does_not_fail_request():
    with patch.object(telemetry.logger, "info", side_effect=RuntimeError("logger unavailable")):
        with telemetry.request_trace("safe"), telemetry.span("work"):
            pass
    assert telemetry.request_id() is None
