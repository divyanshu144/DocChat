"""API enqueue path (QUEUE_BACKEND=sqs): references only, dedupe, failure handling. Local path covered by test_api_ingest."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models.ingest_job import IngestJob, IngestJobStatusValue as S
from app.services.ingestion import enqueue
from app.services.queueing import IngestMessage, ReceivedMessage


class Queue:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, message):
        if self.fail:
            raise RuntimeError("sqs down https://sqs.test/secret")
        self.sent.append(message)


class Blobs:
    def __init__(self):
        self.put = []

    def put_file(self, key, path):
        self.put.append((key, open(path, "rb").read()))


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def wire(monkeypatch, queue, blobs=None):
    monkeypatch.setattr(enqueue, "get_queue", lambda: queue)
    monkeypatch.setattr(enqueue, "get_blob_store", lambda: blobs)


async def test_url_job_sends_reference_only(db, monkeypatch):
    q = Queue()
    wire(monkeypatch, q)
    job_id, status, phase, message = await enqueue.enqueue_ingest(db, "web", url="https://example.com/a?token=zzz")
    assert status == phase == "queued" and "example.com" not in message and "zzz" not in message
    sent = q.sent[0]
    assert (sent.job_id, sent.source_type, sent.url) == (job_id, "web", "https://example.com/a?token=zzz")
    row = await db.get(IngestJob, job_id)
    assert row.dedupe_key and "zzz" not in (row.message + (row.error or ""))


async def test_identical_active_job_is_deduplicated_but_finished_one_is_not(db, monkeypatch):
    q = Queue()
    wire(monkeypatch, q)
    first = await enqueue.enqueue_ingest(db, "web", url="https://example.com/a?b=1&a=2")
    again = await enqueue.enqueue_ingest(db, "web", url="https://EXAMPLE.com/a?a=2&b=1")  # same canonical URL
    assert again[0] == first[0] and len(q.sent) == 1
    row = await db.get(IngestJob, first[0])
    row.status = S.done
    await db.commit()
    third = await enqueue.enqueue_ingest(db, "web", url="https://example.com/a?a=2&b=1")
    assert third[0] != first[0] and len(q.sent) == 2  # explicit refresh of a finished source is allowed


async def test_dedupe_window_expires(db, monkeypatch):
    q = Queue()
    wire(monkeypatch, q)
    monkeypatch.setattr(settings, "ingest_dedupe_window_s", 0)
    a = await enqueue.enqueue_ingest(db, "web", url="https://example.com/x")
    await asyncio.sleep(1.1)  # sqlite timestamps have 1 s resolution
    b = await enqueue.enqueue_ingest(db, "web", url="https://example.com/x")
    assert a[0] != b[0]


async def test_pdf_is_stored_by_job_key_not_filename(db, monkeypatch, tmp_path):
    q, blobs = Queue(), Blobs()
    wire(monkeypatch, q, blobs)
    f = tmp_path / "x.bin"
    f.write_bytes(b"%PDF-1.7 body")
    job_id, *_ = await enqueue.enqueue_ingest(db, "pdf", tmp_path=str(f), filename="Quarterly Secrets.pdf",
                                              content_type="application/pdf")
    key, data = blobs.put[0]
    assert key.endswith(f"{job_id}/source.pdf") and "Quarterly" not in key and data == b"%PDF-1.7 body"
    msg: IngestMessage = q.sent[0]
    assert msg.storage_key == key and msg.filename == "Quarterly Secrets.pdf"
    same = await enqueue.enqueue_ingest(db, "pdf", tmp_path=str(f), filename="copy.pdf", content_type="application/pdf")
    assert same[0] == job_id and len(blobs.put) == 1  # identical bytes while active: no second upload


async def test_send_failure_creates_no_row_and_returns_503_without_leaking(db, monkeypatch):
    wire(monkeypatch, Queue(fail=True))
    with pytest.raises(HTTPException) as err:
        await enqueue.enqueue_ingest(db, "web", url="https://example.com/z")
    assert err.value.status_code == 503 and "sqs.test" not in str(err.value.detail)
    assert (await db.execute(select(IngestJob))).scalars().all() == []


def test_endpoint_uses_sqs_branch(monkeypatch):
    """Smoke the real route in sqs mode; local-mode behaviour is covered by test_api_ingest."""
    from fastapi.testclient import TestClient
    from app.core.deps import get_current_user
    from app.main import app

    async def fake_enqueue(db, source_type, **kw):
        return "job-9", "queued", "queued", "Queued web ingest"

    monkeypatch.setattr(settings, "queue_backend", "sqs")
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        with patch("app.api.ingest.enqueue_ingest", fake_enqueue):
            r = TestClient(app).post("/api/v1/ingest/web/jobs", json={"url": "https://example.com"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 202 and r.json()["job_id"] == "job-9"


# ---------- ordering: send first, then insert the row ----------
from datetime import datetime, timedelta, timezone  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession as _AS  # noqa: E402
from app.services.ingestion import runner  # noqa: E402


@pytest.fixture
async def stack(monkeypatch):
    """One in-memory database shared by the API side (`db`) and the worker side (runner)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=_AS, expire_on_commit=False)
    monkeypatch.setattr(runner, "AsyncSessionLocal", factory)
    monkeypatch.setattr(runner, "engine", engine)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


