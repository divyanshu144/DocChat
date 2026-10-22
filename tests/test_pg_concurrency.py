"""Concurrency guarantees that SQLite cannot show: advisory locks, row locking, DDL races, password rotation.

Run with a throwaway database, for example:
    docker run -d -p 55432:5432 -e POSTGRES_PASSWORD=pw postgres:16-alpine
    (create a database whose name contains "test", then)
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@127.0.0.1:55432/docchat_test pytest -m pg

Skipped when TEST_DATABASE_URL is unset or unreachable, unless REQUIRE_PG=1, which CI sets so a broken service
cannot hide as a pass. The database name must contain "test": these tests rebuild tables.
"""
import asyncio
import json
import os
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.conversation  # noqa: F401
import app.models.ingest_job  # noqa: F401
import app.models.refresh_token  # noqa: F401
import app.models.user  # noqa: F401
from app.core import database
from app.core.config import settings
from app.core.database import Base
from app.core.db_connect import make_async_creator
from app.core.db_secret import DbPasswordProvider
from app.models.ingest_job import IngestJob, IngestJobStatusValue as S
from app.services.ingestion import runner
from app.services.queueing import IngestMessage

pytestmark = pytest.mark.pg
URL = os.environ.get("TEST_DATABASE_URL", "")


def _unavailable(reason: str):
    if os.environ.get("REQUIRE_PG") == "1":
        pytest.fail(f"REQUIRE_PG=1 but {reason}")
    pytest.skip(reason)


@pytest.fixture
async def pg(monkeypatch):
    if not URL:
        _unavailable("TEST_DATABASE_URL is not set")
    if "test" not in (make_url(URL).database or ""):
        _unavailable("refusing to use a database whose name does not contain 'test'")
    engine = create_async_engine(URL, pool_size=10)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        await engine.dispose()
        _unavailable("PostgreSQL is not reachable")
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(runner, "AsyncSessionLocal", factory)
    monkeypatch.setattr(runner, "engine", engine)
    yield SimpleNamespace(engine=engine, factory=factory)
    await engine.dispose()


def web(job_id="j1"):
    return IngestMessage(job_id=job_id, source_type="web", url="https://example.com/a")


async def test_two_workers_claiming_one_job_exactly_one_wins(pg):
    async with pg.factory() as s, s.begin():
        s.add(IngestJob(id="j1", source_type="web", status=S.queued))
    for round_ in range(5):
        async with pg.factory() as s, s.begin():
            job = await s.get(IngestJob, "j1")
            job.status, job.lease_until, job.attempts = S.queued, None, 0
        results = await asyncio.gather(*[runner.claim_job(web(), "k") for _ in range(8)])
        assert sorted(results) == [runner.BUSY] * 7 + [runner.CLAIMED], (round_, results)
    async with pg.factory() as s:
        assert (await s.get(IngestJob, "j1")).attempts == 1


async def test_workers_creating_the_same_missing_row_do_not_crash_or_double_claim(pg):
    results = await asyncio.gather(*[runner.claim_job(web("fresh"), "k") for _ in range(6)],
                                   return_exceptions=True)
    assert [r for r in results if r == runner.CLAIMED] == [runner.CLAIMED], results
    assert not [r for r in results if isinstance(r, BaseException)], results


async def test_source_lock_serialises_writers_of_one_source_but_not_different_sources(pg):
    log = []

    async def writer(key, name, hold=0.25):
        async with runner.source_lock(key):
            log.append(("in", name, time.monotonic()))
            await asyncio.sleep(hold)
            log.append(("out", name, time.monotonic()))

    await asyncio.gather(writer("same", "a"), writer("same", "b"), writer("same", "c"))
    events = [(kind, name) for kind, name, _ in sorted(log, key=lambda e: e[2])]
    for i in range(0, 6, 2):  # strictly in, out, in, out, ...
        assert events[i][0] == "in" and events[i + 1] == ("out", events[i][1])

    log.clear()
    start = time.monotonic()
    await asyncio.gather(writer("one", "x"), writer("two", "y"))
    assert time.monotonic() - start < 0.45  # different sources ran side by side


