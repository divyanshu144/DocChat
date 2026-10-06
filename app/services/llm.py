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
import asyncio
import inspect
from urllib.parse import urlsplit
from contextlib import aclosing

from typing import Any, AsyncGenerator

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.core.config import settings
from app.core.telemetry import span, record_usage, observe_stream, traced_generation, traced_stream_call, emit
from app.services.inference.types import GenerationRequest
from app.services.inference.openai_compatible import OpenAICompatibleBackend

logger = logging.getLogger(__name__)

# Pools are owned by their event loop and immutable connection configuration.
# Configuration switching retains old clients until that loop's explicit shutdown;
# it never closes a client underneath an in-flight request.
_clients: dict[tuple, Any] = {}


def _connection_key(provider):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None  # synchronous construction in tests/tools; no I/O yet
    credentials = {
        "groq": settings.groq_api_key, "mistral": settings.mistral_api_key,
        "openai": settings.openai_api_key, "local": settings.local_api_key,
    }
    return (loop, provider, credentials.get(provider),
            settings.local_base_url if provider == "local" else None,
            settings.inference_connect_timeout_s, settings.inference_read_timeout_s,
            settings.inference_pool_timeout_s, settings.inference_max_connections)


async def close_llm_clients():
    """Close every client owned by this loop, even if one close fails."""
    loop = asyncio.get_running_loop()
    errors = []
    for key in list(_clients):
        if key[0] is not loop:
            continue
        client = _clients.pop(key)
        try:
            close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result
            else:
                # Mistral owns separate async/sync clients, exposing context exits.
                if exit_async := getattr(client, "__aexit__", None):
                    await exit_async(None, None, None)
                if exit_sync := getattr(client, "__exit__", None):
                    exit_sync(None, None, None)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise ExceptionGroup("LLM client cleanup failed", errors)


def validate_local_endpoint():
    url = urlsplit(settings.local_base_url)
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username
            or url.password or url.query or url.fragment):
        raise ValueError("LOCAL_BASE_URL must be an HTTP(S) API URL without credentials/query")


def _active_model() -> str:
    """Model name for the configured provider."""
    if settings.llm_provider == "mistral":
        return settings.mistral_chat_model
    if settings.llm_provider == "openai":
        return settings.openai_chat_model
    if settings.llm_provider == "local":
        return settings.local_chat_model
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

    if provider in {"openai", "local"}:
        import httpx

        if provider == "local":
            validate_local_endpoint()
        key = settings.local_api_key if provider == "local" else settings.openai_api_key
        return httpx.AsyncClient(
            base_url=(settings.local_base_url if provider == "local"
                      else "https://api.openai.com/v1"),
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=httpx.Timeout(connect=settings.inference_connect_timeout_s,
                                  read=settings.inference_read_timeout_s,
                                  write=settings.inference_read_timeout_s,
                                  pool=settings.inference_pool_timeout_s),
            limits=httpx.Limits(max_connections=settings.inference_max_connections,
                               max_keepalive_connections=settings.inference_max_connections),
        )

    raise ValueError(
        f"Unknown llm_provider {provider!r}. "
        "Supported providers: 'groq', 'mistral', 'openai', 'local'."
    )


def _get_client() -> Any:
    provider = settings.llm_provider
    key = _connection_key(provider)
    if key not in _clients:
        _clients[key] = _build_client(provider)
    return _clients[key]


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


def _temperature_kwargs(temperature: float | None) -> dict:
    """Send `temperature` only when a caller asked for one.

    Omitting it leaves every existing call sampling at the provider default, so
    pinning the classification nodes cannot silently change the synthesizer's prose.
    """
    return {} if temperature is None else {"temperature": temperature}


def _mentions_temperature(resp: Any) -> bool:
    """Did this 400 complain about `temperature` specifically?

    Narrow on purpose: retrying a 400 we have not understood would just burn a second
    request and return the same error.
    """
    try:
        return "temperature" in json.dumps(resp.json()).lower()
    except Exception:  # pragma: no cover - malformed error body
        return False


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------

