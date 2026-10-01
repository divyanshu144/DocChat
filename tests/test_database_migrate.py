"""Tests for app/core/database.py's idempotent startup migration.

Runs against a real (temporary, in-memory) SQLite database rather than
mocking the connection -- _migrate's whole job is introspecting real schema
and issuing real ALTER TABLE statements, which a MagicMock session would not
catch a mistake in.
"""

from sqlalchemy import create_engine, text

from app.core.database import Base, _migrate, _table_columns


def _fresh_engine():
    """A real, temporary SQLite database with the base schema (created via
    Base.metadata.create_all, like create_all_tables does) but without
    _migrate's columns yet -- the same starting point the real app sees on
    an older database."""
    import app.models.conversation  # noqa: F401
    import app.models.ingest_job  # noqa: F401
    import app.models.refresh_token  # noqa: F401
    import app.models.user  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_migrate_adds_folders_user_id_column():
    engine = _fresh_engine()
    with engine.connect() as conn:
        # Base.metadata.create_all already creates the column from the
        # current model -- drop it to simulate an older database that
        # predates this field, the actual scenario _migrate exists for.
        conn.execute(text("CREATE TABLE folders_old AS SELECT id, name, created_at FROM folders"))
        conn.execute(text("DROP TABLE folders"))
        conn.execute(text("ALTER TABLE folders_old RENAME TO folders"))
        conn.commit()

        assert "user_id" not in _table_columns(conn, "folders")
        _migrate(conn)
        conn.commit()

        assert "user_id" in _table_columns(conn, "folders")


def test_migrate_is_idempotent_on_folders_user_id():
    engine = _fresh_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE folders_old AS SELECT id, name, created_at FROM folders"))
        conn.execute(text("DROP TABLE folders"))
        conn.execute(text("ALTER TABLE folders_old RENAME TO folders"))
        conn.commit()

        _migrate(conn)
        conn.commit()
        # Running it again must not raise (e.g. a bare ALTER TABLE ADD
        # COLUMN with no existence check would error the second time).
        _migrate(conn)
        conn.commit()

        assert "user_id" in _table_columns(conn, "folders")


def test_migrate_creates_an_index_on_folders_user_id():
    engine = _fresh_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE folders_old AS SELECT id, name, created_at FROM folders"))
        conn.execute(text("DROP TABLE folders"))
        conn.execute(text("ALTER TABLE folders_old RENAME TO folders"))
        conn.commit()

        _migrate(conn)
        conn.commit()

        indexes = {
            row[1]
            for row in conn.execute(text("PRAGMA index_list(folders)")).fetchall()
        }
        assert "ix_folders_user_id" in indexes


def test_migrate_already_current_schema_is_a_no_op():
    """A database already matching the current models (the normal case for
    a freshly created test/dev database) must not error when _migrate runs
    on top of it."""
    engine = _fresh_engine()
    with engine.connect() as conn:
        assert "user_id" in _table_columns(conn, "folders")
        _migrate(conn)
        conn.commit()
        assert "user_id" in _table_columns(conn, "folders")


def test_table_columns_reads_real_sqlite_schema():
    engine = _fresh_engine()
    with engine.connect() as conn:
        cols = _table_columns(conn, "conversations")
    assert {"id", "title", "user_id", "folder_id", "created_at"} <= cols