class Q2(Queue):
    def receive_one(self):
        return ReceivedMessage("r1", 1, self.sent[0])


class Acks:
    def __init__(self):
        self.deleted = []

    def delete(self, receipt):
        self.deleted.append(receipt)

    def change_visibility(self, receipt, seconds):
        pass


async def test_crash_after_send_before_insert_the_worker_still_runs_the_job_and_creates_the_row(stack, monkeypatch):
    session, factory = stack
    q = Q2()
    wire(monkeypatch, q)

    async def boom(db, values):
        raise RuntimeError("process died here https://secret.test/x")

    monkeypatch.setattr(enqueue, "_insert_job_row", boom)
    with pytest.raises(HTTPException) as err:
        await enqueue.enqueue_ingest(session, "web", url="https://example.com/doc")
    assert err.value.status_code == 503 and "secret.test" not in str(err.value.detail)
    assert len(q.sent) == 1  # the message is out
    assert (await session.execute(select(IngestJob))).scalars().all() == []  # and no row exists

    with patch.object(runner, "ingest_web", AsyncMock(return_value="src-1")):
        outcome = await runner.process_message(q.receive_one(), Acks(), object())
    assert outcome == "done"
    row = await session.get(IngestJob, q.sent[0].job_id)
    assert (row.source_type, row.status, row.attempts, row.source_id) == ("web", S.done, 1, "src-1")
    assert row.dedupe_key


async def test_worker_created_row_has_source_type_dedupe_key_and_attempts_for_url_and_pdf(stack, monkeypatch, tmp_path):
    session, factory = stack
    web = IngestMessage(job_id="w1", source_type="web", url="https://example.com/a")
    assert await runner.claim_job(web, runner.source_key_for_url("web", web.url)) == runner.CLAIMED
    row = await session.get(IngestJob, "w1")
    assert (row.source_type, row.attempts, row.status) == ("web", 1, S.running) and row.dedupe_key

    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-body")
    pdf = IngestMessage(job_id="p1", source_type="pdf", storage_key="uploads/p1/source.pdf", filename="a.pdf")

    class Blobs:
        def fetch_to_path(self, key, dest):
            dest.write_bytes(f.read_bytes())

        def delete(self, key):
            pass

    async def fake_pdf(path, filename, content_type, progress=None):
        return "src-pdf"

    with patch.object(runner, "ingest_pdf", fake_pdf):
        assert await runner.process_message(ReceivedMessage("r", 1, pdf), Acks(), Blobs()) == "done"
    row = await session.get(IngestJob, "p1")
    assert (row.source_type, row.attempts, row.status) == ("pdf", 1, S.done)
    assert row.dedupe_key == runner.source_key_for_file(f)  # filled in once the content hash is known


async def test_insert_conflict_with_a_worker_created_row_is_ignored(stack):
    session, factory = stack
    msg = IngestMessage(job_id="same", source_type="web", url="https://example.com/c")
    await runner.claim_job(msg, "k")  # the worker got there first
    async with factory() as s2, s2.begin():
        (await s2.get(IngestJob, "same")).status = S.done
    await enqueue._insert_job_row(session, dict(
        id="same", source_type="web", status=S.queued, phase="queued", message="Queued", dedupe_key="k", attempts=0))
    row = await session.get(IngestJob, "same")
    await session.refresh(row)
    assert row.status == S.done and row.attempts == 1  # nothing was overwritten, nothing raised


async def test_dedupe_returns_the_worker_created_job(stack, monkeypatch):
    session, factory = stack
    q = Q2()
    wire(monkeypatch, q)
    url = "https://example.com/dedupe"
    await runner.claim_job(IngestMessage(job_id="wk", source_type="web", url=url),
                           runner.source_key_for_url("web", url))
    job_id, status, *_ = await enqueue.enqueue_ingest(session, "web", url=url)
    assert job_id == "wk" and status == "running" and q.sent == []


async def test_stale_queued_job_does_not_block_a_new_submission_but_a_fresh_one_does(stack, monkeypatch):
    session, factory = stack
    q = Q2()
    wire(monkeypatch, q)
    monkeypatch.setattr(settings, "ingest_queued_stale_s", 600)
    monkeypatch.setattr(settings, "ingest_dedupe_window_s", 3600)
    url = "https://example.com/stale"
    first = await enqueue.enqueue_ingest(session, "web", url=url)
    again = await enqueue.enqueue_ingest(session, "web", url=url)
    assert again[0] == first[0]  # fresh queued job: reused

    row = await session.get(IngestJob, first[0])
    row.updated_at = datetime.now(timezone.utc) - timedelta(seconds=601)
    await session.commit()
    third = await enqueue.enqueue_ingest(session, "web", url=url)
    assert third[0] != first[0] and len(q.sent) == 2  # dead row ignored

    old_running = await session.get(IngestJob, third[0])
    old_running.status = S.running
    old_running.updated_at = datetime.now(timezone.utc) - timedelta(seconds=1200)  # older than stale, inside window
    await session.commit()
    assert (await enqueue.enqueue_ingest(session, "web", url=url))[0] == third[0]  # running jobs keep the window rule