async def _groq_complete(
    client: Any, messages: list[dict], max_tokens: int, temperature: float | None = None
) -> str:
    models = _groq_models()
    for index, model in enumerate(models):
        try:
            with span("llm.attempt", provider="groq", model=model,
                      streaming=False, ttft_s=None, queue_wait_s=None):
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    **_temperature_kwargs(temperature),
                )
                record_usage(getattr(resp, "usage", None),
                             getattr(resp.choices[0], "finish_reason", None), getattr(resp, "id", None))
                return _text(resp.choices[0].message.content)
        except Exception as exc:
            has_fallback = index < len(models) - 1
            if not has_fallback or not _is_retryable_llm_error(exc):
                raise
            emit({"event": "llm_retry", "provider": "groq"})
            logger.warning(
                "groq_chat_model_failed_retrying_fallback",
                extra={"model": model, "fallback_model": models[index + 1]},
            )
    return ""


async def _groq_stream_attempt(client, model, messages, max_tokens, usage_sink):
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": True}
    if usage_sink is not None:
        kwargs["stream_options"] = {"include_usage": True}
    try:
        stream = await client.chat.completions.create(**kwargs)
    except TypeError as exc:
        if "stream_options" not in str(exc) or usage_sink is None:
            raise
        kwargs.pop("stream_options")
        stream = await client.chat.completions.create(**kwargs)
    try:
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage_sink is not None and usage is not None:
                usage_sink["prompt_tokens"] = usage.prompt_tokens
                usage_sink["completion_tokens"] = usage.completion_tokens
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if usage_sink is not None and choice.finish_reason:
                usage_sink["finish_reason"] = choice.finish_reason
            if choice.delta.content:
                yield _text(choice.delta.content)
    finally:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if close:
            result = close()
            if inspect.isawaitable(result):
                await result


async def _groq_stream(client, messages, max_tokens, usage_sink=None):
    models = _groq_models()
    for index, model in enumerate(models):
        yielded = False
        try:
            generator = _groq_stream_attempt(client, model, messages, max_tokens, usage_sink)
            async with aclosing(observe_stream(generator, provider="groq", model=model,
                                              usage=usage_sink)) as stream:
                async for text in stream:
                    yielded = True
                    yield text
            return
        except Exception as exc:
            if yielded or index == len(models) - 1 or not _is_retryable_llm_error(exc):
                raise
            if usage_sink is not None:
                usage_sink.clear()
            emit({"event": "llm_retry", "provider": "groq"})
            logger.warning("groq_stream_model_failed_retrying_fallback",
                           extra={"model": model, "fallback_model": models[index + 1]})


# ---------------------------------------------------------------------------
# Mistral
# ---------------------------------------------------------------------------

async def _mistral_complete(
    client: Any, messages: list[dict], max_tokens: int, temperature: float | None = None
) -> str:
    with span("llm.attempt", provider="mistral", model=_active_model(),
              streaming=False, ttft_s=None, queue_wait_s=None):
        resp = await client.chat.complete_async(
            model=_active_model(),
            messages=messages,
            max_tokens=max_tokens,
            **_temperature_kwargs(temperature),
        )
        record_usage(getattr(resp, "usage", None),
                     getattr(resp.choices[0], "finish_reason", None), getattr(resp, "id", None))
        return _text(resp.choices[0].message.content)


async def _mistral_stream(client, messages, max_tokens, usage_sink=None):
    generator = _mistral_stream_raw(client, messages, max_tokens, usage_sink)
    async with aclosing(observe_stream(generator, provider="mistral", model=settings.mistral_chat_model,
                                      usage=usage_sink)) as stream:
        async for text in stream:
            yield text