async def test_source_lock_is_released_when_the_holder_is_cancelled(pg):
    holder_in = asyncio.Event()

    async def holder():
        async with runner.source_lock("k"):
            holder_in.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(holder())
    await holder_in.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(5):  # would hang forever if the session lock leaked
        async with runner.source_lock("k"):
            pass


async def test_lease_expiry_versus_redelivery_on_postgres(pg, monkeypatch):
    async with pg.factory() as s, s.begin():
        s.add(IngestJob(id="j1", source_type="web", status=S.queued))
    t0 = runner._now()
    monkeypatch.setattr(runner, "_now", lambda: t0 + timedelta(milliseconds=300))
    assert await runner.claim_job(web(), "k") == runner.CLAIMED  # worker A claims, then dies
    visibility = timedelta(seconds=settings.sqs_visibility_timeout_s)
    monkeypatch.setattr(runner, "_now", lambda: t0 + timedelta(seconds=5))
    assert await runner.claim_job(web(), "k") == runner.BUSY  # a live duplicate copy is refused
    monkeypatch.setattr(runner, "_now", lambda: t0 + visibility)  # SQS redelivers here
    assert await runner.claim_job(web(), "k") == runner.CLAIMED


async def test_concurrent_startup_ddl_is_serialised_and_migrations_apply(pg, monkeypatch):
    old_table = ("CREATE TABLE ingest_jobs (id VARCHAR PRIMARY KEY, source_type VARCHAR(50) NOT NULL,"
                 " status VARCHAR, phase VARCHAR(100), message TEXT, source_id VARCHAR, error TEXT,"
                 " created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())")
    async with pg.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text(old_table))  # a database from before the new columns existed
    monkeypatch.setattr(database, "engine", pg.engine)
    await asyncio.gather(*[database.create_all_tables() for _ in range(4)])  # four API tasks starting together
    async with pg.engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='ingest_jobs'"))
        cols = {r[0] for r in rows}
    assert {"attempts", "dedupe_key", "lease_until"} <= cols


async def test_password_rotation_survives_on_real_postgres(pg):
    """Change the role's password under a live pool, as an RDS rotation does, and reconnect via the provider."""
    parsed = make_url(URL)
    original = parsed.password
    secret = {"value": original}

    class Fake:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({"password": secret["value"]})}

    provider = DbPasswordProvider("arn", client=Fake(), ttl=3600)
    cfg = SimpleNamespace(database_host=parsed.host, database_port=parsed.port or 5432,
                          database_user=parsed.username, database_name=parsed.database, database_ssl="")
    bare = f"postgresql+asyncpg://{quote(parsed.username)}@{parsed.host}:{parsed.port}/{parsed.database}"
    engine = create_async_engine(bare, async_creator=make_async_creator(cfg, provider), pool_pre_ping=True)
    rotated = "rotated-pw-1"
    changed = False
    try:
        async with engine.connect() as c:
            assert (await c.execute(text("select 1"))).scalar() == 1
        async with pg.engine.begin() as admin:
            await admin.execute(text(f"ALTER USER {parsed.username} PASSWORD '{rotated}'"))
        changed = True
        secret["value"] = rotated
        await engine.dispose()  # pooled connections are gone; the provider still caches the old password
        async with engine.connect() as c:
            assert (await c.execute(text("select 1"))).scalar() == 1
    finally:
        if changed:
            restore = create_async_engine(
                f"postgresql+asyncpg://{quote(parsed.username)}:{rotated}@{parsed.host}:{parsed.port}/{parsed.database}")
            async with restore.begin() as conn:
                await conn.execute(text(f"ALTER USER {parsed.username} PASSWORD '{original}'"))
            await restore.dispose()
        await engine.dispose()
