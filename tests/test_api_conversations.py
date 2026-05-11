import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db
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

    conv = MagicMock()
    conv.id = "conv-1"
    conv.title = "Test Chat"
    conv.folder_id = None
    conv.created_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [conv]

    async def mock_db_with_conv():
        session = MagicMock()
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db_with_conv
    with TestClient(app) as c:
        response = c.get("/api/v1/conversations")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "conv-1"
    assert data[0]["title"] == "Test Chat"
    assert data[0]["folder_id"] is None
