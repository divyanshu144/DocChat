"""Offline contract tests exercising real HTTPX transport and cancellation."""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core import telemetry
from app.services import llm
from app.services.inference.openai_compatible import OpenAICompatibleBackend, InvalidInferenceResponse
from app.services.inference.types import GenerationRequest


@pytest.fixture
def records(monkeypatch):
    rows = []
    monkeypatch.setattr(telemetry, "emit", lambda row: rows.append(dict(row)))
    return rows


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "local")
    monkeypatch.setattr(settings, "local_base_url", "http://inference.test/v1")
    monkeypatch.setattr(settings, "local_chat_model", "test-model")
    monkeypatch.setattr(settings, "local_api_key", "")


@pytest.mark.asyncio
async def test_completion_contract_usage_identity_and_no_prompt_logging(local, records):
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["x-request-id"] == "request-1"
        assert json.loads(request.content)["temperature"] == 0
        return httpx.Response(200, json={"id": "backend-1", "choices": [
            {"message": {"content": "answer-secret"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 2}})
    async with httpx.AsyncClient(base_url=settings.local_base_url,
                                 transport=httpx.MockTransport(handler)) as client:
        with patch.object(llm, "_get_client", return_value=client), telemetry.request_trace("request-1"):
            assert await llm.chat_complete([{"role": "user", "content": "prompt-secret"}],
                                           temperature=0) == "answer-secret"
    attempt = next(r for r in records if r.get("name") == "llm.attempt")
    assert attempt["completion_tokens"] == 2
    assert attempt["backend_request_id"] == "backend-1"
    assert attempt["ttft_s"] is None
    assert attempt["queue_wait_s"] is None
    assert attempt["attempt_index"] == 1
    assert attempt["parent_span_id"]
    assert "secret" not in json.dumps(records)


@pytest.mark.asyncio
async def test_local_stream_usage_only_tail_and_timing(local, records):
    clock = [0.0]

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for at, data in [(1, {"choices": [{"delta": {"role": "assistant"}}]}),
                             (2, {"choices": [{"delta": {"content": "hello "}}]}),
                             (4, {"choices": [{"delta": {"content": "world"},
                                                "finish_reason": "stop"}]}),
                             (8, {"choices": [], "usage": {"completion_tokens": 5}})]:
                clock[0] = at
                yield f"data: {json.dumps(data)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    async with httpx.AsyncClient(base_url=settings.local_base_url, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, stream=Body())
    )) as client:
        with patch.object(llm, "_get_client", return_value=client), \
             patch.object(telemetry.time, "perf_counter", side_effect=lambda: clock[0]):
            sink = {}
            assert [x async for x in llm.chat_stream([], usage_sink=sink)] == ["hello ", "world"]
    attempt = next(r for r in records if r.get("name") == "llm.attempt")
    assert attempt["ttft_s"] == 2
    assert attempt["duration_s"] == 8
    assert attempt["content_duration_s"] == 2
    assert attempt["decode_tokens_per_second_estimate"] == 2
    assert sink == {"completion_tokens": 5, "finish_reason": "stop"}
    assert telemetry.request_id() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
    b'data: not-json\n\n',
    b'data: {"error":{"message":"private detail"}}\n\n',
])
async def test_local_stream_rejects_invalid_or_incomplete_response(body, local, records):
    async with httpx.AsyncClient(base_url=settings.local_base_url, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=body)
    )) as client:
        with patch.object(llm, "_get_client", return_value=client), pytest.raises(ValueError):
            _ = [x async for x in llm.chat_stream([])]
    assert any(r.get("name") == "llm.attempt" and r["outcome"] == "error" for r in records)
    assert "private detail" not in json.dumps(records)


@pytest.mark.asyncio
async def test_missing_usage_is_unknown_not_chunk_count(local, records):
    body = b'data: {"choices":[{"delta":{"content":"many words here"}}]}\n\ndata: [DONE]\n\n'
    async with httpx.AsyncClient(base_url=settings.local_base_url, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=body)
    )) as client:
        with patch.object(llm, "_get_client", return_value=client):
            assert [x async for x in llm.chat_stream([])] == ["many words here"]
    attempt = next(r for r in records if r.get("name") == "llm.attempt")
    assert "completion_tokens" not in attempt
    assert attempt["decode_tokens_per_second_estimate"] is None


@pytest.mark.asyncio
async def test_cancelled_stream_closes_transport(local, records):
    entered = asyncio.Event()
    closed = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            entered.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async with httpx.AsyncClient(base_url=settings.local_base_url, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, stream=Body())
    )) as client:
        with patch.object(llm, "_get_client", return_value=client):
            async def consume():
                return [x async for x in llm.chat_stream([])]
            task = asyncio.create_task(consume())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert closed.is_set()
    assert any(r.get("name") == "llm.attempt" and r["outcome"] == "cancelled" for r in records)


@pytest.mark.asyncio
async def test_client_configuration_change_and_shutdown(local, monkeypatch):
    first = llm._get_client()
    assert first is llm._get_client()
    monkeypatch.setattr(settings, "local_base_url", "http://other.test/v1")
    second = llm._get_client()
    monkeypatch.setattr(settings, "local_api_key", "different-key")
    third = llm._get_client()
    assert len({id(first), id(second), id(third)}) == 3
    assert not first.is_closed  # no teardown under an in-flight caller
    await llm.close_llm_clients()
    assert all(client.is_closed for client in (first, second, third))
    assert not llm._clients


