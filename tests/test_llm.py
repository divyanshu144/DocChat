import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm import chat_complete, chat_stream


@pytest.mark.asyncio
async def test_chat_complete_returns_content():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello world"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("app.services.llm._get_client", return_value=mock_client):
        result = await chat_complete([{"role": "user", "content": "hi"}])

    assert result == "hello world"


@pytest.mark.asyncio
async def test_chat_stream_yields_tokens():
    chunk1 = MagicMock()
    chunk1.choices[0].delta.content = "hello"
    chunk2 = MagicMock()
    chunk2.choices[0].delta.content = " world"
    chunk3 = MagicMock()
    chunk3.choices[0].delta.content = None

    async def fake_stream(*args, **kwargs):
        for c in [chunk1, chunk2, chunk3]:
            yield c

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())

    with patch("app.services.llm._get_client", return_value=mock_client):
        tokens = []
        async for token in chat_stream([{"role": "user", "content": "hi"}]):
            tokens.append(token)

    assert tokens == ["hello", " world"]
