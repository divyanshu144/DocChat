"""Long-polling ingestion worker: bounded concurrency, graceful drain, content-free metrics."""
import asyncio
import logging
import random
import time
from contextlib import suppress

from app.core.config import settings
from app.core.metrics import metrics
from app.services.blobs import BlobStore
from app.services.ingestion.runner import process_message
from app.services.queueing import JobQueue
from app.worker.protection import RENEW_EVERY_S, TaskProtection

logger = logging.getLogger("worker")


class Worker:
    def __init__(self, queue: JobQueue, blobs: BlobStore, *, concurrency: int | None = None,
                 wait_seconds: int | None = None, shutdown_timeout: float | None = None,
                 protection: TaskProtection | None = None):
        self.queue, self.blobs = queue, blobs
        self.protection = protection or TaskProtection()
        self.concurrency = concurrency or settings.worker_concurrency
        self.wait_seconds = settings.sqs_wait_seconds if wait_seconds is None else wait_seconds
        self.shutdown_timeout = shutdown_timeout or settings.worker_shutdown_timeout_s
        self.stopping = asyncio.Event()
        self.warm = False
        self.poll_errors = 0
        self._tick = time.monotonic()
        self._tasks: set[asyncio.Task] = set()

    # --- probe state, read from the HTTP thread (plain attribute reads) ---
    @property
    def alive(self) -> bool:
        """The event loop is still turning; a wedged loop stops updating the tick."""
        return time.monotonic() - self._tick < 30

    @property
    def ready(self) -> bool:
        return self.warm and not self.stopping.is_set() and self.poll_errors < 5

    def stop(self) -> None:
        self.stopping.set()

    async def _ticker(self) -> None:
        last_renew = time.monotonic()
        while True:
            self._tick = time.monotonic()
            if self._tick - last_renew >= RENEW_EVERY_S:
                last_renew = self._tick
                await self.protection.renew()
            await asyncio.sleep(2)

    async def _run_one(self, received) -> None:
        metrics.worker_inflight.inc()
        await self.protection.job_started()
        try:
            await process_message(received, self.queue, self.blobs)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Message stays invisible until its timeout, then is redelivered. Never log the exception text.
            logger.error("job_processing_failed", extra={"error_type": "UnhandledError"})
        finally:
            metrics.worker_inflight.dec()
            await asyncio.shield(self.protection.job_finished())

    async def _receive(self, free: int):
        try:
            received = await asyncio.to_thread(self.queue.receive, free, self.wait_seconds)
        except Exception:
            self.poll_errors += 1
            metrics.worker_polls.labels("error").inc()
            await self._sleep(min(2 ** self.poll_errors, 30) * random.uniform(0.5, 1.0))
            return []
        self.poll_errors = 0
        metrics.worker_polls.labels("messages" if received else "empty").inc()
        return received

    async def _sleep(self, seconds: float) -> None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.stopping.wait(), seconds)

    async def run(self) -> None:
        ticker = asyncio.create_task(self._ticker())
        try:
            while not self.stopping.is_set():
                free = self.concurrency - len(self._tasks)
                if free <= 0:
                    # All slots busy: wake on a finished job OR on a stop request (SIGTERM mid-job).
                    stop_wait = asyncio.create_task(self.stopping.wait())
                    try:
                        await asyncio.wait({*self._tasks, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        stop_wait.cancel()
                    continue
                for received in await self._receive(free):
                    if self.stopping.is_set():
                        # Received while stopping: give it straight back instead of starting work.
                        with suppress(Exception):
                            await asyncio.to_thread(self.queue.change_visibility, received.receipt, 0)
                    elif received.message is None:
                        # Poison body: not deleted, so the redrive policy moves it to the DLQ.
                        metrics.worker_polls.labels("poison").inc()
                        logger.error("poison_message_skipped")
                    else:
                        task = asyncio.create_task(self._run_one(received))
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)
            await self._drain()
        finally:
            ticker.cancel()
            with suppress(asyncio.CancelledError):
                await ticker

    async def _drain(self) -> None:
        pending = set(self._tasks)
        if not pending:
            return
        logger.info("draining", extra={"in_flight": len(pending)})
        _, still = await asyncio.wait(pending, timeout=self.shutdown_timeout)
        for task in still:
            task.cancel()  # process_message releases its message and resets the job on cancellation
        if still:
            await asyncio.wait(still, timeout=15)
            logger.warning("drain_timeout_cancelled", extra={"cancelled": len(still)})
