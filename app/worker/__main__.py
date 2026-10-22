"""Entry point: python -m app.worker"""
import asyncio
import logging
import signal
import sys

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.worker.loop import Worker
from app.worker.server import make_server, serve_in_thread


async def main() -> int:
    configure_logging()
    log = logging.getLogger("worker")
    if settings.queue_backend != "sqs":
        log.error("QUEUE_BACKEND must be sqs to run the worker")
        return 2
    from app.core.database import engine
    from app.services.blobs import get_blob_store
    from app.services.embedder import get_embedder
    from app.services.queueing import get_queue

    worker = Worker(get_queue(), get_blob_store())
    server = make_server(worker, settings.worker_http_port)
    serve_in_thread(server)  # liveness is up while the model loads; readiness is not
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    try:
        if await asyncio.to_thread(get_embedder) is None:
            log.error("embedder_unavailable")
            return 3
        worker.warm = True
        log.info("worker_started", extra={"concurrency": worker.concurrency})
        await worker.run()
        log.info("worker_stopped")
        return 0
    finally:
        server.shutdown()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
