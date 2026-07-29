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


def _openai_client(content="from openai"):
    resp = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    return client


def _groq_stream_chunk(text):
    chunk = MagicMock()
    chunk.choices[0].delta.content = text
    return chunk


async def _groq_stream(*texts):
    for text in texts:
        yield _groq_stream_chunk(text)


async def _token_stream(*texts):
    for text in texts:
        yield text


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


def test_active_model_uses_openai_model_when_selected():
    with patch.object(llm.settings, "llm_provider", "openai"), \
         patch.object(llm.settings, "openai_chat_model", "gpt-5.6-luna"):
        assert llm._active_model() == "gpt-5.6-luna"


def test_groq_models_include_distinct_fallback():
    with patch.object(llm.settings, "chat_model", "llama-3.3-70b-versatile"), \
         patch.object(llm.settings, "groq_fallback_chat_model", "openai/gpt-oss-20b"):
        assert llm._groq_models() == [
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-20b",
        ]


def test_groq_models_skip_empty_or_duplicate_fallback():
    with patch.object(llm.settings, "chat_model", "llama-3.3-70b-versatile"), \
         patch.object(llm.settings, "groq_fallback_chat_model", " llama-3.3-70b-versatile "):
        assert llm._groq_models() == ["llama-3.3-70b-versatile"]


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
async def test_complete_dispatches_to_openai():
    client = _openai_client("from api")
    with patch.object(llm.settings, "llm_provider", "openai"), \
         patch.object(llm.settings, "openai_chat_model", "gpt-5.6-luna"), \
         patch.object(llm, "_get_client", return_value=client):
        assert await llm.chat_complete([{"role": "user", "content": "hi"}]) == "from api"

    client.post.assert_awaited_once()
    assert client.post.await_args.kwargs["json"]["model"] == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_groq_complete_retries_fallback_model_on_rate_limit():
    resp = MagicMock()
    resp.choices[0].message.content = "from fallback"
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[RuntimeError("429 Too Many Requests"), resp]
    )

    with patch.object(llm.settings, "chat_model", "llama-3.3-70b-versatile"), \
         patch.object(llm.settings, "groq_fallback_chat_model", "openai/gpt-oss-20b"):
        result = await llm._groq_complete(client, [{"role": "user", "content": "hi"}], 50)

    assert result == "from fallback"
    assert [call.kwargs["model"] for call in client.chat.completions.create.call_args_list] == [
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-20b",
    ]


@pytest.mark.asyncio
async def test_groq_complete_does_not_retry_non_retryable_error():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("bad request"))

    with patch.object(llm.settings, "chat_model", "llama-3.3-70b-versatile"), \
         patch.object(llm.settings, "groq_fallback_chat_model", "openai/gpt-oss-20b"):
        with pytest.raises(RuntimeError, match="bad request"):
            await llm._groq_complete(client, [{"role": "user", "content": "hi"}], 50)

    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_groq_complete_falls_back_to_openai_provider_on_retryable_error():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("429 rate limit"))

    with patch.object(llm.settings, "llm_provider", "groq"), \
         patch.object(llm.settings, "groq_fallback_chat_model", ""), \
         patch.object(llm.settings, "fallback_llm_provider", "openai"), \
         patch.object(llm.settings, "openai_api_key", "sk-test"), \
         patch.object(llm, "_get_client", return_value=client), \
         patch.object(
             llm,
             "_openai_complete_with_temporary_client",
             new_callable=AsyncMock,
             return_value="from openai",
         ) as openai_complete:
        result = await llm.chat_complete([{"role": "user", "content": "hi"}])

    assert result == "from openai"
    openai_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_groq_complete_requires_openai_key_for_provider_fallback():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("429 rate limit"))

    with patch.object(llm.settings, "llm_provider", "groq"), \
         patch.object(llm.settings, "groq_fallback_chat_model", ""), \
         patch.object(llm.settings, "fallback_llm_provider", "openai"), \
         patch.object(llm.settings, "openai_api_key", ""), \
         patch.object(llm, "_get_client", return_value=client), \
         patch.object(llm, "_openai_complete_with_temporary_client", new_callable=AsyncMock) as openai_complete:
        with pytest.raises(RuntimeError, match="429 rate limit"):
            await llm.chat_complete([{"role": "user", "content": "hi"}])

    openai_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_groq_stream_retries_fallback_model_before_tokens_start():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[RuntimeError("503 unavailable"), _groq_stream("fall", "back")]
    )

    with patch.object(llm.settings, "chat_model", "llama-3.3-70b-versatile"), \
         patch.object(llm.settings, "groq_fallback_chat_model", "openai/gpt-oss-20b"):
        tokens = [t async for t in llm._groq_stream(
            client,
            [{"role": "user", "content": "hi"}],
            50,
        )]

    assert tokens == ["fall", "back"]
    assert [call.kwargs["model"] for call in client.chat.completions.create.call_args_list] == [
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-20b",
    ]


@pytest.mark.asyncio
async def test_groq_stream_falls_back_to_openai_provider_before_tokens_start():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("503 unavailable"))

    with patch.object(llm.settings, "llm_provider", "groq"), \
         patch.object(llm.settings, "groq_fallback_chat_model", ""), \
         patch.object(llm.settings, "fallback_llm_provider", "openai"), \
         patch.object(llm.settings, "openai_api_key", "sk-test"), \
         patch.object(llm, "_get_client", return_value=client), \
         patch.object(
             llm,
             "_openai_stream_with_temporary_client",
             side_effect=lambda *_args: _token_stream("open", "ai"),
         ):
        tokens = [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}])]

    assert tokens == ["open", "ai"]


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
        with patch.object(llm.settings, "llm_provider", "openai"):
            openai_client = llm._get_client()

    assert groq_client is not mistral_client
    assert mistral_client is not openai_client
    assert [c.args[0] for c in build.call_args_list] == ["groq", "mistral", "openai"]


def test_unknown_provider_raises_with_a_useful_message():
    with pytest.raises(ValueError, match="Unknown llm_provider"):
        llm._build_client("anthropic")


@pytest.mark.asyncio
async def test_complete_rejects_unknown_provider_in_dispatch():
    with patch.object(llm.settings, "llm_provider", "anthropic"), \
         patch.object(llm, "_get_client", return_value=MagicMock()):
        with pytest.raises(ValueError, match="Unknown llm_provider"):
            await llm.chat_complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_stream_rejects_unknown_provider_in_dispatch():
    with patch.object(llm.settings, "llm_provider", "anthropic"), \
         patch.object(llm, "_get_client", return_value=MagicMock()):
        with pytest.raises(ValueError, match="Unknown llm_provider"):
            tokens = [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}])]
            assert tokens == []


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
