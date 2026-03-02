"""ARQ worker tasks for background document ingestion.

Start the worker with:
    arq app.workers.tasks.WorkerSettings

Requires REDIS_URL to be set in the environment or .env file.
"""

from arq.connections import RedisSettings

from app.core.config import settings


async def ingest_document_task(ctx, document_id: str) -> None:
    """ARQ task: ingest a document by ID using its own DB session."""
    from app.core.database import AsyncSessionLocal
    from app.services import ingestion

    async with AsyncSessionLocal() as db:
        from app.models.document import Document
        document = await db.get(Document, document_id)
        if document:
            await ingestion.ingest_document(document, db)


class WorkerSettings:
    functions = [ingest_document_task]
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
