"""Retries, idempotency, permanent errors, dead-lettering and cancellation of queue-driven ingestion.

No AWS: fake queue, fake blob store, in-memory SQLite, patched ingesters.
"""
import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models.ingest_job import IngestJob, IngestJobStatusValue as S
from app.services.blobs import BlobError
from app.services.ingestion import runner
from app.services.queueing import IngestMessage, ReceivedMessage


class FakeQueue:
    def __init__(self):
        self.deleted, self.visibility = [], []

    def delete(self, receipt):
        self.deleted.append(receipt)

    def change_visibility(self, receipt, seconds):
        self.visibility.append((receipt, seconds))


class FakeBlobs:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.deleted = []

    def fetch_to_path(self, key, dest):
        if key not in self.objects:
            raise BlobError("Object not found")
        dest.write_bytes(self.objects[key])

    def delete(self, key):
        self.deleted.append(key)


@pytest.fixture
async def sessions(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(runner, "AsyncSessionLocal", factory)
    monkeypatch.setattr(runner, "engine", engine)
    monkeypatch.setattr(settings, "ingest_max_attempts", 3)
    monkeypatch.setattr(settings, "ingest_retry_base_delay_s", 10)
    monkeypatch.setattr(settings, "ingest_retry_max_delay_s", 100)
    yield factory
    await engine.dispose()


async def add_job(factory, job_id="j1", **kw):
    async with factory() as session:
        session.add(IngestJob(id=job_id, source_type=kw.pop("source_type", "web"), **kw))
        await session.commit()


async def job(factory, job_id="j1"):
    async with factory() as session:
        return await session.get(IngestJob, job_id)


def web_msg(job_id="j1"):
    return IngestMessage(job_id=job_id, source_type="web", url="https://example.com/secret?token=abc",
                         correlation_id="req-1")


def recv(message, count=1, receipt="r1"):
    return ReceivedMessage(receipt, count, message)


async def test_success_marks_done_and_acks(sessions):
    await add_job(sessions, status=S.queued)
    q = FakeQueue()
    with patch.object(runner, "ingest_web", AsyncMock(return_value="src-1")):
        assert await runner.process_message(recv(web_msg()), q, FakeBlobs()) == "done"
    j = await job(sessions)
    assert (j.status, j.source_id, j.attempts, j.error, j.lease_until) == (S.done, "src-1", 1, None, None)
    assert j.dedupe_key and q.deleted == ["r1"]


async def test_duplicate_delivery_of_finished_job_is_acked_without_running(sessions):
    await add_job(sessions, status=S.done, source_id="src-1")
    q, ingest = FakeQueue(), AsyncMock()
    with patch.object(runner, "ingest_web", ingest):
        assert await runner.process_message(recv(web_msg()), q, FakeBlobs()) == "duplicate"
    ingest.assert_not_awaited()
    assert q.deleted == ["r1"]


async def test_live_lease_blocks_second_worker_but_expired_lease_is_reclaimed(sessions):
    await add_job(sessions, status=S.running, lease_until=runner._now() + timedelta(minutes=5), attempts=1)
    q, ingest = FakeQueue(), AsyncMock(return_value="src-2")
    with patch.object(runner, "ingest_web", ingest):
        assert await runner.process_message(recv(web_msg()), q, FakeBlobs()) == "duplicate"
        ingest.assert_not_awaited()
        async with sessions() as s, s.begin():
            (await s.get(IngestJob, "j1")).lease_until = runner._now() - timedelta(seconds=1)
        assert await runner.process_message(recv(web_msg(), count=2, receipt="r2"), q, FakeBlobs()) == "done"
    j = await job(sessions)
    assert j.status == S.done and j.attempts == 2


async def test_transient_failure_backs_off_exponentially_and_keeps_message(sessions):
    await add_job(sessions, status=S.queued)
    q = FakeQueue()
    with patch.object(runner, "ingest_web", AsyncMock(side_effect=ConnectionError("boom https://x.test/y"))):
        assert await runner.process_message(recv(web_msg(), count=1), q, FakeBlobs()) == "retry"
        assert await runner.process_message(recv(web_msg(), count=2), q, FakeBlobs()) == "retry"
    assert q.deleted == [] and q.visibility == [("r1", 10), ("r1", 20)]
    j = await job(sessions)
    assert (j.status, j.phase, j.error) == (S.queued, "retrying", "ConnectionError")  # no message text


async def test_final_attempt_marks_error_and_leaves_message_for_dlq(sessions):
    await add_job(sessions, status=S.queued)
    q = FakeQueue()
    with patch.object(runner, "ingest_web", AsyncMock(side_effect=RuntimeError("down"))):
        assert await runner.process_message(recv(web_msg(), count=3), q, FakeBlobs()) == "dead_letter"
    assert q.deleted == [] and q.visibility == [("r1", 0)]
    j = await job(sessions)
    assert j.status == S.error and "dead-letter" in j.message


async def test_permanent_error_is_not_retried_and_url_is_scrubbed(sessions):
    await add_job(sessions, status=S.queued)
    q = FakeQueue()
    err = ValueError("Could not extract readable content from https://example.com/secret?token=abc")
    with patch.object(runner, "ingest_web", AsyncMock(side_effect=err)):
        assert await runner.process_message(recv(web_msg(), count=1), q, FakeBlobs()) == "failed"
    assert q.deleted == ["r1"]
    j = await job(sessions)
    assert j.status == S.error and "token=abc" not in j.error and "<url>" in j.error


async def test_cancellation_releases_message_and_resets_job(sessions):
    await add_job(sessions, status=S.queued)
    q = FakeQueue()
    started = asyncio.Event()

    async def hang(url):
        started.set()
        await asyncio.sleep(60)

    with patch.object(runner, "ingest_web", hang):
        task = asyncio.create_task(runner.process_message(recv(web_msg()), q, FakeBlobs()))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert q.visibility == [("r1", 0)] and q.deleted == []
    assert (await job(sessions)).status == S.queued


async def test_timeout_is_a_retryable_failure(sessions, monkeypatch):
    await add_job(sessions, status=S.queued)
    monkeypatch.setattr(settings, "ingest_job_timeout_s", 0.05)

    async def slow(url):
        await asyncio.sleep(5)

    q = FakeQueue()
    with patch.object(runner, "ingest_web", slow):
        assert await runner.process_message(recv(web_msg()), q, FakeBlobs()) == "retry"
    assert (await job(sessions)).error == "TimeoutError"


async def test_missing_job_row_is_recreated_after_db_restore(sessions):
    q = FakeQueue()
    with patch.object(runner, "ingest_web", AsyncMock(return_value="src-9")):
        assert await runner.process_message(recv(web_msg("restored")), q, FakeBlobs()) == "done"
    assert (await job(sessions, "restored")).status == S.done


async def test_pdf_fetches_blob_ingests_and_deletes_unless_retained(sessions, monkeypatch):
    await add_job(sessions, source_type="pdf", status=S.queued)
    msg = IngestMessage(job_id="j1", source_type="pdf", storage_key="uploads/j1/source.pdf",
                        filename="a.pdf", content_type="application/pdf")
    seen = {}

    async def fake_pdf(path, filename, content_type, progress=None):
        seen["bytes"] = open(path, "rb").read()
        await progress("embedding", "x")
        return "src-pdf"

    blobs = FakeBlobs({"uploads/j1/source.pdf": b"%PDF"})
    monkeypatch.setattr(settings, "retain_uploads", False)
    with patch.object(runner, "ingest_pdf", fake_pdf):
        assert await runner.process_message(recv(msg), FakeQueue(), blobs) == "done"
    assert seen["bytes"] == b"%PDF" and blobs.deleted == ["uploads/j1/source.pdf"]

    await add_job(sessions, "j2", source_type="pdf", status=S.queued)
    kept = FakeBlobs({"uploads/j1/source.pdf": b"%PDF"})
    monkeypatch.setattr(settings, "retain_uploads", True)
    msg2 = IngestMessage(job_id="j2", source_type="pdf", storage_key="uploads/j1/source.pdf")
    with patch.object(runner, "ingest_pdf", fake_pdf):
        assert await runner.process_message(recv(msg2), FakeQueue(), kept) == "done"
    assert kept.deleted == []


async def test_missing_upload_is_permanent(sessions):
    await add_job(sessions, source_type="pdf", status=S.queued)
    msg = IngestMessage(job_id="j1", source_type="pdf", storage_key="uploads/j1/source.pdf")
    q = FakeQueue()
    assert await runner.process_message(recv(msg), q, FakeBlobs()) == "failed"
    assert q.deleted == ["r1"]


async def test_logs_and_metrics_carry_no_url_or_tokens(sessions, caplog):
    await add_job(sessions, status=S.queued)
    caplog.set_level(logging.INFO)
    with patch.object(runner, "ingest_web", AsyncMock(side_effect=RuntimeError("secret-token-123"))):
        await runner.process_message(recv(web_msg()), FakeQueue(), FakeBlobs())
    text = caplog.text
    assert "ingest_job" in text and "req-1" in text
    for forbidden in ("example.com", "token=abc", "secret-token-123"):
        assert forbidden not in text


def test_safe_error_only_exposes_value_error_text():
    assert runner.safe_error(RuntimeError("password=hunter2")) == "RuntimeError"
    assert runner.safe_error(ValueError("bad https://a.b/c?k=v ok")) == "ValueError: bad <url> ok"


async def test_redelivery_after_worker_crash_is_reclaimed_not_dropped_as_duplicate(sessions, monkeypatch):
    """The DB lease must lapse BEFORE SQS redelivers a crashed worker's message.

    SQS redelivers at receive_time + visibility. The claim happens slightly after the receive, so a lease of
    exactly `visibility` would still be live at redelivery: the message would be deleted as a 'duplicate'
    and the job would sit in `running` forever.
    """
    await add_job(sessions, status=S.queued)
    t0 = runner._now()
    monkeypatch.setattr(runner, "_now", lambda: t0)
    claim_delay = timedelta(milliseconds=300)  # time between receive and claim
    monkeypatch.setattr(runner, "_now", lambda: t0 + claim_delay)
    assert await runner.claim_job(web_msg(), "k") == runner.CLAIMED  # worker A claims, then crashes

    visibility = timedelta(seconds=settings.sqs_visibility_timeout_s)
    monkeypatch.setattr(runner, "_now", lambda: t0 + timedelta(seconds=5))
    assert await runner.claim_job(web_msg(), "k") == runner.BUSY  # a live duplicate copy is still refused
    monkeypatch.setattr(runner, "_now", lambda: t0 + visibility)  # SQS redelivers right here
    assert await runner.claim_job(web_msg(), "k") == runner.CLAIMED
