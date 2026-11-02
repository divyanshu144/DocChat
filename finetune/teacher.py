"""A minimal client for an OpenAI-compatible chat endpoint, used for the teacher model.

No key is ever read from the environment or printed: pass `--api-key-file` or nothing. Calls are retried a few times on
transient errors. In tests the whole client is replaced by any `complete(messages, max_tokens, temperature) -> str`.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Protocol

import httpx


class Teacher(Protocol):
    name: str

    def complete(self, messages: list[dict], max_tokens: int = 700, temperature: float = 0.2) -> str: ...


class HttpTeacher:
    def __init__(self, base_url: str, model: str, api_key_file: Path | None = None, retries: int = 3, timeout: float = 180.0,
                 client: httpx.Client | None = None, backoff_s: float = 1.0):
        key = api_key_file.read_text().strip() if api_key_file else ""
        self.name = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model, self._retries, self._backoff = model, retries, backoff_s
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._client = client or httpx.Client(timeout=timeout)
        self._client.headers.update(headers)

    def complete(self, messages: list[dict], max_tokens: int = 700, temperature: float = 0.2) -> str:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = self._client.post(self._url, json={"model": self._model, "messages": messages,
                                                              "max_tokens": max_tokens, "temperature": temperature})
                response.raise_for_status()
                return response.json()["choices"][0]["message"].get("content") or ""
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {408, 409, 429, 500, 502, 503, 504}:
                    raise
                last = exc
                time.sleep(self._backoff * 2 ** attempt)
        raise RuntimeError(f"teacher failed after {self._retries} attempts: {type(last).__name__}")


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(text: str) -> dict | None:
    """First JSON object in a model reply, tolerating code fences and chatter. None when there is none."""
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
