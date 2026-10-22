"""Rotating database password: cache, forced refresh, retry after auth failure, no secret in errors or logs."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.db_connect import make_async_creator
from app.core.db_secret import DbPasswordProvider, SecretReadError


class FakeSecrets:
    """Stands in for Secrets Manager; `rotate()` changes the value like an RDS rotation."""

    def __init__(self, password="old-pw"):
        self.password, self.calls = password, 0

    def rotate(self, new):
        self.password = new

    def get_secret_value(self, SecretId):
        self.calls += 1
        return {"SecretString": json.dumps({"username": "docchat", "password": self.password})}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


async def test_value_is_cached_until_ttl_then_refetched():
    fake, clock = FakeSecrets(), Clock()
    p = DbPasswordProvider("arn", client=fake, ttl=60, clock=clock)
    assert await p.get() == "old-pw" and await p.get() == "old-pw"
    assert fake.calls == 1
    fake.rotate("new-pw")
    assert await p.get() == "old-pw"  # still cached
    clock.now = 61
    assert await p.get() == "new-pw" and fake.calls == 2


async def test_force_refresh_bypasses_the_cache():
    fake = FakeSecrets()
    p = DbPasswordProvider("arn", client=fake, ttl=3600)
    await p.get()
    fake.rotate("new-pw")
    assert await p.get(force=True) == "new-pw"


async def test_read_errors_never_include_secret_content_or_ids(caplog):
    class Broken:
        def get_secret_value(self, SecretId):
            raise RuntimeError("AccessDenied for arn:aws:secretsmanager:eu-west-1:1:secret:x password=hunter2")

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(SecretReadError) as err:
            await DbPasswordProvider("arn", client=Broken()).get()
    assert "hunter2" not in str(err.value) and "arn:aws" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert "hunter2" not in caplog.text


async def test_malformed_secret_is_a_clean_error():
    class Bad:
        def get_secret_value(self, SecretId):
            return {"SecretString": "not json with s3cret"}

    with pytest.raises(SecretReadError) as err:
        await DbPasswordProvider("arn", client=Bad()).get()
    assert "s3cret" not in str(err.value)


CFG = SimpleNamespace(database_host="db", database_port=5432, database_user="docchat",
                      database_name="docchat", database_ssl="require")


async def test_creator_retries_once_with_a_fresh_password_after_rotation():
    fake = FakeSecrets("old-pw")
    provider = DbPasswordProvider("arn", client=fake, ttl=3600)
    await provider.get()  # cached before the rotation
    fake.rotate("new-pw")
    attempts = []

    async def fake_connect(**kw):
        attempts.append(kw["password"])
        if kw["password"] != "new-pw":
            raise asyncpg.exceptions.InvalidPasswordError("password authentication failed")
        return "connection"

    with patch.object(asyncpg, "connect", fake_connect):
        assert await make_async_creator(CFG, provider)() == "connection"
    assert attempts == ["old-pw", "new-pw"]


async def test_creator_gives_up_after_one_retry_and_other_errors_are_not_retried():
    provider = DbPasswordProvider("arn", client=FakeSecrets(), ttl=3600)
    attempts = []

    async def always_bad(**kw):
        attempts.append(kw["password"])
        raise asyncpg.exceptions.InvalidPasswordError("nope")

    with patch.object(asyncpg, "connect", always_bad):
        with pytest.raises(asyncpg.exceptions.InvalidPasswordError):
            await make_async_creator(CFG, provider)()
    assert len(attempts) == 2

    attempts.clear()

    async def down(**kw):
        attempts.append(1)
        raise OSError("connection refused")

    with patch.object(asyncpg, "connect", down):
        with pytest.raises(OSError):
            await make_async_creator(CFG, provider)()
    assert attempts == [1]


async def test_creator_passes_ssl_and_connection_parts():
    seen = {}

    async def capture(**kw):
        seen.update(kw)
        return "c"

    provider = DbPasswordProvider("arn", client=FakeSecrets(), ttl=3600)
    with patch.object(asyncpg, "connect", capture):
        await make_async_creator(CFG, provider)()
    assert (seen["host"], seen["port"], seen["user"], seen["database"], seen["ssl"]) == (
        "db", 5432, "docchat", "docchat", "require")


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_config_secret_arn_builds_a_url_without_a_password():
    s = make(database_host="db", database_password_secret_arn="arn:x", database_ssl="require")
    assert s.database_url == "postgresql+asyncpg://docchat@db:5432/docchat?ssl=require"
    assert "arn" not in s.database_url


def test_config_rejects_both_neither_and_arn_without_host():
    with pytest.raises(ValidationError, match="not both"):
        make(database_host="db", database_password="x", database_password_secret_arn="arn")
    with pytest.raises(ValidationError, match="required"):
        make(database_host="db")
    with pytest.raises(ValidationError, match="needs DATABASE_HOST"):
        make(database_password_secret_arn="arn")


def test_env_password_path_is_unchanged_for_local_use():
    s = make(database_host="db", database_password="pw")
    assert s.database_url == "postgresql+asyncpg://docchat:pw@db:5432/docchat"
