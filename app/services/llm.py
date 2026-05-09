from typing import AsyncGenerator
from groq import AsyncGroq
from app.core.config import settings

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def chat_complete(messages: list[dict], max_tokens: int = 1024) -> str:
    resp = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


async def chat_stream(
    messages: list[dict], max_tokens: int = 1024
) -> AsyncGenerator[str, None]:
    stream = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
