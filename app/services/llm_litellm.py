"""Opt-in LiteLLM backend for `app/services/llm.py` (`LLM_BACKEND=litellm`).

Same contract as the native paths: the same entry points, `usage_sink`, timing spans, retry
classification, temperature handling and fallback chain. LiteLLM is used as the call engine
(one `Router` deployment per provider model, every key and URL taken from `settings`).

The fallback chain is deliberately driven from here and NOT by `Router(fallbacks=...)`.
Measured against LiteLLM 1.83.0 (see docs/litellm-backend.md): the Router falls back on any error,
including a 400 or 401, and when a stream fails after tokens were sent it continues on the fallback
model, so a caller sees the first tokens twice. The native backend only falls back on errors
`_is_retryable_llm_error` accepts, and never after the first token. So the Router is created
with no fallbacks, no retries and no cooldowns, and `chain()` below decides the next model.
"""

import logging
from contextlib import aclosing
from typing import Any, AsyncGenerator

from app.core.config import settings
from app.core.telemetry import emit, observe_stream, record_usage, span
from app.services import llm as native

logger = logging.getLogger(__name__)

_ROUTERS: dict[tuple, Any] = {}
_LITELLM_LOGGERS = ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy")


def _litellm():
    try:
        import litellm
    except ImportError as exc:
        raise RuntimeError(
            "LLM_BACKEND=litellm needs the optional package: "
            "pip install -r requirements-litellm.txt"
        ) from exc
    # At DEBUG, LiteLLM logs whole prompts and request URLs. This project's rule is that logs never carry
    # document content, prompts or URLs, so its loggers are held at WARNING whatever the root level is.
    for name in _LITELLM_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return litellm


def _provider_of(deployment: str) -> str:
    return deployment.split("-")[0]


def _deployment_params(name: str) -> dict:
    """LiteLLM parameters for one deployment. Keys come from settings, never from the environment.

    A blank key must not reach LiteLLM: it would go and look for GROQ_API_KEY and friends itself.
    """
    provider = _provider_of(name)
    if provider == "groq":
        models = native._groq_models()
        return {"model": f"groq/{models[int(name.split('-')[1])]}", "api_key": _require(settings.groq_api_key, "groq")}
    if provider == "openai":
        return {"model": f"openai/{settings.openai_chat_model}", "api_key": _require(settings.openai_api_key, "openai")}
    if provider == "mistral":
        return {"model": f"mistral/{settings.mistral_chat_model}", "api_key": _require(settings.mistral_api_key, "mistral")}
    if provider == "local":
        native.validate_local_endpoint()
        # The native client sends no auth header when the key is blank; LiteLLM's openai route wants a value.
        return {"model": f"openai/{settings.local_chat_model}", "api_base": settings.local_base_url,
                "api_key": settings.local_api_key or "none"}
    raise ValueError(f"Unknown deployment {name!r}")


def _require(key: str, provider: str) -> str:
    if not key:
        raise ValueError(f"No API key configured for {provider}; set it in settings (LiteLLM never reads the environment)")
    return key


def chain(primary: str) -> list[str]:
    """Deployments to try in order, reproducing the native fallback rules.

    groq: each Groq model, then openai. openai: openai, then groq. mistral and local never fall
    back, and `local` is never a fallback target (a rented GPU may not be running).
    """
    if primary not in {"groq", "mistral", "openai", "local"}:
        raise ValueError(
            f"Unknown llm_provider {primary!r}. Supported providers: 'groq', 'mistral', 'openai', 'local'."
        )
    groq = [f"groq-{i}" for i in range(len(native._groq_models()))]
    fallback = settings.fallback_llm_provider
    allowed = primary in {"groq", "openai"} and fallback in {"groq", "openai"} and fallback != primary
    if allowed and not (settings.openai_api_key if fallback == "openai" else settings.groq_api_key):
        allowed = False  # same rule as `_can_fallback`: no key, no fallback
    if primary == "groq":
        return groq + (["openai"] if allowed else [])
    if primary == "openai":
        return ["openai"] + (groq if allowed else [])
    return [primary]


def _router(deployments: list[str]):
    litellm = _litellm()
    key = (native._connection_key(settings.llm_provider), tuple(deployments), settings.fallback_llm_provider,
           settings.groq_fallback_chat_model, settings.openai_chat_model, settings.mistral_chat_model,
           settings.chat_model, settings.local_chat_model, settings.openai_api_key, settings.groq_api_key,
           settings.mistral_api_key)
    if key not in _ROUTERS:
        _ROUTERS[key] = litellm.Router(
            model_list=[{"model_name": name, "litellm_params": _deployment_params(name)} for name in deployments],
            num_retries=0, disable_cooldowns=True,
            timeout=settings.inference_read_timeout_s,
        )
    return _ROUTERS[key]


