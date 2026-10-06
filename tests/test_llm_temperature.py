"""Temperature threading through the provider seam.

The classification nodes need a pinned temperature so a verdict does not move between
identical runs — at N=5 a single flip moved benchmark precision ~8 points. But pinning
must be opt-in: every existing caller has to keep sampling at the provider default, or
this becomes a silent behaviour change to the synthesizer's prose.

No network. Vendor clients are faked; these assert what gets sent, not what comes back.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.services import llm


@pytest.fixture(autouse=True)
def _reset_client_cache():
    llm._clients.clear()
    llm._TEMPERATURE_UNSUPPORTED.clear()
    yield
    llm._clients.clear()
    llm._TEMPERATURE_UNSUPPORTED.clear()


def _groq_client():
    resp = MagicMock()
    resp.choices[0].message.content = "ok"
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


def _openai_client(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {"choices": [{"message": {"content": "ok"}}]}
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    return client


# ---------------------------------------------------------------------------
# Opt-in
# ---------------------------------------------------------------------------

def test_temperature_kwargs_omits_the_key_entirely_when_unset():
    """Not "temperature": None — the key must be absent, or providers see an explicit
    null and some reject it."""
    assert llm._temperature_kwargs(None) == {}
    assert llm._temperature_kwargs(0) == {"temperature": 0}
    assert llm._temperature_kwargs(0.7) == {"temperature": 0.7}


@pytest.mark.asyncio
async def test_openai_reasoning_effort_is_opt_in(monkeypatch):
    client = _openai_client()
    monkeypatch.setattr(settings, "openai_reasoning_effort", "")
    await llm._openai_complete(client, [{"role": "user", "content": "verdict"}], 150)
    assert "reasoning_effort" not in client.post.call_args.kwargs["json"]
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    monkeypatch.setattr(settings, "openai_chat_model", "gpt-5.5")
    await llm._openai_complete(client, [{"role": "user", "content": "verdict"}], 150, temperature=0)
    payload = client.post.call_args.kwargs["json"]
    assert payload["reasoning_effort"] == "none"
    assert payload["model"] == "gpt-5.5"
    assert payload["max_completion_tokens"] == 150


@pytest.mark.asyncio
async def test_default_call_sends_no_temperature(monkeypatch):
    """Existing callers must keep the provider default. This is the regression guard
    against pinning leaking into the synthesizer."""
    monkeypatch.setattr(settings, "llm_provider", "groq")
    client = _groq_client()

    with patch.object(llm, "_build_client", return_value=client):
        await llm.chat_complete([{"role": "user", "content": "hi"}])

    assert "temperature" not in client.chat.completions.create.call_args.kwargs


@pytest.mark.asyncio
async def test_explicit_temperature_reaches_groq(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    client = _groq_client()

    with patch.object(llm, "_build_client", return_value=client):
        await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)

    assert client.chat.completions.create.call_args.kwargs["temperature"] == 0


@pytest.mark.asyncio
async def test_explicit_temperature_reaches_openai(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    client = _openai_client()

    with patch.object(llm, "_build_client", return_value=client):
        await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)

    assert client.post.call_args.kwargs["json"]["temperature"] == 0


@pytest.mark.asyncio
async def test_explicit_temperature_reaches_mistral(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    resp = MagicMock()
    resp.choices[0].message.content = "ok"
    client = AsyncMock()
    client.chat.complete_async = AsyncMock(return_value=resp)

    with patch.object(llm, "_build_client", return_value=client):
        await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)

    assert client.chat.complete_async.call_args.kwargs["temperature"] == 0


# ---------------------------------------------------------------------------
# Reasoning models reject non-default temperature
# ---------------------------------------------------------------------------

_TEMP_400 = {"error": {"message": "Unsupported value: 'temperature' does not support 0."}}


@pytest.mark.asyncio
async def test_openai_400_on_temperature_retries_without_it(monkeypatch):
    """Determinism is a nice-to-have. Failing the user's request over it is not."""
    monkeypatch.setattr(settings, "llm_provider", "openai")

    rejected = MagicMock(status_code=400)
    rejected.json.return_value = _TEMP_400
    accepted = MagicMock(status_code=200)
    accepted.json.return_value = {"choices": [{"message": {"content": "recovered"}}]}

    client = AsyncMock()
    client.post = AsyncMock(side_effect=[rejected, accepted])

    with patch.object(llm, "_build_client", return_value=client):
        result = await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)

    assert result == "recovered"
    assert client.post.await_count == 2
    assert "temperature" not in client.post.call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_rejection_is_remembered_so_the_400_is_paid_once(monkeypatch):
    """gpt-5.6-luna rejects temperature on every call. Without this the retry doubles
    the request count of every critic and planner call for the life of the process."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_chat_model", "gpt-5.6-luna")

    rejected = MagicMock(status_code=400)
    rejected.json.return_value = _TEMP_400
    accepted = MagicMock(status_code=200)
    accepted.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    client = AsyncMock()
    client.post = AsyncMock(side_effect=[rejected, accepted, accepted])

    with patch.object(llm, "_build_client", return_value=client):
        await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)
        assert client.post.await_count == 2       # first call pays the 400

        await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)
        assert client.post.await_count == 3       # second goes straight through

    assert "temperature" not in client.post.call_args.kwargs["json"]
    assert "gpt-5.6-luna" in llm._TEMPERATURE_UNSUPPORTED


@pytest.mark.asyncio
async def test_unrelated_400_is_not_retried(monkeypatch):
    """Retrying a 400 we have not understood burns a request to get the same error."""
    monkeypatch.setattr(settings, "llm_provider", "openai")

    resp = MagicMock(status_code=400)
    resp.json.return_value = {"error": {"message": "context_length_exceeded"}}
    resp.raise_for_status.side_effect = RuntimeError("400")

    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)

    with patch.object(llm, "_build_client", return_value=client):
        with pytest.raises(RuntimeError):
            await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)

    assert client.post.await_count == 1


@pytest.mark.asyncio
async def test_malformed_error_body_does_not_trigger_a_retry(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")

    resp = MagicMock(status_code=400)
    resp.json.side_effect = ValueError("not json")
    resp.raise_for_status.side_effect = RuntimeError("400")

    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)

    with patch.object(llm, "_build_client", return_value=client):
        with pytest.raises(RuntimeError):
            await llm.chat_complete([{"role": "user", "content": "hi"}], temperature=0)

    assert client.post.await_count == 1


# ---------------------------------------------------------------------------
# Call sites
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_critic_pins_temperature():
    from app.agent.nodes.critic import critic_node

    captured = {}

    async def fake(messages, max_tokens=150, temperature=None):
        captured["temperature"] = temperature
        return '{"quality": "good", "feedback": ""}'

    state = {
        "query": "q", "answer": "a", "iteration": 0, "conversation_id": "c",
        "conversation_history": [], "sources_to_use": [], "source_ids": [],
        "retrieved_chunks": [], "critic_feedback": "", "needs_replan": False,
        "grounding_passed": False, "pending_rejection": None,
    }
    with patch("app.agent.nodes.critic.chat_complete", new=fake):
        await critic_node(state)

    assert captured["temperature"] == settings.classification_temperature == 0.0


@pytest.mark.asyncio
async def test_synthesizer_is_left_sampling():
    """Determinism buys nothing for prose and costs variety — this must NOT be pinned."""
    from app.agent.nodes.synthesizer import synthesizer_node

    captured = {}

    async def fake(messages, max_tokens=1400, temperature=None):
        captured["temperature"] = temperature
        return "an answer"

    state = {
        "query": "q", "answer": "", "iteration": 0, "conversation_id": "c",
        "conversation_history": [], "sources_to_use": ["pdf"], "source_ids": [],
        "retrieved_chunks": [{"text": "t", "metadata": {}, "source_type": "pdf", "score": 0.9}],
        "critic_feedback": "", "needs_replan": False, "grounding_passed": False,
        "pending_rejection": None,
    }
    with patch("app.agent.nodes.synthesizer.chat_complete", new=fake):
        await synthesizer_node(state)

    assert captured["temperature"] is None
