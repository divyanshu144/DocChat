"""vLLM-first transport. Other engines require contract tests before claiming support."""
import json

from app.services.inference.types import GenerationRequest, GenerationResult
from app.core.telemetry import request_id


class InvalidInferenceResponse(ValueError):
    pass


def _result(data: dict, *, streaming: bool) -> GenerationResult:
    if not isinstance(data, dict) or data.get("error"):
        raise InvalidInferenceResponse("Invalid completion response")
    choices = data.get("choices") or []
    usage = data.get("usage") or {}
    if not isinstance(choices, list) or not isinstance(usage, dict):
        raise InvalidInferenceResponse("Invalid completion metadata")
    if not choices and not streaming:
        raise InvalidInferenceResponse("Completion has no choices")
    choice = choices[0] if choices else {}
    if not isinstance(choice, dict):
        raise InvalidInferenceResponse("Invalid completion choice")
    message = choice.get("delta" if streaming else "message") or {}
    if not isinstance(message, dict):
        raise InvalidInferenceResponse("Invalid completion content")
    text = message.get("content") or ""
    if not isinstance(text, str):
        raise InvalidInferenceResponse("Expected text completion")
    counts = {k: v for k, v in usage.items()
              if k in {"prompt_tokens", "completion_tokens"} and type(v) is int and v >= 0}
    return GenerationResult(text, counts, choice.get("finish_reason"), data.get("id"))


class OpenAICompatibleBackend:
    def __init__(self, client):
        self.client = client

    @staticmethod
    def _payload(request):
        payload = {"model": request.model, "messages": request.messages,
                   "max_tokens": request.max_tokens}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload

    @staticmethod
    def _headers():
        identifier = request_id()
        return {"headers": {"X-Request-Id": identifier}} if identifier else {}

    async def complete(self, request: GenerationRequest) -> GenerationResult:
        response = await self.client.post("/chat/completions", json=self._payload(request), **self._headers())
        response.raise_for_status()
        return _result(response.json(), streaming=False)

    async def stream(self, request: GenerationRequest, *, include_usage: bool = True):
        payload = {**self._payload(request), "stream": True}
        if include_usage:
            payload["stream_options"] = {"include_usage": True}
        async with self.client.stream("POST", "/chat/completions", json=payload, **self._headers()) as response:
            response.raise_for_status()
            finished = False
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if not raw:
                    continue
                if raw == "[DONE]":
                    return
                event = _result(json.loads(raw), streaming=True)
                finished = finished or bool(event.finish_reason)
                yield event
            if not finished:
                raise InvalidInferenceResponse("Stream ended without a terminal event")
