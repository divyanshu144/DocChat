"""Tests for the provider seam in app/services/llm.py.

No network. Every provider client is faked — these assert dispatch, model
selection and content normalisation, not vendor behaviour.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import llm


@pytest.fixture(autouse=True)
def _reset_client_cache():
    """The module caches a client globally — reset around every test."""
    llm._client = None
    llm._client_provider = None
    yield
    llm._client = None
    llm._client_provider = None


def _groq_client(content="from groq"):
    resp = MagicMock()
    resp.choices[0].message.content = content
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


def _mistral_client(content="from mistral"):
    resp = MagicMock()
    resp.choices[0].message.content = content
    client = AsyncMock()
    client.chat.complete_async = AsyncMock(return_value=resp)
    return client


# --- model selection -------------------------------------------------------

def test_active_model_uses_groq_model_by_default():
    with patch.object(llm.settings, "llm_provider", "groq"), \
         patch.object(llm.settings, "chat_model", "llama-3.3-70b-versatile"):
        assert llm._active_model() == "llama-3.3-70b-versatile"


def test_active_model_uses_mistral_model_when_selected():
    """Switching provider must switch model too — the whole point of separate settings."""
    with patch.object(llm.settings, "llm_provider", "mistral"), \
         patch.object(llm.settings, "mistral_chat_model", "mistral-small-latest"):
        assert llm._active_model() == "mistral-small-latest"


# --- dispatch --------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_dispatches_to_groq():
    client = _groq_client("hello world")
    with patch.object(llm.settings, "llm_provider", "groq"), \
         patch.object(llm, "_get_client", return_value=client):
        assert await llm.chat_complete([{"role": "user", "content": "hi"}]) == "hello world"
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_dispatches_to_mistral():
    client = _mistral_client("bonjour")
    with patch.object(llm.settings, "llm_provider", "mistral"), \
         patch.object(llm, "_get_client", return_value=client):
        assert await llm.chat_complete([{"role": "user", "content": "hi"}]) == "bonjour"
    client.chat.complete_async.assert_awaited_once()
    # Groq's call shape must not be used for Mistral.
    assert not client.chat.completions.create.await_count


@pytest.mark.asyncio
async def test_mistral_stream_unwraps_completion_event():
    """Mistral nests the chunk under `.data`; Groq does not."""
    def event(text):
        e = MagicMock()
        e.data.choices[0].delta.content = text
        return e

    async def fake_stream(*_a, **_kw):
        for t in ["Bon", "jour", None]:
            yield event(t)

    client = AsyncMock()
    client.chat.stream_async = AsyncMock(return_value=fake_stream())

    with patch.object(llm.settings, "llm_provider", "mistral"), \
         patch.object(llm, "_get_client", return_value=client):
        tokens = [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}])]

    assert tokens == ["Bon", "jour"]


# --- client caching --------------------------------------------------------

def test_client_is_cached_within_a_provider():
    with patch.object(llm.settings, "llm_provider", "groq"), \
         patch.object(llm, "_build_client", side_effect=lambda p: MagicMock(name=p)) as build:
        first = llm._get_client()
        second = llm._get_client()

    assert first is second
    assert build.call_count == 1


def test_client_is_rebuilt_when_provider_changes():
    """A stale cached client would silently keep calling the old vendor."""
    with patch.object(llm, "_build_client", side_effect=lambda p: MagicMock(name=p)) as build:
        with patch.object(llm.settings, "llm_provider", "groq"):
            groq_client = llm._get_client()
        with patch.object(llm.settings, "llm_provider", "mistral"):
            mistral_client = llm._get_client()

    assert groq_client is not mistral_client
    assert [c.args[0] for c in build.call_args_list] == ["groq", "mistral"]


def test_unknown_provider_raises_with_a_useful_message():
    with pytest.raises(ValueError, match="Unknown llm_provider"):
        llm._build_client("openai")


# --- content normalisation -------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, ""),
    ("plain", "plain"),
    ([], ""),
    (["a", "b"], "ab"),
])
def test_text_normalises_scalar_and_list_content(value, expected):
    assert llm._text(value) == expected


def test_text_flattens_typed_content_chunks():
    """Mistral content may arrive as typed chunks rather than a bare string."""
    chunk_a, chunk_b = MagicMock(), MagicMock()
    chunk_a.text, chunk_b.text = "Hello ", "world"
    assert llm._text([chunk_a, chunk_b]) == "Hello world"


def test_text_survives_a_chunk_without_text():
    chunk = MagicMock()
    chunk.text = None
    assert llm._text([chunk, "tail"]) == "tail"
