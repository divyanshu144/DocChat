from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

if settings.database_url.startswith("sqlite"):
    engine = create_async_engine(settings.database_url, echo=settings.debug)

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
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def create_all_tables() -> None:
    import app.models.conversation  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.refresh_token  # noqa: F401
    import app.models.ingest_job  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)


def _table_columns(conn, table_name: str) -> set[str]:
    from sqlalchemy import text
    if conn.dialect.name == "sqlite":
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}
    rows = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :table_name"
    ), {"table_name": table_name}).fetchall()
    return {row[0] for row in rows}


def _migrate(conn) -> None:
    from sqlalchemy import text
    cols = _table_columns(conn, "conversations")
    if "folder_id" not in cols:
        conn.execute(text("ALTER TABLE conversations ADD COLUMN folder_id VARCHAR REFERENCES folders(id)"))
    if "user_id" not in cols:
        conn.execute(text("ALTER TABLE conversations ADD COLUMN user_id VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id)"))

    folder_cols = _table_columns(conn, "folders")
    if "user_id" not in folder_cols:
        conn.execute(text("ALTER TABLE folders ADD COLUMN user_id VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_folders_user_id ON folders (user_id)"))


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
