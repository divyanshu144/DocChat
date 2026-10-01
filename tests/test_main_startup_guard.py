"""Tests for the startup guard that refuses to run with the shipped default
JWT secret outside debug mode (app/main.py).

TestClient(app) without a `with` block, the pattern every other test file in
this repo uses, never runs the FastAPI lifespan -- confirmed empirically
before writing this guard, since a guard that only runs in lifespan would
otherwise go completely untested by the existing suite. These tests call
the pure check function directly, plus one that drives the actual lifespan
context manager to prove it is really wired in.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.main import _DEFAULT_JWT_SECRET_KEY, _refuse_default_secret_in_production, lifespan


def test_refuses_default_secret_when_debug_is_false():
    with patch.object(settings, "jwt_secret_key", _DEFAULT_JWT_SECRET_KEY), \
         patch.object(settings, "debug", False):
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            _refuse_default_secret_in_production()


def test_allows_default_secret_when_debug_is_true():
    """Local development with DEBUG=true is allowed to use the default --
    the guard is about accidentally running a real deployment with it."""
    with patch.object(settings, "jwt_secret_key", _DEFAULT_JWT_SECRET_KEY), \
         patch.object(settings, "debug", True):
        _refuse_default_secret_in_production()  # must not raise


def test_allows_a_real_secret_when_debug_is_false():
    with patch.object(settings, "jwt_secret_key", "a-real-random-secret-value"), \
         patch.object(settings, "debug", False):
        _refuse_default_secret_in_production()  # must not raise


def test_allows_a_real_secret_when_debug_is_true():
    with patch.object(settings, "jwt_secret_key", "a-real-random-secret-value"), \
         patch.object(settings, "debug", True):
        _refuse_default_secret_in_production()  # must not raise


@pytest.mark.asyncio
async def test_lifespan_itself_raises_before_create_all_tables():
    """Proves the guard is actually wired into lifespan, not just a
    standalone function nothing calls -- and that it runs before
    create_all_tables, not after."""
    with patch.object(settings, "jwt_secret_key", _DEFAULT_JWT_SECRET_KEY), \
         patch.object(settings, "debug", False), \
         patch("app.main.create_all_tables", new=AsyncMock()) as mock_create_tables:
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            async with lifespan(app=None):
                pass
        mock_create_tables.assert_not_awaited()
