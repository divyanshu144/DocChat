from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

if settings.database_url.startswith("sqlite"):
    engine = create_async_engine(settings.database_url, echo=settings.debug)

    # Enable WAL mode for SQLite so reads don't block writes
    @event.listens_for(engine.sync_engine, "connect")
    def _set_wal_mode(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
else:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )

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
        # --- chunks table ---
        try:
            result = await conn.execute(text("PRAGMA table_info(chunks)"))
            cols = {row[1] for row in result.fetchall()}
            if "embedding" not in cols:
                await conn.execute(text("ALTER TABLE chunks ADD COLUMN embedding BLOB"))
            if "page_number" not in cols:
                await conn.execute(text("ALTER TABLE chunks ADD COLUMN page_number INTEGER"))
            if "section_heading" not in cols:
                await conn.execute(text("ALTER TABLE chunks ADD COLUMN section_heading TEXT"))
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks (document_id)")
            )
        except Exception:
            pass  # Table doesn't exist yet; create_all will handle it

        # --- messages table ---
        try:
            result = await conn.execute(text("PRAGMA table_info(messages)"))
            cols = {row[1] for row in result.fetchall()}
            if "is_complete" not in cols:
                await conn.execute(
                    text("ALTER TABLE messages ADD COLUMN is_complete INTEGER NOT NULL DEFAULT 1")
                )
        except Exception:
            pass
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
            # page_number / section_heading
            for col, coltype in [("page_number", "INTEGER"), ("section_heading", "TEXT")]:
                r = await conn.execute(
                    # Parameterized SELECT — safe against injection via col name
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='chunks' AND column_name=:col"
                    ),
                    {"col": col},
                )
                if not r.fetchone():
                    # DDL (ALTER TABLE) cannot use bind parameters; col and coltype
                    # are hardcoded string literals above — not user-supplied input.
                    await conn.execute(
                        text(f"ALTER TABLE chunks ADD COLUMN {col} {coltype}")
                    )
            # messages.is_complete
            r = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='messages' AND column_name='is_complete'"
                )
            )
            if not r.fetchone():
                await conn.execute(
                    text("ALTER TABLE messages ADD COLUMN is_complete BOOLEAN DEFAULT TRUE")
                )
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
