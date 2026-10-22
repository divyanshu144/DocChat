"""Queue-driven ingestion (SQS path). The local BackgroundTasks path in app/api/ingest.py is unchanged.

Delivery is at-least-once, so every step must be safe to repeat:
  * claim_job   - a finished job is acknowledged without re-running; a live lease is respected
  * source_lock - one writer per source across processes (Postgres advisory lock; the skill's
                  "multi-process writers need an external lock" requirement)
  * ingest_*    - deterministic source/chunk ids and delete-then-upsert replacement
Nothing here logs URLs, filenames, document text or exception messages.
"""
import asyncio
import re
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.telemetry import emit, request_trace
from app.models.ingest_job import IngestJob, IngestJobStatusValue
from app.services.blobs import BlobError, BlobStore
from app.services.ingestion.pdf import _file_sha256, _source_id_from_content_hash, ingest_pdf
from app.services.ingestion.web import _source_id_for_url, ingest_web
from app.services.ingestion.youtube import _extract_video_id, _source_id_for_video, ingest_youtube
from app.services.queueing import IngestMessage, JobQueue, ReceivedMessage, backoff_seconds

CLAIMED, DONE, BUSY = "claimed", "done", "busy"
_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_URL = re.compile(r"https?://\S+")


def source_key_for_url(source_type: str, url: str) -> str:
    if source_type == "youtube":
        try:
            return _source_id_for_video(_extract_video_id(url))
        except (KeyError, IndexError):
            return f"youtube-raw:{url}"[:600]
    return _source_id_for_url(url)


def source_key_for_file(path: str | Path) -> str:
    return _source_id_from_content_hash(_file_sha256(path))


def lease_seconds() -> int:
    """DB lease = 2/3 of the SQS visibility timeout; the heartbeat renews both every 1/3.

    The lease must lapse BEFORE SQS redelivers a crashed worker's message (receive + visibility), or
    that redelivery would look like a live duplicate and be dropped, stranding the job in `running`.
    """
    return settings.sqs_visibility_timeout_s * 2 // 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


def safe_error(exc: BaseException) -> str:
    """Class name always; message only for ValueError (our own user-actionable text), URLs removed."""
    if isinstance(exc, ValueError):
        return f"{type(exc).__name__}: {_URL.sub('<url>', str(exc))[:200]}"
    return type(exc).__name__


def is_permanent(exc: BaseException) -> bool:
    """Retrying cannot help: bad/unsupported input or a missing upload."""
    return isinstance(exc, (ValueError, BlobError))


async def claim_job(message: IngestMessage, source_key: str | None) -> str:
    """Atomically move the job to running unless it is already done or leased by a live worker."""
    now = _now()
    async with AsyncSessionLocal() as session, session.begin():
        if (await session.connection()).dialect.name == "postgresql":
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                                  {"k": f"job:{message.job_id}"})
        job = await session.get(IngestJob, message.job_id)
        if job is None:  # e.g. database restored from backup, then the queue redriven
            job = IngestJob(id=message.job_id, source_type=message.source_type, attempts=0)
            session.add(job)
        elif job.status == IngestJobStatusValue.done:
            return DONE
        elif job.status == IngestJobStatusValue.running and (_aware(job.lease_until) or now) > now:
            return BUSY
        job.status = IngestJobStatusValue.running
        job.phase, job.message, job.error = "starting", "Starting ingest", None
        job.attempts = (job.attempts or 0) + 1
        job.dedupe_key = job.dedupe_key or source_key
        job.lease_until = now + timedelta(seconds=lease_seconds())
    return CLAIMED


async def update_job(job_id: str, **values) -> None:
    async with AsyncSessionLocal() as session, session.begin():
        job = await session.get(IngestJob, job_id)
        if job is not None:
            for key, value in values.items():
                setattr(job, key, value)


@asynccontextmanager
async def source_lock(key: str):
    """Serialise writers of one source across processes. No-op off PostgreSQL (single process)."""
    if engine.dialect.name != "postgresql":
        yield
        return
    async with engine.connect() as conn:
        params = {"k": f"source:{key}"}
        await conn.execute(text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"), params)
        try:
            yield
        finally:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), params)
            except BaseException:
                # A session lock outlives rollback; dropping the socket is what releases it.
                await asyncio.shield(conn.invalidate())
                raise