def test_client_is_owned_by_event_loop(local):
    async def use():
        client = llm._get_client()
        await llm.close_llm_clients()
        return client
    first = asyncio.run(use())
    second = asyncio.run(use())
    assert first is not second
    assert first.is_closed and second.is_closed


@pytest.mark.parametrize("url", ["", "file:///tmp/model", "http://user:secret@host/v1", "http://host/v1?key=x"])
def test_invalid_endpoint_rejected_without_echoing_secrets(local, monkeypatch, url):
    monkeypatch.setattr(settings, "local_base_url", url)
    with pytest.raises(ValueError, match="LOCAL_BASE_URL") as exc:
        llm._build_client("local")
    assert "secret" not in str(exc.value)


def test_model_and_timeout_validation():
    with pytest.raises(ValueError, match="LOCAL_CHAT_MODEL"):
        GenerationRequest(" ", [])
    with pytest.raises(ValueError):
        Settings(_env_file=None, inference_read_timeout_s=0)


@pytest.mark.asyncio
async def test_backend_rejects_missing_completion(local):
    async with httpx.AsyncClient(base_url=settings.local_base_url, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"choices": []})
    )) as client:
        with pytest.raises(InvalidInferenceResponse):
            await OpenAICompatibleBackend(client).complete(GenerationRequest("model", []))


@pytest.mark.parametrize("models,code", [([{"id": "test-model"}], 200), ([], 503)])
def test_serving_readiness_checks_model_without_generation(local, models, code):
    from app.main import app
    client = AsyncMock()
    client.get.return_value = httpx.Response(200, json={"data": models},
                                            request=httpx.Request("GET", "http://host/v1/models"))
    with patch.object(llm, "_get_client", return_value=client):
        response = TestClient(app).get("/api/v1/health/serving")
    assert response.status_code == code
    client.get.assert_awaited_once_with("/models", timeout=3.0)
    client.post.assert_not_called()


def test_hosted_readiness_does_not_require_gpu(monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, "llm_provider", "groq")
    with patch.object(llm, "_get_client") as client:
        response = TestClient(app).get("/api/v1/health/serving")
    assert response.json() == {"status": "not_applicable", "provider": "groq"}
    client.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_is_recorded_and_not_retried_on_local(local, records):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private URL", request=request)

    async with httpx.AsyncClient(base_url=settings.local_base_url,
                                 transport=httpx.MockTransport(handler)) as client:
        with patch.object(llm, "_get_client", return_value=client), pytest.raises(httpx.ReadTimeout):
            await llm.chat_complete([])
    assert len(calls) == 1
    assert any(r.get("error_type") == "ReadTimeout" for r in records)
    assert "private URL" not in str(records)


@pytest.mark.asyncio
async def test_fallback_records_actual_provider_and_separate_attempts(monkeypatch, records):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_fallback_chat_model", "")
    monkeypatch.setattr(settings, "fallback_llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    groq = AsyncMock()
    groq.chat.completions.create.side_effect = RuntimeError("503 unavailable")
    response = {"choices": [{"message": {"content": "fallback"}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 1}}
    async with httpx.AsyncClient(base_url="http://fallback.test/v1", transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=response)
    )) as client:
        with patch.object(llm, "_get_client", return_value=groq), \
             patch.object(llm, "_build_client", return_value=client):
            assert await llm.chat_complete([]) == "fallback"
    attempts = [r for r in records if r.get("name") == "llm.attempt"]
    assert [(r["provider"], r["outcome"], r["attempt_index"]) for r in attempts] == [
        ("groq", "error", 1), ("openai", "ok", 2)]
    assert len({r["request_id"] for r in attempts}) == 1


@pytest.mark.asyncio
async def test_no_fallback_after_partial_stream(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "fallback_llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test")

    async def partial(*args):
        yield "partial"
        raise RuntimeError("503 failed mid-stream")

    with patch.object(llm, "_get_client", return_value=object()), \
         patch.object(llm, "_groq_stream", partial), \
         patch.object(llm, "_openai_stream_with_temporary_client") as fallback:
        with pytest.raises(RuntimeError):
            _ = [x async for x in llm.chat_stream([])]
    fallback.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_closes_mistral_context_clients_and_other_clients(local):
    events = []

    class ContextClient:
        async def __aexit__(self, *args):
            events.append("async")

        def __exit__(self, *args):
            events.append("sync")

    llm._clients[(asyncio.get_running_loop(), "mistral")] = ContextClient()
    client = llm._get_client()
    await llm.close_llm_clients()
    assert events == ["async", "sync"]
    assert client.is_closed


@pytest.mark.asyncio
async def test_buffered_completion_preserves_temperature_and_return_type(local, records, monkeypatch):
    monkeypatch.setattr(settings, "local_stream_completions", True)

    def handler(request):
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["temperature"] == 0
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(200, content=(
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}]}\n\n'
            b'data: [DONE]\n\n'))

    async with httpx.AsyncClient(base_url=settings.local_base_url,
                                 transport=httpx.MockTransport(handler)) as client:
        with patch.object(llm, "_get_client", return_value=client):
            assert await llm.chat_complete([], temperature=0) == "hello world"
    attempt = next(r for r in records if r.get("name") == "llm.attempt")
    assert attempt["streaming"] is True
    assert attempt["ttft_s"] is not None
