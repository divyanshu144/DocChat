"""Provider-agnostic chat completion.

`chat_complete` / `chat_stream` are the only LLM entry points in the codebase —
the agent nodes never touch a vendor SDK. Selecting a backend is a config change
(`LLM_PROVIDER`), not a code change, which is what makes it possible to run the
same eval suite against two providers and compare the results.

Adding a provider means: a branch in `_build_client`, a `_*_complete`, a
`_*_stream`, and an entry in each dispatch. Nothing outside this module changes.
"""

from typing import Any, AsyncGenerator

from app.core.config import settings

# Cached alongside the provider it was built for, so flipping LLM_PROVIDER at
# runtime (tests, A/B scripts) rebuilds rather than silently reusing the old client.
_client: Any = None
_client_provider: str | None = None


def _active_model() -> str:
    """Model name for the configured provider."""
    if settings.llm_provider == "mistral":
        return settings.mistral_chat_model
    return settings.chat_model


def _build_client(provider: str) -> Any:
    # Imported lazily so an unused provider's SDK never has to be installed, and a
    # missing one fails at call time with a clear error rather than at import time.
    if provider == "groq":
        from groq import AsyncGroq

        return AsyncGroq(api_key=settings.groq_api_key)

    if provider == "mistral":
        from mistralai.client import Mistral

        return Mistral(api_key=settings.mistral_api_key)

    raise ValueError(
        f"Unknown llm_provider {provider!r}. Supported providers: 'groq', 'mistral'."
    )


def _get_client() -> Any:
    global _client, _client_provider
    provider = settings.llm_provider
    if _client is None or _client_provider != provider:
        _client = _build_client(provider)
        _client_provider = provider
    return _client


def _text(content: Any) -> str:
    """Normalise a message content field to a plain string.

    Groq returns `str | None`. Mistral's content is a union that may also arrive
    as a list of typed chunks, so flatten those to their text.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part if isinstance(part, str) else (getattr(part, "text", "") or "")
            for part in content
        )
    return str(content)


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------

async def _groq_complete(client: Any, messages: list[dict], max_tokens: int) -> str:
    resp = await client.chat.completions.create(
        model=_active_model(),
        messages=messages,
        max_tokens=max_tokens,
    )
    return _text(resp.choices[0].message.content)


async def _groq_stream(
    client: Any, messages: list[dict], max_tokens: int
) -> AsyncGenerator[str, None]:
    stream = await client.chat.completions.create(
        model=_active_model(),
        messages=messages,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield _text(delta)


# ---------------------------------------------------------------------------
# Mistral
# ---------------------------------------------------------------------------

async def _mistral_complete(client: Any, messages: list[dict], max_tokens: int) -> str:
    resp = await client.chat.complete_async(
        model=_active_model(),
        messages=messages,
        max_tokens=max_tokens,
    )
    return _text(resp.choices[0].message.content)


async def _mistral_stream(
    client: Any, messages: list[dict], max_tokens: int
) -> AsyncGenerator[str, None]:
    # Mistral wraps each chunk in a CompletionEvent — the payload is under `.data`.
    stream = await client.chat.stream_async(
        model=_active_model(),
        messages=messages,
        max_tokens=max_tokens,
    )
    async for event in stream:
        delta = event.data.choices[0].delta.content
        if delta:
            yield _text(delta)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat_complete(messages: list[dict], max_tokens: int = 1024) -> str:
    client = _get_client()
    if settings.llm_provider == "mistral":
        return await _mistral_complete(client, messages, max_tokens)
    return await _groq_complete(client, messages, max_tokens)


async def chat_stream(
    messages: list[dict], max_tokens: int = 1024
) -> AsyncGenerator[str, None]:
    client = _get_client()
    if settings.llm_provider == "mistral":
        generator = _mistral_stream(client, messages, max_tokens)
    else:
        generator = _groq_stream(client, messages, max_tokens)
    async for token in generator:
        yield token
