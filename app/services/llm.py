"""Provider-agnostic chat completion.

`chat_complete` / `chat_stream` are the only LLM entry points in the codebase —
the agent nodes never touch a vendor SDK. Selecting a backend is a config change
(`LLM_PROVIDER`), not a code change, which is what makes it possible to run the
same eval suite against two providers and compare the results.

Adding a provider means: a branch in `_build_client`, a `_*_complete`, a
`_*_stream`, and an entry in each dispatch. Nothing outside this module changes.
"""

import logging
import json

from typing import Any, AsyncGenerator

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cached alongside the provider it was built for, so flipping LLM_PROVIDER at
# runtime (tests, A/B scripts) rebuilds rather than silently reusing the old client.
_client: Any = None
_client_provider: str | None = None


def _active_model() -> str:
    """Model name for the configured provider."""
    if settings.llm_provider == "mistral":
        return settings.mistral_chat_model
    if settings.llm_provider == "openai":
        return settings.openai_chat_model
    return settings.chat_model


def _groq_models() -> list[str]:
    """Primary Groq model followed by an optional fallback."""
    models = [settings.chat_model]
    fallback = settings.groq_fallback_chat_model.strip()
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def _is_retryable_llm_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True

    message = str(exc).lower()
    retryable_markers = (
        "408",
        "409",
        "429",
        "500",
        "502",
        "503",
        "504",
        "rate limit",
        "too many requests",
        "timeout",
        "timed out",
        "temporarily",
        "unavailable",
    )
    return any(marker in message for marker in retryable_markers)


def _build_client(provider: str) -> Any:
    # Imported lazily so an unused provider's SDK never has to be installed, and a
    # missing one fails at call time with a clear error rather than at import time.
    if provider == "groq":
        from groq import AsyncGroq

        return AsyncGroq(api_key=settings.groq_api_key)

    if provider == "mistral":
        from mistralai.client import Mistral

        return Mistral(api_key=settings.mistral_api_key)

    if provider == "openai":
        import httpx

        return httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            timeout=60.0,
        )

    raise ValueError(
        f"Unknown llm_provider {provider!r}. "
        "Supported providers: 'groq', 'mistral', 'openai'."
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
    models = _groq_models()
    for index, model in enumerate(models):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            return _text(resp.choices[0].message.content)
        except Exception as exc:
            has_fallback = index < len(models) - 1
            if not has_fallback or not _is_retryable_llm_error(exc):
                raise
            logger.warning(
                "groq_chat_model_failed_retrying_fallback",
                extra={"model": model, "fallback_model": models[index + 1]},
            )
    return ""


async def _groq_stream(
    client: Any, messages: list[dict], max_tokens: int
) -> AsyncGenerator[str, None]:
    models = _groq_models()
    for index, model in enumerate(models):
        yielded = False
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yielded = True
                    yield _text(delta)
            return
        except Exception as exc:
            has_fallback = index < len(models) - 1
            if yielded or not has_fallback or not _is_retryable_llm_error(exc):
                raise
            logger.warning(
                "groq_stream_model_failed_retrying_fallback",
                extra={"model": model, "fallback_model": models[index + 1]},
            )


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
# OpenAI
# ---------------------------------------------------------------------------

async def _openai_complete(client: Any, messages: list[dict], max_tokens: int) -> str:
    resp = await client.post(
        "/chat/completions",
        json={
            "model": settings.openai_chat_model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return _text(data["choices"][0]["message"].get("content"))


async def _openai_stream(
    client: Any, messages: list[dict], max_tokens: int
) -> AsyncGenerator[str, None]:
    payload = {
        "model": settings.openai_chat_model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "stream": True,
    }
    async with client.stream("POST", "/chat/completions", json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line.removeprefix("data:").strip()
            if not raw or raw == "[DONE]":
                continue
            data = json.loads(raw)
            delta = data["choices"][0].get("delta", {}).get("content")
            if delta:
                yield _text(delta)


async def _openai_complete_with_temporary_client(
    messages: list[dict], max_tokens: int
) -> str:
    client = _build_client("openai")
    try:
        return await _openai_complete(client, messages, max_tokens)
    finally:
        await client.aclose()


async def _openai_stream_with_temporary_client(
    messages: list[dict], max_tokens: int
) -> AsyncGenerator[str, None]:
    client = _build_client("openai")
    try:
        async for token in _openai_stream(client, messages, max_tokens):
            yield token
    finally:
        await client.aclose()


def _can_fallback_to_openai(exc: Exception) -> bool:
    return (
        settings.fallback_llm_provider == "openai"
        and bool(settings.openai_api_key)
        and _is_retryable_llm_error(exc)
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat_complete(messages: list[dict], max_tokens: int = 1024) -> str:
    client = _get_client()
    if settings.llm_provider == "mistral":
        return await _mistral_complete(client, messages, max_tokens)
    if settings.llm_provider == "groq":
        try:
            return await _groq_complete(client, messages, max_tokens)
        except Exception as exc:
            if not _can_fallback_to_openai(exc):
                raise
            logger.warning(
                "groq_chat_failed_retrying_openai",
                extra={"fallback_model": settings.openai_chat_model},
            )
            return await _openai_complete_with_temporary_client(messages, max_tokens)
    if settings.llm_provider == "openai":
        return await _openai_complete(client, messages, max_tokens)
    raise ValueError(
        f"Unknown llm_provider {settings.llm_provider!r}. "
        "Supported providers: 'groq', 'mistral', 'openai'."
    )


async def chat_stream(
    messages: list[dict], max_tokens: int = 1024
) -> AsyncGenerator[str, None]:
    client = _get_client()
    if settings.llm_provider == "mistral":
        generator = _mistral_stream(client, messages, max_tokens)
    elif settings.llm_provider == "groq":
        yielded = False
        try:
            async for token in _groq_stream(client, messages, max_tokens):
                yielded = True
                yield token
        except Exception as exc:
            if yielded or not _can_fallback_to_openai(exc):
                raise
            logger.warning(
                "groq_stream_failed_retrying_openai",
                extra={"fallback_model": settings.openai_chat_model},
            )
            async for token in _openai_stream_with_temporary_client(messages, max_tokens):
                yield token
        return
    elif settings.llm_provider == "openai":
        generator = _openai_stream(client, messages, max_tokens)
    else:
        raise ValueError(
            f"Unknown llm_provider {settings.llm_provider!r}. "
            "Supported providers: 'groq', 'mistral', 'openai'."
        )
    async for token in generator:
        yield token
