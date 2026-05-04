"""Tests for app/services/chat.py — Bug #1 guard: None content from Groq."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_completion(content):
    """Build a minimal mock response mirroring groq ChatCompletion structure."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_stream_chunk(content):
    """Build a minimal mock streaming chunk."""
    delta = MagicMock()
    delta.content = content
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


@pytest.mark.asyncio
async def test_generate_reply_returns_empty_string_when_content_is_none():
    """generate_reply must return '' instead of None when Groq returns None content."""
    mock_response = _make_completion(None)

    with patch("app.services.chat._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        with patch("app.services.chat.settings") as mock_settings:
            mock_settings.groq_api_key = "test-key"
            mock_settings.chat_model = "llama3-8b-8192"

            from app.services.chat import generate_reply
            result = await generate_reply("What is AI?", ["Some context"], [])

    assert result == "", f"Expected empty string, got {result!r}"
    assert isinstance(result, str), "Result must be a str, not None"


@pytest.mark.asyncio
async def test_generate_reply_returns_content_when_present():
    """generate_reply must pass through non-None content unchanged."""
    mock_response = _make_completion("Artificial intelligence is a field of computer science.")

    with patch("app.services.chat._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        with patch("app.services.chat.settings") as mock_settings:
            mock_settings.groq_api_key = "test-key"
            mock_settings.chat_model = "llama3-8b-8192"

            from app.services.chat import generate_reply
            result = await generate_reply("What is AI?", ["Some context"], [])

    assert result == "Artificial intelligence is a field of computer science."


@pytest.mark.asyncio
async def test_generate_reply_returns_empty_string_when_content_is_empty_string():
    """generate_reply must return '' when Groq returns an empty string."""
    mock_response = _make_completion("")

    with patch("app.services.chat._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        with patch("app.services.chat.settings") as mock_settings:
            mock_settings.groq_api_key = "test-key"
            mock_settings.chat_model = "llama3-8b-8192"

            from app.services.chat import generate_reply
            result = await generate_reply("What is AI?", [], [])

    assert result == ""
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_generate_reply_stream_skips_none_delta():
    """generate_reply_stream must not yield tokens when delta.content is None."""

    async def mock_stream():
        yield _make_stream_chunk(None)
        yield _make_stream_chunk("Hello")
        yield _make_stream_chunk(None)
        yield _make_stream_chunk(" world")

    with patch("app.services.chat._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_get_client.return_value = mock_client

        with patch("app.services.chat.settings") as mock_settings:
            mock_settings.groq_api_key = "test-key"
            mock_settings.chat_model = "llama3-8b-8192"

            from app.services.chat import generate_reply_stream
            tokens = []
            async for token in generate_reply_stream("What is AI?", ["context"], []):
                tokens.append(token)

    assert tokens == ["Hello", " world"], f"Unexpected tokens: {tokens}"


@pytest.mark.asyncio
async def test_generate_reply_stream_skips_empty_string_delta():
    """generate_reply_stream must not yield empty string tokens (falsy guard)."""

    async def mock_stream():
        yield _make_stream_chunk("")
        yield _make_stream_chunk("Token")

    with patch("app.services.chat._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_get_client.return_value = mock_client

        with patch("app.services.chat.settings") as mock_settings:
            mock_settings.groq_api_key = "test-key"
            mock_settings.chat_model = "llama3-8b-8192"

            from app.services.chat import generate_reply_stream
            tokens = []
            async for token in generate_reply_stream("Q", [], []):
                tokens.append(token)

    assert tokens == ["Token"]