async def _mistral_stream_raw(
    client: Any, messages: list[dict], max_tokens: int, usage_sink: dict | None = None
) -> AsyncGenerator[str, None]:
    # Mistral wraps each chunk in a CompletionEvent — the payload is under `.data`.
    # Usage/finish_reason extraction here is best-effort and unverified against a
    # live Mistral stream — mirrors the OpenAI-compatible shape defensively via getattr.
    stream = await client.chat.stream_async(
        model=_active_model(),
        messages=messages,
        max_tokens=max_tokens,
    )
    try:
        async for event in stream:
            data = event.data
            if usage_sink is not None:
                usage = getattr(data, "usage", None)
                if usage is not None:
                    usage_sink["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
                    usage_sink["completion_tokens"] = getattr(usage, "completion_tokens", None)
            if not data.choices:
                continue
            choice = data.choices[0]
            if usage_sink is not None and getattr(choice, "finish_reason", None):
                usage_sink["finish_reason"] = choice.finish_reason
            delta = choice.delta.content
            if delta:
                yield _text(delta)
    finally:
        if close := getattr(stream, "aclose", None):
            await close()
        elif exit_async := getattr(stream, "__aexit__", None):
            await exit_async(None, None, None)



# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

# Models that have rejected an explicit temperature. Reasoning-family models accept
# only the default and reject every single time, so without this the retry below would
# permanently double the request count of every classification call.
_TEMPERATURE_UNSUPPORTED: set[str] = set()


async def _openai_post(client, payload):
    with span("llm.attempt", provider="openai", model=payload["model"],
              streaming=False, ttft_s=None, queue_wait_s=None) as record:
        response = await client.post("/chat/completions", json=payload)
        if response.status_code >= 400:
            record.update(outcome="error", status_code=response.status_code)
        else:
            data = response.json()
            choices = data.get("choices") or [{}]
            record_usage(data.get("usage"), choices[0].get("finish_reason"), data.get("id"))
        return response


async def _openai_complete(
    client: Any, messages: list[dict], max_tokens: int, temperature: float | None = None
) -> str:
    model = settings.openai_chat_model
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    if settings.openai_reasoning_effort:
        payload["reasoning_effort"] = settings.openai_reasoning_effort
    if model not in _TEMPERATURE_UNSUPPORTED:
        payload.update(_temperature_kwargs(temperature))

    resp = await _openai_post(client, payload)

    # Determinism is a nice-to-have; failing the user's request over it is not. Drop
    # the parameter and retry rather than propagate — then remember, so the next call
    # goes straight to the working shape.
    if resp.status_code == 400 and "temperature" in payload and _mentions_temperature(resp):
        emit({"event": "llm_retry", "provider": "openai"})
        _TEMPERATURE_UNSUPPORTED.add(model)
        logger.warning("openai_rejected_temperature_retrying_without", extra={"model": model})
        del payload["temperature"]
        resp = await _openai_post(client, payload)

    resp.raise_for_status()
    data = resp.json()
    return _text(data["choices"][0]["message"].get("content"))


async def _openai_stream(client, messages, max_tokens, usage_sink=None):
    generator = _openai_stream_raw(client, messages, max_tokens, usage_sink)
    async with aclosing(observe_stream(generator, provider="openai", model=settings.openai_chat_model,
                                      usage=usage_sink)) as stream:
        async for text in stream:
            yield text


async def _openai_stream_raw(
    client: Any, messages: list[dict], max_tokens: int, usage_sink: dict | None = None
) -> AsyncGenerator[str, None]:
    payload = {
        "model": settings.openai_chat_model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "stream": True,
    }
    if settings.openai_reasoning_effort:
        payload["reasoning_effort"] = settings.openai_reasoning_effort
    if usage_sink is not None:
        payload["stream_options"] = {"include_usage": True}
    async with client.stream("POST", "/chat/completions", json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line.removeprefix("data:").strip()
            if not raw or raw == "[DONE]":
                continue
            data = json.loads(raw)
            if usage_sink is not None and data.get("usage"):
                usage = data["usage"]
                usage_sink["prompt_tokens"] = usage.get("prompt_tokens")
                usage_sink["completion_tokens"] = usage.get("completion_tokens")
            # The usage-bearing final chunk (when stream_options requested it) carries
            # an empty `choices` list — guard rather than index into nothing.
            choices = data.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            if usage_sink is not None and choice.get("finish_reason"):
                usage_sink["finish_reason"] = choice["finish_reason"]
            delta = choice.get("delta", {}).get("content")
            if delta:
                yield _text(delta)


async def _openai_complete_with_temporary_client(
    messages: list[dict], max_tokens: int, temperature: float | None = None
) -> str:
    client = _build_client("openai")
    try:
        return await _openai_complete(client, messages, max_tokens, temperature)
    finally:
        await client.aclose()


async def _openai_stream_with_temporary_client(
    messages: list[dict], max_tokens: int, usage_sink: dict | None = None
) -> AsyncGenerator[str, None]:
    client = _build_client("openai")
    try:
        async with aclosing(_openai_stream(client, messages, max_tokens, usage_sink)) as stream:
            async for token in stream:
                yield token
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Local (self-hosted, e.g. vLLM's OpenAI-compatible server)
# ---------------------------------------------------------------------------
#
# vLLM's server is a plain OpenAI-compatible chat endpoint — no reasoning-model
# temperature quirks, no max_completion_tokens split, so this is a straight
# `max_tokens` request/response shape with none of `_openai_*`'s retry dance.


async def _local_complete(
    client: Any, messages: list[dict], max_tokens: int, temperature: float | None = None
) -> str:
    request = GenerationRequest(settings.local_chat_model, messages, max_tokens, temperature)
    if settings.local_stream_completions:
        # Buffer draft tokens internally; grounding/critic still run before UI delivery.
        async with aclosing(_local_stream(client, messages, max_tokens,
                                          temperature=temperature)) as stream:
            return "".join([text async for text in stream])
    with span("llm.attempt", provider="local", model=request.model,
              streaming=False, ttft_s=None, queue_wait_s=None):
        result = await OpenAICompatibleBackend(client).complete(request)
        record_usage(result.usage, result.finish_reason, result.request_id)
        return result.text


async def _local_stream(
    client: Any, messages: list[dict], max_tokens: int, usage_sink: dict | None = None,
    temperature: float | None = None
) -> AsyncGenerator[str, None]:
    request = GenerationRequest(settings.local_chat_model, messages, max_tokens, temperature)
    # Telemetry also consumes usage; old callers still receive only text.
    sink = usage_sink if usage_sink is not None else {}

    async def generate():
        backend = OpenAICompatibleBackend(client)
        async with aclosing(backend.stream(request, include_usage=True)) as events:
            async for event in events:
                sink.update(event.usage)
                if event.finish_reason:
                    sink["finish_reason"] = event.finish_reason
                record_usage(event.usage, event.finish_reason, event.request_id)
                if event.text:
                    yield event.text

    async with aclosing(observe_stream(generate(), provider="local", model=request.model,
                                      usage=sink)) as stream:
        async for text in stream:
            yield text


def _can_fallback_to_openai(exc: Exception) -> bool:
    return (
        settings.fallback_llm_provider == "openai"
        and bool(settings.openai_api_key)
        and _is_retryable_llm_error(exc)
    )


# ---------------------------------------------------------------------------
# Tracing
#
# LangGraph traces the agent nodes on its own, but every LLM call below goes
# through a vendor SDK (AsyncGroq, Mistral) or raw httpx (OpenAI) — none of which
# LangChain instruments. Without these decorators a trace shows five node runs
# and not a single prompt, completion, or token count.
# ---------------------------------------------------------------------------

def _tag_run(**metadata: Any) -> None:
    """Attach metadata to the active LangSmith run, if one exists.

    Never raises. Observability must not be able to break a chat request — a
    no-op here costs a missing label, an exception costs the user their answer.
    """
    try:
        run = get_current_run_tree()
        if run is not None:
            run.extra.setdefault("metadata", {}).update(metadata)
    except Exception:  # pragma: no cover - defensive only
        logger.debug("langsmith_tag_run_failed", exc_info=True)


def _join_stream(tokens: list[str]) -> dict:
    """Collapse streamed tokens into one output field.

    Without this the trace records the raw yield list — hundreds of fragments
    instead of the answer the user actually saw.
    """
    return {"output": "".join(tokens)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@traceable(run_type="llm", name="chat_complete")
@traced_generation
async def chat_complete(
    messages: list[dict], max_tokens: int = 1024, temperature: float | None = None
) -> str:
    """Complete a chat turn.

    `temperature=None` (the default) sends no temperature at all, leaving the provider
    default in place. Pass `0` for the classification nodes, whose output is a label
    that should not move between runs — see `settings.classification_temperature`.
    """
    _tag_run(
        provider=settings.llm_provider,
        model=_active_model(),
        streaming=False,
        temperature=temperature,
    )
    client = _get_client()
    if settings.llm_provider == "mistral":
        return await _mistral_complete(client, messages, max_tokens, temperature)
    if settings.llm_provider == "groq":
        try:
            return await _groq_complete(client, messages, max_tokens, temperature)
        except Exception as exc:
            if not _can_fallback_to_openai(exc):
                raise
            emit({"event": "llm_retry", "provider": "groq"})
            logger.warning(
                "groq_chat_failed_retrying_openai",
                extra={"fallback_model": settings.openai_chat_model},
            )
            return await _openai_complete_with_temporary_client(
                messages, max_tokens, temperature
            )
    if settings.llm_provider == "openai":
        return await _openai_complete(client, messages, max_tokens, temperature)
    if settings.llm_provider == "local":
        return await _local_complete(client, messages, max_tokens, temperature)
    raise ValueError(
        f"Unknown llm_provider {settings.llm_provider!r}. "
        "Supported providers: 'groq', 'mistral', 'openai', 'local'."
    )


@traceable(run_type="llm", name="chat_stream", reduce_fn=_join_stream)
@traced_stream_call
async def chat_stream(
    messages: list[dict], max_tokens: int = 1024, usage_sink: dict | None = None
) -> AsyncGenerator[str, None]:
    """Stream a chat completion.

    `usage_sink`, when passed a dict, is filled in-place with whatever the provider
    returns of `prompt_tokens`, `completion_tokens`, `finish_reason` — for callers
    (e.g. the inference benchmark) that need real usage/finish data a plain token
    stream doesn't carry. Public streams now request usage for telemetry even when
    the caller omits the sink; yielded text and optional sink shape are unchanged.
    """
    _tag_run(provider=settings.llm_provider, model=_active_model(), streaming=True)
    client = _get_client()
    sink = usage_sink if usage_sink is not None else {}
    provider = settings.llm_provider
    functions = {"mistral": _mistral_stream, "groq": _groq_stream,
                 "openai": _openai_stream, "local": _local_stream}
    if provider not in functions:
        raise ValueError(f"Unknown llm_provider {provider!r}")
    yielded = False
    try:
        async with aclosing(functions[provider](client, messages, max_tokens, sink)) as stream:
            async for token in stream:
                yielded = True
                yield token
    except Exception as exc:
        if provider != "groq" or yielded or not _can_fallback_to_openai(exc):
            raise
        sink.clear()
        emit({"event": "llm_retry", "provider": "groq"})
        logger.warning("groq_stream_failed_retrying_openai")
        async with aclosing(_openai_stream_with_temporary_client(
            messages, max_tokens, sink
        )) as stream:
            async for token in stream:
                yield token
