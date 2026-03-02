from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)

# Enable WAL mode for SQLite so reads don't block writes
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_wal_mode(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def _run_migrations(conn) -> None:
    """Add missing columns to existing tables (safe to call on every startup)."""
    is_sqlite = settings.database_url.startswith("sqlite")

    if is_sqlite:
        try:
            result = await conn.execute(text("PRAGMA table_info(chunks)"))
            columns = {row[1] for row in result.fetchall()}
            if "embedding" not in columns:
                await conn.execute(text("ALTER TABLE chunks ADD COLUMN embedding BLOB"))
            # Ensure the document_id index exists (idempotent)
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks (document_id)")
            )
        except Exception:
            pass  # Table doesn't exist yet; create_all will handle it
    else:
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='chunks' AND column_name='embedding'"
                )
            )
            if not result.fetchone():
                await conn.execute(text("ALTER TABLE chunks ADD COLUMN embedding BYTEA"))
        except Exception:
            pass


async def create_all_tables() -> None:
    # Import all models so Base.metadata knows about every table
    import app.models.document  # noqa: F401
    import app.models.chunk  # noqa: F401
    import app.models.conversation  # noqa: F401
    import app.models.message  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
