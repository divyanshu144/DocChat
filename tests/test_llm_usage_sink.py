"""Tests for the optional `usage_sink` parameter on `chat_stream` / `_*_stream`.

The contract: passing nothing (the default, every existing production caller)
must send no extra request field and touch nothing — verified here by asserting
the exact payload/kwargs sent. Passing a dict must get it filled with whatever
the provider returns of prompt_tokens/completion_tokens/finish_reason.

No network. Every provider client is faked.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import llm


@pytest.fixture(autouse=True)
def _reset_client_cache():
    llm._client = None
    llm._client_provider = None
    yield
    llm._client = None
    llm._client_provider = None


# ---------------------------------------------------------------------------
# OpenAI / local — same SSE shape, same code path
# ---------------------------------------------------------------------------


def _sse_stream_client(lines: list[str]):
    async def fake_aiter_lines():
        for line in lines:
            yield line

    resp = MagicMock()
    resp.aiter_lines = fake_aiter_lines
    resp.raise_for_status = MagicMock()

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=resp)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.stream = MagicMock(return_value=stream_cm)
    return client


_USAGE_SSE_LINES = [
    'data: {"choices": [{"delta": {"content": "hel"}}]}',
    'data: {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]}',
    'data: {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 2}}',
    "data: [DONE]",
]


@pytest.mark.asyncio
async def test_openai_stream_omits_stream_options_when_no_sink():
    client = _sse_stream_client(_USAGE_SSE_LINES)
    with patch.object(llm.settings, "openai_chat_model", "gpt-test"):
        tokens = [t async for t in llm._openai_stream(client, [{"role": "user", "content": "hi"}], 50)]

    assert tokens == ["hel", "lo"]
    sent_payload = client.stream.call_args.kwargs["json"]
    assert "stream_options" not in sent_payload


@pytest.mark.asyncio
async def test_openai_stream_threads_selected_reasoning_effort():
    client = _sse_stream_client(_USAGE_SSE_LINES)
    with patch.object(llm.settings, "openai_reasoning_effort", "none"):
        tokens = [t async for t in llm._openai_stream(client, [{"role": "user", "content": "hi"}], 50)]
    assert tokens == ["hel", "lo"]
    assert client.stream.call_args.kwargs["json"]["reasoning_effort"] == "none"


@pytest.mark.asyncio
async def test_openai_stream_requests_usage_when_sink_given():
    client = _sse_stream_client(_USAGE_SSE_LINES)
    sink: dict = {}
    with patch.object(llm.settings, "openai_chat_model", "gpt-test"):
        tokens = [
            t
            async for t in llm._openai_stream(
                client, [{"role": "user", "content": "hi"}], 50, usage_sink=sink
            )
        ]

    assert tokens == ["hel", "lo"]
    assert client.stream.call_args.kwargs["json"]["stream_options"] == {"include_usage": True}
    assert sink == {"prompt_tokens": 12, "completion_tokens": 2, "finish_reason": "stop"}


@pytest.mark.asyncio
async def test_openai_stream_empty_choices_usage_chunk_does_not_crash():
    """The usage-bearing final chunk has `choices: []` — must not IndexError."""
    client = _sse_stream_client(_USAGE_SSE_LINES)
    sink: dict = {}
    with patch.object(llm.settings, "openai_chat_model", "gpt-test"):
        tokens = [
            t
            async for t in llm._openai_stream(
                client, [{"role": "user", "content": "hi"}], 50, usage_sink=sink
            )
        ]
    assert tokens == ["hel", "lo"]  # ran to completion, no exception


@pytest.mark.asyncio
async def test_local_stream_requests_usage_when_sink_given():
    client = _sse_stream_client(_USAGE_SSE_LINES)
    sink: dict = {}
    with patch.object(llm.settings, "local_chat_model", "Qwen2.5-7B-Instruct"):
        tokens = [
            t
            async for t in llm._local_stream(
                client, [{"role": "user", "content": "hi"}], 50, usage_sink=sink
            )
        ]

    assert tokens == ["hel", "lo"]
    assert client.stream.call_args.kwargs["json"]["stream_options"] == {"include_usage": True}
    assert sink == {"prompt_tokens": 12, "completion_tokens": 2, "finish_reason": "stop"}


# ---------------------------------------------------------------------------
# Groq — SDK-shaped chunks, not raw SSE
# ---------------------------------------------------------------------------


def _groq_chunk(content=None, finish_reason=None, usage=None):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    chunk.choices[0].finish_reason = finish_reason
    chunk.usage = usage
    return chunk


def _groq_usage(prompt_tokens, completion_tokens):
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    return usage


@pytest.mark.asyncio
async def test_groq_stream_omits_stream_options_when_no_sink():
    chunks = [_groq_chunk(content="hi")]

    async def fake_stream():
        for c in chunks:
            yield c

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=fake_stream())

    with patch.object(llm.settings, "chat_model", "test-model"), \
         patch.object(llm.settings, "groq_fallback_chat_model", ""):
        tokens = [t async for t in llm._groq_stream(client, [{"role": "user", "content": "hi"}], 50)]

    assert tokens == ["hi"]
    assert "stream_options" not in client.chat.completions.create.call_args.kwargs


@pytest.mark.asyncio
async def test_groq_stream_populates_sink_from_usage_chunk():
    final_usage_chunk = _groq_chunk(content=None, finish_reason=None, usage=_groq_usage(9, 3))
    final_usage_chunk.choices = []  # Groq's usage-only final chunk carries no choices

    chunks = [
        _groq_chunk(content="he"),
        _groq_chunk(content="llo", finish_reason="stop"),
        final_usage_chunk,
    ]

    async def fake_stream():
        for c in chunks:
            yield c

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=fake_stream())
    sink: dict = {}

    with patch.object(llm.settings, "chat_model", "test-model"), \
         patch.object(llm.settings, "groq_fallback_chat_model", ""):
        tokens = [
            t
            async for t in llm._groq_stream(
                client, [{"role": "user", "content": "hi"}], 50, usage_sink=sink
            )
        ]

    assert tokens == ["he", "llo"]
    assert client.chat.completions.create.call_args.kwargs["stream_options"] == {
        "include_usage": True
    }
    assert sink == {"prompt_tokens": 9, "completion_tokens": 3, "finish_reason": "stop"}


# ---------------------------------------------------------------------------
# Public chat_stream() threads usage_sink through to the active provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_threads_usage_sink_to_openai():
    client = _sse_stream_client(_USAGE_SSE_LINES)
    sink: dict = {}
    with patch.object(llm.settings, "llm_provider", "openai"), \
         patch.object(llm.settings, "openai_chat_model", "gpt-test"), \
         patch.object(llm, "_get_client", return_value=client):
        tokens = [
            t async for t in llm.chat_stream([{"role": "user", "content": "hi"}], usage_sink=sink)
        ]

    assert tokens == ["hel", "lo"]
    assert sink["completion_tokens"] == 2
