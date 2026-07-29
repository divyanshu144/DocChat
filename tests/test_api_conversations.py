import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db
    from app.core.deps import get_current_user

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    def mock_current_user():
        user = MagicMock()
        user.id = "user-1"
        return user

    app.dependency_overrides[get_db] = mock_db
    app.dependency_overrides[get_current_user] = mock_current_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_conversations_returns_empty(client):
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    assert response.json() == []


def test_get_conversation_404_when_not_found(client):
    response = client.get("/api/v1/conversations/does-not-exist")
    assert response.status_code == 404


def test_move_conversation_404_when_not_found(client):
    response = client.patch("/api/v1/conversations/does-not-exist", json={"folder_id": None})
    assert response.status_code == 404


def test_list_conversations_returns_conversations():
    from app.main import app
    from app.core.database import get_db
    from app.core.deps import get_current_user

    conv = MagicMock()
    conv.id = "conv-1"
    conv.title = "Test Chat"
    conv.user_id = "user-1"
    conv.folder_id = None
    conv.created_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [conv]

    async def mock_db_with_conv():
        session = MagicMock()
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    def mock_current_user():
        user = MagicMock()
        user.id = "user-1"
        return user

    app.dependency_overrides[get_db] = mock_db_with_conv
    app.dependency_overrides[get_current_user] = mock_current_user
    c = TestClient(app)
    response = c.get("/api/v1/conversations")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "conv-1"
    assert data[0]["title"] == "Test Chat"
    assert data[0]["folder_id"] is None


def test_get_conversation_returns_all_messages_with_ids_in_order():
    from app.main import app
    from app.core.database import get_db
    from app.core.deps import get_current_user

    conv = MagicMock()
    conv.id = "conv-1"
    conv.title = "Test Chat"
    conv.folder_id = None
    conv.created_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    first = MagicMock()
    first.id = "msg-1"
    first.role.value = "user"
    first.content = "First question"
    first.created_at = datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)

    second = MagicMock()
    second.id = "msg-2"
    second.role.value = "assistant"
    second.content = "First answer"
    second.created_at = datetime(2026, 5, 11, 10, 1, tzinfo=timezone.utc)

    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    msgs_result = MagicMock()
    msgs_result.scalars.return_value.all.return_value = [first, second]

    async def mock_db_with_messages():
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[conv_result, msgs_result])
        yield session

    def mock_current_user():
        user = MagicMock()
        user.id = "user-1"
        return user

    app.dependency_overrides[get_db] = mock_db_with_messages
    app.dependency_overrides[get_current_user] = mock_current_user
    c = TestClient(app)
    response = c.get("/api/v1/conversations/conv-1")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["id"] for m in messages] == ["msg-1", "msg-2"]
    assert [m["content"] for m in messages] == ["First question", "First answer"]