@asynccontextmanager
async def _heartbeat(queue: JobQueue, receipt: str, job_id: str):
    """Keep the message invisible and the lease alive while a long job runs."""
    interval = max(settings.sqs_visibility_timeout_s / 3, 5)

    async def beat():
        while True:
            await asyncio.sleep(interval)
            with suppress(Exception):  # a missed beat is recovered by redelivery
                await asyncio.to_thread(queue.change_visibility, receipt, settings.sqs_visibility_timeout_s)
                await update_job(job_id, lease_until=_now() + timedelta(seconds=lease_seconds()))

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _ingest(message: IngestMessage, blobs: BlobStore, source_key: str | None) -> str:
    async def progress(phase: str, text_: str) -> None:
        await update_job(message.job_id, phase=phase, message=text_)

    if message.source_type != "pdf":
        key = source_key or source_key_for_url(message.source_type, message.url)
        async with source_lock(key):
            if message.source_type == "youtube":
                return await ingest_youtube(message.url)
            return await ingest_web(message.url)

    suffix = Path(message.storage_key).suffix
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / f"source{suffix}"
        await asyncio.to_thread(blobs.fetch_to_path, message.storage_key, local)
        key = source_key or await asyncio.to_thread(source_key_for_file, local)
        if not source_key:
            await update_job(message.job_id, dedupe_key=key)  # known only after the download
        async with source_lock(key):
            return await ingest_pdf(str(local), message.filename or "upload",
                                    message.content_type or "application/pdf", progress=progress)


def _correlation(message: IngestMessage) -> str | None:
    cid = message.correlation_id
    return cid if cid and _ID.fullmatch(cid) else None


def _emit(message: IngestMessage, outcome: str, started: float, received: ReceivedMessage,
          error_type: str | None = None) -> None:
    emit({"event": "ingest_job", "job_id": message.job_id, "source_type": message.source_type,
          "outcome": outcome, "receive_count": received.receive_count,
          "duration_s": time.perf_counter() - started, "error_type": error_type})


async def process_message(received: ReceivedMessage, queue: JobQueue, blobs: BlobStore) -> str:
    """Run one delivered message. Returns the outcome label; acknowledges (deletes) only when it is final."""
    message = received.message
    started = time.perf_counter()
    with request_trace(_correlation(message), transport="worker"):
        existing_key = None
        try:
            if message.source_type != "pdf":
                existing_key = source_key_for_url(message.source_type, message.url)
            claim = await claim_job(message, existing_key)
        except Exception:
            # Cannot read job state (database down): leave the message to be redelivered.
            await asyncio.to_thread(queue.change_visibility, received.receipt, backoff_seconds(received.receive_count))
            _emit(message, "retry", started, received, "ClaimFailed")
            return "retry"
        if claim in (DONE, BUSY):
            await asyncio.to_thread(queue.delete, received.receipt)
            _emit(message, "duplicate", started, received)
            return "duplicate"

        try:
            async with _heartbeat(queue, received.receipt, message.job_id):
                async with asyncio.timeout(settings.ingest_job_timeout_s):
                    source_id = await _ingest(message, blobs, existing_key)
            await update_job(message.job_id, status=IngestJobStatusValue.done, phase="done",
                             message="Ingested", source_id=source_id, error=None, lease_until=None)
            if message.storage_key and not settings.retain_uploads:
                with suppress(Exception):
                    await asyncio.to_thread(blobs.delete, message.storage_key)
            await asyncio.to_thread(queue.delete, received.receipt)
            _emit(message, "done", started, received)
            return "done"
        except asyncio.CancelledError:
            # Shutdown or cancellation: hand the message straight back to another worker.
            await asyncio.shield(_release(message, queue, received))
            _emit(message, "cancelled", started, received)
            raise
        except Exception as exc:
            return await _fail(exc, message, queue, received, started)


async def _release(message: IngestMessage, queue: JobQueue, received: ReceivedMessage) -> None:
    with suppress(Exception):
        await update_job(message.job_id, status=IngestJobStatusValue.queued, phase="queued",
                         message="Interrupted; will retry", lease_until=None)
    with suppress(Exception):
        await asyncio.to_thread(queue.change_visibility, received.receipt, 0)


async def _fail(exc: Exception, message: IngestMessage, queue: JobQueue, received: ReceivedMessage,
                started: float) -> str:
    error = safe_error(exc)
    error_type = type(exc).__name__
    if is_permanent(exc):
        await update_job(message.job_id, status=IngestJobStatusValue.error, phase="error",
                         message="Ingest failed", error=error, lease_until=None)
        await asyncio.to_thread(queue.delete, received.receipt)  # retrying cannot succeed
        _emit(message, "failed", started, received, error_type)
        return "failed"
    if received.receive_count >= settings.ingest_max_attempts:
        # Leave the message: the queue's redrive policy moves it to the DLQ on its next delivery.
        await update_job(message.job_id, status=IngestJobStatusValue.error, phase="error",
                         message="Ingest failed; retries exhausted, moved to dead-letter queue",
                         error=error, lease_until=None)
        with suppress(Exception):
            await asyncio.to_thread(queue.change_visibility, received.receipt, 0)
        _emit(message, "dead_letter", started, received, error_type)
        return "dead_letter"
    delay = backoff_seconds(received.receive_count)
    await update_job(message.job_id, status=IngestJobStatusValue.queued, phase="retrying",
                     message=f"Attempt {received.receive_count} failed; retrying in {delay}s",
                     error=error, lease_until=None)
    await asyncio.to_thread(queue.change_visibility, received.receipt, delay)
    _emit(message, "retry", started, received, error_type)
    return "retry"
