"""Real cross-user folder isolation, against a real (temporary, in-memory)
SQLite database, not mocks. The property being proven is specific: user B
must not be able to see, rename, delete, or move a conversation into user
A's folder, even by guessing A's folder id. A mocked session can be told to
return whatever a test wants; a real query against a real database is the
only way to prove the WHERE clause itself is doing the filtering. Mirrors
the direct-route-call pattern tests/test_api_auth.py already uses for this
kind of real-database test.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.conversations import ConversationMove, move_conversation
from app.api.folders import FolderRename, delete_folder, list_folders, rename_folder
from app.core.database import Base
from app.models.conversation import Conversation, Folder
from app.models.user import User


@pytest.fixture
async def seeded_session():
    import app.models.ingest_job  # noqa: F401
    import app.models.refresh_token  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        user_a = User(id="user-a", email="a@example.com", hashed_password="x")
        user_b = User(id="user-b", email="b@example.com", hashed_password="x")
        folder_a = Folder(id="folder-a", name="A's folder", user_id="user-a")
        folder_b = Folder(id="folder-b", name="B's folder", user_id="user-b")
        conv_a = Conversation(id="conv-a", title="A's chat", user_id="user-a")
        session.add_all([user_a, user_b, folder_a, folder_b, conv_a])
        await session.commit()
        yield session, user_a, user_b


@pytest.mark.asyncio
async def test_user_b_cannot_see_user_a_folder_in_listing(seeded_session):
    session, user_a, user_b = seeded_session

    folders_for_b = await list_folders(db=session, current_user=user_b)
    folders_for_a = await list_folders(db=session, current_user=user_a)

    assert [f["id"] for f in folders_for_b] == ["folder-b"]  # only their own
    assert [f["id"] for f in folders_for_a] == ["folder-a"]  # only their own


@pytest.mark.asyncio
async def test_user_b_cannot_rename_user_a_folder(seeded_session):
    session, user_a, user_b = seeded_session

    with pytest.raises(HTTPException) as exc:
        await rename_folder(
            "folder-a", FolderRename(name="Hijacked"), db=session, current_user=user_b
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_user_b_cannot_delete_user_a_folder(seeded_session):
    session, user_a, user_b = seeded_session

    with pytest.raises(HTTPException) as exc:
        await delete_folder("folder-a", db=session, current_user=user_b)
    assert exc.value.status_code == 404

    # Prove it is actually still there, not deleted and then re-blocked.
    folders_for_a = await list_folders(db=session, current_user=user_a)
    assert [f["id"] for f in folders_for_a] == ["folder-a"]


@pytest.mark.asyncio
async def test_user_a_can_rename_and_delete_their_own_folder(seeded_session):
    session, user_a, user_b = seeded_session

    renamed = await rename_folder(
        "folder-a", FolderRename(name="Renamed"), db=session, current_user=user_a
    )
    assert renamed["name"] == "Renamed"

    await delete_folder("folder-a", db=session, current_user=user_a)
    folders_for_a = await list_folders(db=session, current_user=user_a)
    assert folders_for_a == []


@pytest.mark.asyncio
async def test_user_a_cannot_move_their_conversation_into_user_b_folder(seeded_session):
    """The actual target of this fix: a conversation the caller owns cannot
    be moved into a folder owned by someone else, even though both the
    conversation and the folder id are individually real and valid."""
    session, user_a, user_b = seeded_session

    with pytest.raises(HTTPException) as exc:
        await move_conversation(
            "conv-a", ConversationMove(folder_id="folder-b"), db=session, current_user=user_a
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_user_a_can_move_their_conversation_into_their_own_folder(seeded_session):
    session, user_a, user_b = seeded_session

    result = await move_conversation(
        "conv-a", ConversationMove(folder_id="folder-a"), db=session, current_user=user_a
    )
    assert result["folder_id"] == "folder-a"


@pytest.mark.asyncio
async def test_user_b_cannot_move_user_a_conversation_at_all(seeded_session):
    """user_b doesn't own conv-a, so this must 404 on the conversation
    lookup itself, before the folder ownership check is ever reached."""
    session, user_a, user_b = seeded_session

    with pytest.raises(HTTPException) as exc:
        await move_conversation(
            "conv-a", ConversationMove(folder_id="folder-b"), db=session, current_user=user_b
        )
    assert exc.value.status_code == 404
