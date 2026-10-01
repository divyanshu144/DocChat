import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone


def _mock_current_user():
    user = MagicMock()
    user.id = "user-1"
    user.is_active = True
    return user


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db
    from app.core.deps import get_current_user

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.delete = AsyncMock()
        session.refresh = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db
    app.dependency_overrides[get_current_user] = _mock_current_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_folders_returns_empty(client):
    response = client.get("/api/v1/folders")
    assert response.status_code == 200
    assert response.json() == []


def test_create_folder_returns_201(client):
    from app.main import app
    from app.core.database import get_db
    from app.core.deps import get_current_user

    folder_dt = datetime(2026, 5, 11, tzinfo=timezone.utc)

    async def mock_db_create():
        session = MagicMock()
        session.add = MagicMock()

        async def fake_commit():
            pass

        async def fake_refresh(obj):
            obj.id = "f-1"
            obj.name = "Work"
            obj.created_at = folder_dt

        session.commit = fake_commit
        session.refresh = fake_refresh
        yield session

    app.dependency_overrides[get_db] = mock_db_create
    app.dependency_overrides[get_current_user] = _mock_current_user
    response = TestClient(app).post("/api/v1/folders", json={"name": "Work"})
    app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Work"
    assert body["conversation_count"] == 0


def test_rename_folder_404_when_not_found(client):
    response = client.patch("/api/v1/folders/missing-id", json={"name": "New Name"})
    assert response.status_code == 404


def test_delete_folder_404_when_not_found(client):
    response = client.delete("/api/v1/folders/missing-id")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Auth gaps (Part 2 A): every folder route must reject an unauthenticated
# caller with 401. No override of get_current_user here -- a real (missing)
# Authorization header must 401.
# ---------------------------------------------------------------------------


@pytest.fixture
def unauthenticated_client():
    from app.main import app

    assert app.dependency_overrides == {}
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_folder_401_without_auth(unauthenticated_client):
    response = unauthenticated_client.post("/api/v1/folders", json={"name": "Work"})
    assert response.status_code == 401


def test_list_folders_401_without_auth(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/folders")
    assert response.status_code == 401


def test_rename_folder_401_without_auth(unauthenticated_client):
    response = unauthenticated_client.patch(
        "/api/v1/folders/f-1", json={"name": "New Name"}
    )
    assert response.status_code == 401


def test_delete_folder_401_without_auth(unauthenticated_client):
    response = unauthenticated_client.delete("/api/v1/folders/f-1")
    assert response.status_code == 401
