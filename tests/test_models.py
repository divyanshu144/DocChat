import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, selectinload
from app.core.database import Base
from app.models.conversation import Conversation, Message, MessageRole


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    import app.models.conversation  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_and_message(db):
    conv = Conversation(title="test chat")
    db.add(conv)
    await db.flush()

    msg = Message(conversation_id=conv.id, role=MessageRole.user, content="hello")
    db.add(msg)
    await db.commit()

    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conv.id)
        .options(selectinload(Conversation.messages))
    )
    conv = result.scalar_one()
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "hello"
    assert conv.messages[0].role == MessageRole.user


@pytest.mark.asyncio
async def test_conversation_has_no_document_id(db):
    conv = Conversation(title="standalone")
    db.add(conv)
    await db.flush()
    assert not hasattr(conv, "document_id")