def _request_kwargs(name: str, messages: list[dict], max_tokens: int) -> dict:
    kwargs: dict = {"model": name, "messages": messages}
    if _provider_of(name) == "openai":
        # The native openai path sends max_completion_tokens, which reasoning models require.
        kwargs["max_completion_tokens"] = max_tokens
        if settings.openai_reasoning_effort:
            kwargs["reasoning_effort"] = settings.openai_reasoning_effort
    else:
        kwargs["max_tokens"] = max_tokens
    return kwargs


def _model_name(name: str) -> str:
    return _deployment_params(name)["model"].split("/", 1)[1]


def _rejected_temperature(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 400 and "temperature" in str(exc).lower()


async def _complete_one(router, name: str, messages: list[dict], max_tokens: int, temperature: float | None) -> str:
    kwargs = _request_kwargs(name, messages, max_tokens)
    model = _model_name(name)
    openai_quirk = name == "openai"
    if temperature is not None and not (openai_quirk and model in native._TEMPERATURE_UNSUPPORTED):
        kwargs["temperature"] = temperature
    for attempt in range(2):
        try:
            with span("llm.attempt", provider=_provider_of(name), model=model,
                      streaming=False, ttft_s=None, queue_wait_s=None):
                resp = await router.acompletion(**kwargs)
                choice = resp.choices[0]
                record_usage(getattr(resp, "usage", None), getattr(choice, "finish_reason", None),
                             getattr(resp, "id", None))
                return native._text(choice.message.content)
        except Exception as exc:
            # Same rule as the native openai path: determinism is a nice-to-have, so drop the
            # parameter, remember the model, and retry once instead of failing the request.
            if attempt == 0 and openai_quirk and "temperature" in kwargs and _rejected_temperature(exc):
                emit({"event": "llm_retry", "provider": "openai"})
                native._TEMPERATURE_UNSUPPORTED.add(model)
                logger.warning("openai_rejected_temperature_retrying_without", extra={"model": model})
                del kwargs["temperature"]
                continue
            raise
    raise AssertionError("unreachable")  # pragma: no cover


async def complete(messages: list[dict], max_tokens: int, temperature: float | None = None) -> str:
    deployments = chain(settings.llm_provider)
    router = _router(deployments)
    for index, name in enumerate(deployments):
        try:
            return await _complete_one(router, name, messages, max_tokens, temperature)
        except Exception as exc:
            if index == len(deployments) - 1 or not native._is_retryable_llm_error(exc):
                raise
            emit({"event": "llm_retry", "provider": _provider_of(name)})
            logger.warning("litellm_chat_failed_retrying_fallback",
                           extra={"model": _model_name(name), "fallback_model": _model_name(deployments[index + 1])})
    return ""  # pragma: no cover


async def _stream_one(router, name: str, messages: list[dict], max_tokens: int,
                      usage_sink: dict) -> AsyncGenerator[str, None]:
    kwargs = _request_kwargs(name, messages, max_tokens)
    response = await router.acompletion(stream=True, stream_options={"include_usage": True}, **kwargs)
    try:
        async for chunk in response:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                usage_sink["prompt_tokens"] = usage.prompt_tokens
                usage_sink["completion_tokens"] = usage.completion_tokens
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                usage_sink["finish_reason"] = choice.finish_reason
            if choice.delta.content:
                yield native._text(choice.delta.content)
    finally:
        close = getattr(response, "aclose", None)
        if close:
            await close()


async def stream(messages: list[dict], max_tokens: int, usage_sink: dict | None = None) -> AsyncGenerator[str, None]:
    sink = usage_sink if usage_sink is not None else {}
    deployments = chain(settings.llm_provider)
    router = _router(deployments)
    yielded = False
    for index, name in enumerate(deployments):
        try:
            attempt = _stream_one(router, name, messages, max_tokens, sink)
            async with aclosing(observe_stream(attempt, provider=_provider_of(name), model=_model_name(name),
                                              usage=sink)) as tokens:
                async for text in tokens:
                    yielded = True
                    yield text
            return
        except Exception as exc:
            if yielded or index == len(deployments) - 1 or not native._is_retryable_llm_error(exc):
                raise
            sink.clear()
            emit({"event": "llm_retry", "provider": _provider_of(name)})
            logger.warning("litellm_stream_failed_retrying_fallback",
                           extra={"model": _model_name(name), "fallback_model": _model_name(deployments[index + 1])})
