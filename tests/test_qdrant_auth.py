"""Qdrant API key: sent on every call path when set, absent when not, never logged."""
import logging
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import qdrant as qdrant_mod
from app.core.config import settings


@pytest.fixture(autouse=True)
def _fresh_client_cache():
    qdrant_mod.get_qdrant_client.cache_clear()
    yield
    qdrant_mod.get_qdrant_client.cache_clear()


def test_headers_only_when_a_key_is_set(monkeypatch):
    monkeypatch.setattr(settings, "qdrant_api_key", "")
    assert qdrant_mod.qdrant_headers() == {}
    monkeypatch.setattr(settings, "qdrant_api_key", "k-123")
    assert qdrant_mod.qdrant_headers() == {"api-key": "k-123"}


def test_client_gets_the_key_or_none(monkeypatch):
    with patch.object(qdrant_mod, "QdrantClient") as client:
        monkeypatch.setattr(settings, "qdrant_api_key", "")
        qdrant_mod.get_qdrant_client()
        assert client.call_args.kwargs["api_key"] is None
        qdrant_mod.get_qdrant_client.cache_clear()
        monkeypatch.setattr(settings, "qdrant_api_key", "k-123")
        qdrant_mod.get_qdrant_client()
        assert client.call_args.kwargs["api_key"] == "k-123"


def test_the_insecure_connection_warning_is_suppressed_for_our_client(monkeypatch):
    """A stand-in client emits the warning the real one would; no connection is made."""
    def noisy_client(**kwargs):
        warnings.warn("Api key is used with an insecure connection.", UserWarning, stacklevel=2)
        return MagicMock()

    monkeypatch.setattr(settings, "qdrant_api_key", "k-123")
    with patch.object(qdrant_mod, "QdrantClient", noisy_client):
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            qdrant_mod.get_qdrant_client()
    assert not seen


async def test_retriever_search_sends_the_key(monkeypatch):
    from app.agent.nodes import retriever

    monkeypatch.setattr(settings, "qdrant_api_key", "k-123")
    response = MagicMock()
    response.json.return_value = {"result": []}
    http = MagicMock()
    http.post = AsyncMock(return_value=response)
    with patch.object(retriever, "_get_http_client", return_value=http):
        await retriever._search("c", [0.1], 3)
    assert http.post.call_args.kwargs["headers"] == {"api-key": "k-123"}


async def test_health_probe_sends_the_key(monkeypatch):
    from app.api import health

    monkeypatch.setattr(settings, "qdrant_api_key", "k-123")
    response = MagicMock()
    http = MagicMock()
    http.get = AsyncMock(return_value=response)
    with patch.object(health, "_get_http_client", return_value=http):
        await health._qdrant_probe()
    assert http.get.call_args.kwargs["headers"] == {"api-key": "k-123"}


async def test_key_never_appears_in_logs(monkeypatch, caplog):
    from app.agent.nodes import retriever

    monkeypatch.setattr(settings, "qdrant_api_key", "k-secret-xyz")
    response = MagicMock()
    response.json.return_value = {"result": []}
    http = MagicMock()
    http.post = AsyncMock(return_value=response)
    with caplog.at_level(logging.DEBUG), patch.object(retriever, "_get_http_client", return_value=http):
        await retriever._search("c", [0.1], 3)
    assert "k-secret-xyz" not in caplog.text
