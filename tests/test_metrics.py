import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from app.core import metrics as instrumentation
from app.core import telemetry
from app.core.config import settings


@pytest.fixture
def metrics(monkeypatch):
    instance = instrumentation.Metrics()
    monkeypatch.setattr(instrumentation, "metrics", instance)
    return instance


def sample(metrics, name, labels=None):
    return metrics.registry.get_sample_value(name, labels or {})


def test_model_usage_and_failures_are_separate(metrics):
    with telemetry.request_trace("secret-id", transport="internal"):
        with telemetry.span("llm.attempt", provider="local", model="private-model", ttft_s=.3):
            telemetry.record_usage({"prompt_tokens": 12, "completion_tokens": 4}, "stop")
        with pytest.raises(RuntimeError), telemetry.span("llm.attempt", provider="local"):
            raise RuntimeError("secret message")
    assert sample(metrics, "docchat_llm_tokens_total", {"provider": "local", "direction": "output"}) == 4
    assert sample(metrics, "docchat_llm_ttft_seconds_count", {"provider": "local"}) == 1
    assert sample(metrics, "docchat_llm_missing_usage_total", {"provider": "local"}) == 1
    assert sample(metrics, "docchat_llm_attempts_total", {"provider": "local", "outcome": "error"}) == 1
    text = generate_latest(metrics.registry).decode()
    assert "secret" not in text and "private-model" not in text


@pytest.mark.asyncio
async def test_http_inflight_full_lifecycle_and_bounded_route(metrics):
    entered, release = asyncio.Event(), asyncio.Event()

    async def app(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/api/v1/conversations/{conversation_id}")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        entered.set()
        await release.wait()
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        pass

    task = asyncio.create_task(telemetry.RequestTelemetryMiddleware(app)(
        {"type": "http", "method": "GET", "path": "/api/v1/conversations/private-id"}, None, send))
    await entered.wait()
    assert sample(metrics, "docchat_requests_inflight") == 1
    release.set()
    await task
    assert sample(metrics, "docchat_requests_inflight") == 0
    labels = {"route": "/api/v1/conversations/{conversation_id}", "method": "GET",
              "outcome": "ok", "status_class": "2xx"}
    assert sample(metrics, "docchat_requests_total", labels) == 1
    assert "private-id" not in generate_latest(metrics.registry).decode()


def test_metrics_endpoint_auth_and_no_scrape_self_instrumentation(metrics, monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, "metrics_bearer_token", "private-token")
    client = TestClient(app)
    assert client.get("/api/v1/metrics").status_code == 401
    response = client.get("/api/v1/metrics", headers={"Authorization": "Bearer private-token"})
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert list(text_string_to_metric_families(response.text))
    assert "private-token" not in response.text
    assert sample(metrics, "docchat_requests_inflight") == 0
    assert list(metrics.requests.collect())[0].samples == []


def test_pipeline_signals_and_metrics_failure_are_nonfatal(metrics):
    with telemetry.span("retriever"):
        telemetry.annotate(retrieval_failed=True, retrieved_chunks_count=0)
    with telemetry.span("critic"):
        telemetry.annotate(critic_parse_failed=True, needs_replan=True)
    telemetry.emit({"event": "llm_retry", "provider": "groq"})
    assert sample(metrics, "docchat_retrieval_failures_total") == 1
    assert sample(metrics, "docchat_empty_retrieval_total") == 1
    assert sample(metrics, "docchat_critic_parse_failures_total") == 1
    assert sample(metrics, "docchat_replans_total") == 1
    assert sample(metrics, "docchat_llm_retries_total", {"provider": "groq"}) == 1
    with patch.object(metrics, "observe", side_effect=RuntimeError("export unavailable")):
        with telemetry.span("critic"):
            pass
