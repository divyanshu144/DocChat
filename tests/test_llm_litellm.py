"""Tests for the opt-in LiteLLM backend (app/services/llm_litellm.py).

Most tests use a fake `litellm` module so they run with or without the package and never touch a network. The last
group runs the real package against a loopback mock server and is skipped when `litellm` is not installed.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.services import llm, llm_litellm as ll

MESSAGES = [{"role": "user", "content": "hi"}]


class StatusError(Exception):
    def __init__(self, status_code, message="boom"):
        super().__init__(message)
        self.status_code = status_code


def response(text="ok", *, usage=(3, 2), finish="stop", rid="r1"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]), id=rid)


def chunk(text=None, *, finish=None, usage=None):
    choices = [SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish)] if (text or finish) else []
    return SimpleNamespace(
        choices=choices, usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None)


class FakeStream:
    """An async iterator of chunks that can fail after some of them have been delivered."""
    def __init__(self, items, then=None):
        self.items, self.then, self.closed = list(items), then, False

    def __aiter__(self):
        return self._run()

    async def _run(self):
        for item in self.items:
            yield item
        if self.then:
            raise self.then

    async def aclose(self):
        self.closed = True


class FakeRouter:
    script: dict = {}
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs, self.calls = kwargs, []
        FakeRouter.instances.append(self)

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        outcome = FakeRouter.script[kwargs["model"]].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def litellm_backend(monkeypatch):
    FakeRouter.script, FakeRouter.instances = {}, []
    ll._ROUTERS.clear()
    monkeypatch.setattr(ll, "_litellm", lambda: SimpleNamespace(Router=FakeRouter))
    for name, value in dict(llm_backend="litellm", llm_provider="groq", fallback_llm_provider="openai",
                            groq_api_key="gk", openai_api_key="ok", mistral_api_key="mk", local_api_key="",
                            groq_fallback_chat_model="", chat_model="groq-main", openai_chat_model="oa-main",
                            mistral_chat_model="mi-main", local_chat_model="loc-main",
                            local_base_url="http://127.0.0.1:9/v1", openai_reasoning_effort="").items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(llm, "_TEMPERATURE_UNSUPPORTED", set())
    events = []
    monkeypatch.setattr(ll, "emit", events.append)
    yield events
    ll._ROUTERS.clear()


def router():
    assert len(FakeRouter.instances) == 1
    return FakeRouter.instances[0]


async def collect(**kwargs):
    return [token async for token in llm.chat_stream(MESSAGES, max_tokens=50, **kwargs)]


# ---------------- selection and defaults ----------------
def test_loading_litellm_holds_its_loggers_at_warning(monkeypatch):
    import logging
    monkeypatch.undo()
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(Router=FakeRouter))
    for name in ll._LITELLM_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)
    ll._litellm()
    assert all(logging.getLogger(n).level == logging.WARNING for n in ll._LITELLM_LOGGERS)


def test_the_default_backend_is_native():
    from app.core.config import Settings
    assert Settings.model_fields["llm_backend"].default == "native"


async def test_native_backend_never_touches_the_litellm_module(monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "native")
    boom = MagicMock(side_effect=AssertionError("litellm was used"))
    monkeypatch.setattr(ll, "complete", boom)
    monkeypatch.setattr(ll, "stream", boom)
    client = MagicMock()
    client.chat.completions.create = MagicMock(side_effect=RuntimeError("native client reached"))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    with pytest.raises(RuntimeError, match="native client reached"):
        await llm.chat_complete(MESSAGES)
    boom.assert_not_called()


async def test_missing_package_gives_a_clear_error(monkeypatch):
    monkeypatch.undo()  # drop the fake loader from the fixture
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(RuntimeError, match="requirements-litellm.txt"):
        ll._litellm()


# ---------------- completion ----------------
async def test_completion_goes_through_the_router_and_returns_text():
    FakeRouter.script = {"groq-0": [response("hello")]}
    assert await llm.chat_complete(MESSAGES, max_tokens=77) == "hello"
    call = router().calls[0]
    assert call["model"] == "groq-0" and call["max_tokens"] == 77 and call["messages"] == MESSAGES
    assert "temperature" not in call  # unset temperature stays the provider default


async def test_router_has_no_automatic_fallbacks_retries_or_cooldowns():
    FakeRouter.script = {"groq-0": [response()]}
    await llm.chat_complete(MESSAGES)
    kwargs = router().kwargs
    assert kwargs["num_retries"] == 0 and kwargs["disable_cooldowns"] is True and "fallbacks" not in kwargs


async def test_keys_and_urls_come_from_settings_only(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "local")
    monkeypatch.setattr(settings, "local_api_key", "")
    FakeRouter.script = {"local": [response()]}
    await llm.chat_complete(MESSAGES)
    params = router().kwargs["model_list"][0]["litellm_params"]
    assert params["api_base"] == "http://127.0.0.1:9/v1" and params["model"] == "openai/loc-main"
    assert params["api_key"] == "none"  # a placeholder, so LiteLLM never goes looking in the environment


async def test_a_blank_key_is_refused_instead_of_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from-environment")
    monkeypatch.setattr(settings, "groq_api_key", "")
    with pytest.raises(ValueError, match="No API key configured for groq"):
        await llm.chat_complete(MESSAGES)
    assert not FakeRouter.instances


async def test_openai_uses_max_completion_tokens_and_reasoning_effort(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "fallback_llm_provider", "none")
    monkeypatch.setattr(settings, "openai_reasoning_effort", "low")
    FakeRouter.script = {"openai": [response()]}
    await llm.chat_complete(MESSAGES, max_tokens=64)
    call = router().calls[0]
    assert call["max_completion_tokens"] == 64 and "max_tokens" not in call and call["reasoning_effort"] == "low"


async def test_usage_finish_reason_and_request_id_are_recorded(monkeypatch):
    seen = []
    monkeypatch.setattr(ll, "record_usage", lambda usage, finish, rid: seen.append((usage, finish, rid)))
    FakeRouter.script = {"groq-0": [response(usage=(11, 5), finish="length", rid="req-9")]}
    await llm.chat_complete(MESSAGES)
    usage, finish, rid = seen[0]
    assert (usage.prompt_tokens, usage.completion_tokens, finish, rid) == (11, 5, "length", "req-9")


async def test_each_attempt_is_a_span(monkeypatch):
    spans = []
    real = ll.span
    monkeypatch.setattr(ll, "span", lambda name, **f: (spans.append((name, f)), real(name, **f))[1])
    FakeRouter.script = {"groq-0": [response()]}
    await llm.chat_complete(MESSAGES)
    assert spans == [("llm.attempt", {"provider": "groq", "model": "groq-main", "streaming": False,
                                       "ttft_s": None, "queue_wait_s": None})]


# ---------------- fallback chain ----------------
def test_chain_table(monkeypatch):
    assert ll.chain("groq") == ["groq-0", "openai"]
    monkeypatch.setattr(settings, "groq_fallback_chat_model", "groq-backup")
    assert ll.chain("groq") == ["groq-0", "groq-1", "openai"]
    assert ll.chain("openai") == ["openai"]  # fallback_llm_provider is openai, equal to the primary
    monkeypatch.setattr(settings, "fallback_llm_provider", "groq")
    assert ll.chain("openai") == ["openai", "groq-0", "groq-1"]
    assert ll.chain("groq") == ["groq-0", "groq-1"]
    assert ll.chain("mistral") == ["mistral"] and ll.chain("local") == ["local"]
    monkeypatch.setattr(settings, "fallback_llm_provider", "none")
    assert ll.chain("openai") == ["openai"] and ll.chain("groq") == ["groq-0", "groq-1"]


def test_no_fallback_without_the_fallback_providers_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert ll.chain("groq") == ["groq-0"]


@pytest.mark.parametrize("primary", ["groq", "mistral", "openai", "local"])
@pytest.mark.parametrize("fallback", ["none", "openai", "groq"])
def test_local_is_never_a_fallback_target(monkeypatch, primary, fallback):
    monkeypatch.setattr(settings, "fallback_llm_provider", fallback)
    monkeypatch.setattr(settings, "groq_fallback_chat_model", "groq-backup")
    deployments = ll.chain(primary)
    assert deployments[0] == primary or deployments[0].startswith(primary)
    assert "local" not in deployments[1:] and "mistral" not in deployments[1:]


def test_unknown_provider_has_the_same_error_as_native(monkeypatch):
    with pytest.raises(ValueError, match="Unknown llm_provider 'nope'"):
        ll.chain("nope")


async def test_retryable_error_falls_through_the_whole_chain(monkeypatch, litellm_backend):
    monkeypatch.setattr(settings, "groq_fallback_chat_model", "groq-backup")
    FakeRouter.script = {"groq-0": [StatusError(429)], "groq-1": [StatusError(503)], "openai": [response("last resort")]}
    assert await llm.chat_complete(MESSAGES) == "last resort"
    assert [c["model"] for c in router().calls] == ["groq-0", "groq-1", "openai"]
    assert litellm_backend == [{"event": "llm_retry", "provider": "groq"}] * 2


async def test_non_retryable_error_does_not_fall_back():
    FakeRouter.script = {"groq-0": [StatusError(400, "bad request")], "openai": [response()]}
    with pytest.raises(StatusError):
        await llm.chat_complete(MESSAGES)
    assert [c["model"] for c in router().calls] == ["groq-0"]


async def test_authentication_errors_do_not_fall_back():
    FakeRouter.script = {"groq-0": [StatusError(401, "invalid key")], "openai": [response()]}
    with pytest.raises(StatusError):
        await llm.chat_complete(MESSAGES)
    assert [c["model"] for c in router().calls] == ["groq-0"]


async def test_the_last_deployments_error_is_raised():
    FakeRouter.script = {"groq-0": [StatusError(429)], "openai": [StatusError(503, "still down")]}
    with pytest.raises(StatusError, match="still down"):
        await llm.chat_complete(MESSAGES)


async def test_openai_falls_back_to_groq_but_never_to_local(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "fallback_llm_provider", "groq")
    FakeRouter.script = {"openai": [StatusError(500)], "groq-0": [response("groq answered")]}
    assert await llm.chat_complete(MESSAGES) == "groq answered"
    assert "local" not in [c["model"] for c in router().calls]


async def test_local_failure_is_raised_without_any_fallback(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "local")
    FakeRouter.script = {"local": [StatusError(503, "gpu is off")], "openai": [response()], "groq-0": [response()]}
    with pytest.raises(StatusError, match="gpu is off"):
        await llm.chat_complete(MESSAGES)
    assert [c["model"] for c in router().calls] == ["local"]


# ---------------- temperature ----------------
async def test_temperature_is_sent_when_asked_for():
    FakeRouter.script = {"groq-0": [response()]}
    await llm.chat_complete(MESSAGES, temperature=0)
    assert router().calls[0]["temperature"] == 0


async def test_openai_temperature_rejection_is_dropped_remembered_and_recorded(monkeypatch, litellm_backend):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "fallback_llm_provider", "none")
    FakeRouter.script = {"openai": [StatusError(400, "Unsupported value: 'temperature' does not support 0"),
                                    response("fine"), response("second call")]}
    assert await llm.chat_complete(MESSAGES, temperature=0) == "fine"
    first, retry = router().calls
    assert first["temperature"] == 0 and "temperature" not in retry
    assert "oa-main" in llm._TEMPERATURE_UNSUPPORTED
    assert {"event": "llm_retry", "provider": "openai"} in litellm_backend
    await llm.chat_complete(MESSAGES, temperature=0)  # remembered: goes straight to the working shape
    assert "temperature" not in router().calls[2] and len(router().calls) == 3


async def test_an_unrelated_openai_400_is_not_retried(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "fallback_llm_provider", "none")
    FakeRouter.script = {"openai": [StatusError(400, "context length exceeded")]}
    with pytest.raises(StatusError):
        await llm.chat_complete(MESSAGES, temperature=0)
    assert len(router().calls) == 1 and not llm._TEMPERATURE_UNSUPPORTED


# ---------------- streaming ----------------
async def test_stream_yields_text_and_fills_the_usage_sink():
    FakeRouter.script = {"groq-0": [FakeStream([chunk("a"), chunk("b"), chunk(finish="stop"), chunk(usage=(7, 2))])]}
    sink = {}
    assert await collect(usage_sink=sink) == ["a", "b"]
    assert sink == {"prompt_tokens": 7, "completion_tokens": 2, "finish_reason": "stop"}
    call = router().calls[0]
    assert call["stream"] is True and call["stream_options"] == {"include_usage": True}


async def test_stream_works_without_a_sink():
    FakeRouter.script = {"groq-0": [FakeStream([chunk("x")])]}
    assert await collect() == ["x"]


async def test_stream_falls_back_before_the_first_token_and_clears_the_sink():
    FakeRouter.script = {"groq-0": [StatusError(503)], "openai": [FakeStream([chunk("from openai"), chunk(usage=(1, 1))])]}
    sink = {"prompt_tokens": 999}
    assert await collect(usage_sink=sink) == ["from openai"]
    assert sink == {"prompt_tokens": 1, "completion_tokens": 1}


async def test_stream_never_falls_back_after_the_first_token():
    FakeRouter.script = {"groq-0": [FakeStream([chunk("a"), chunk("b")], then=StatusError(503))],
                         "openai": [FakeStream([chunk("SPLICED")])]}
    got = []
    with pytest.raises(StatusError):
        async for token in llm.chat_stream(MESSAGES, max_tokens=5):
            got.append(token)
    assert got == ["a", "b"]
    assert [c["model"] for c in router().calls] == ["groq-0"]


async def test_stream_does_not_fall_back_on_a_non_retryable_error():
    FakeRouter.script = {"groq-0": [StatusError(400)], "openai": [FakeStream([chunk("x")])]}
    with pytest.raises(StatusError):
        await collect()
    assert [c["model"] for c in router().calls] == ["groq-0"]


async def test_stream_closes_the_provider_stream_on_early_exit():
    provider_stream = FakeStream([chunk("a"), chunk("b"), chunk("c")])
    FakeRouter.script = {"groq-0": [provider_stream]}
    agen = ll.stream(MESSAGES, 5)  # the backend itself; the public wrapper adds request-scoped context vars
    assert await agen.__anext__() == "a"
    await agen.aclose()
    assert provider_stream.closed


# ---------------- the real package against a loopback server ----------------
class _Mock(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body["model"]
        self.server.hits.append(model)
        if model.startswith("e"):
            data = json.dumps({"error": {"message": f"boom {model}", "type": "x"}}).encode()
            self.send_response(int(model[1:]))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for index, text in enumerate(["a", "b", "c"]):
                if model == "midfail" and index == 2:
                    self.wfile.write(b'data: {"error": {"message": "overloaded", "type": "overloaded_error", "code": 503}}\n\n')
                    return
                self.wfile.write(("data: " + json.dumps({"id": "c", "object": "chat.completion.chunk", "model": model,
                                                         "choices": [{"index": 0, "delta": {"content": text}}]}) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        data = json.dumps({"id": "r", "object": "chat.completion", "model": model, "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "from-" + model}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def real_litellm(monkeypatch):
    pytest.importorskip("litellm")
    monkeypatch.undo()  # drop the fake loader; the autouse fixture's settings are re-applied below
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Mock)
    server.hits = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    original = ll._deployment_params
    state = {"primary": "ok"}

    def pointed(name):
        params = original(name)
        params["api_base"] = base
        params["model"] = "openai/" + (state["primary"] if name == "groq-0" else "ok")
        return params

    for key, value in dict(llm_backend="litellm", llm_provider="groq", fallback_llm_provider="openai",
                           groq_api_key="gk", openai_api_key="ok", groq_fallback_chat_model="").items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(ll, "_deployment_params", pointed)
    ll._ROUTERS.clear()
    yield server, state
    ll._ROUTERS.clear()
    server.shutdown()


async def test_real_litellm_falls_back_on_503_but_not_on_400_or_401(real_litellm):
    server, state = real_litellm
    for primary, expected_hits, outcome in [("e503", ["e503", "ok"], "from-ok"), ("e429", ["e429", "ok"], "from-ok"),
                                            ("e400", ["e400"], None), ("e401", ["e401"], None)]:
        state["primary"], server.hits[:] = primary, []
        ll._ROUTERS.clear()
        if outcome:
            assert await llm.chat_complete(MESSAGES, max_tokens=5) == outcome
        else:
            with pytest.raises((sys.modules["litellm"].BadRequestError, sys.modules["litellm"].AuthenticationError)) as err:
                await llm.chat_complete(MESSAGES, max_tokens=5)
            assert err.value.status_code == int(primary[1:])
        assert server.hits == expected_hits


async def test_real_litellm_never_logs_prompts_or_urls_even_at_debug(real_litellm, caplog):
    import logging
    server, state = real_litellm
    state["primary"] = "e400"
    secret = "CONFIDENTIAL-PROMPT-TEXT https://private.example/doc"
    ll._litellm()  # what a first real call does; restores the logger levels the fixture just undid
    bad_request = sys.modules["litellm"].BadRequestError
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(bad_request):
            await llm.chat_complete([{"role": "user", "content": secret}], max_tokens=5)
        with pytest.raises(bad_request):
            async for _ in llm.chat_stream([{"role": "user", "content": secret}], max_tokens=5):
                pass
    assert "CONFIDENTIAL-PROMPT-TEXT" not in caplog.text and "private.example" not in caplog.text


async def test_real_litellm_stream_never_splices_a_fallback_after_tokens(real_litellm):
    server, state = real_litellm
    state["primary"] = "midfail"
    got = []
    with pytest.raises(sys.modules["litellm"].exceptions.MidStreamFallbackError):
        async for token in llm.chat_stream(MESSAGES, max_tokens=5):
            got.append(token)
    assert got == ["a", "b"] and server.hits == ["midfail"]  # the fallback model was never called


async def test_real_litellm_stream_falls_back_before_the_first_token(real_litellm):
    server, state = real_litellm
    state["primary"] = "e503"
    assert "".join([t async for t in llm.chat_stream(MESSAGES, max_tokens=5)]) == "abc"
    assert server.hits == ["e503", "ok"]
