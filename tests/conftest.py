"""Test-session defaults applied before anything imports `app`.

pytest loads conftest before collecting test modules, which is the only window
in which these take effect — `app.core.config.settings` is a module-level
singleton, so by the first `from app...` the values are already frozen.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.core.rate_limit import rate_limiter
    rate_limiter._buckets.clear()
    yield
    rate_limiter._buckets.clear()

# A LANGSMITH_API_KEY in .env would otherwise switch tracing on for the whole
# suite: every traced call spawns a background upload, and a key that is expired
# or wrong-region turns that into 403 log spam loud enough to bury a real
# failure. Env wins over .env in pydantic-settings, so this is authoritative.
os.environ.setdefault("LANGSMITH_TRACING", "false")


@pytest.fixture(autouse=True)
def _reset_llm_client_cache():
    """Drop the cached LLM client around every test.

    `app.services.llm` caches one client per provider for the process, but its
    connection pool binds to the event loop that created it. pytest-asyncio gives
    each test a fresh loop, so the second test to reach the real client raised
    `RuntimeError: Event loop is closed` — which made `pytest -m eval` fail four of
    eight cases for reasons that had nothing to do with the critic, and hid whichever
    real disagreements were underneath.
    """
    from app.services import llm

    llm._client = None
    llm._client_provider = None
    yield
    llm._client = None
    llm._client_provider = None
