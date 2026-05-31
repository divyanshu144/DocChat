from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient


def test_signup_returns_usable_tokens():
    from app.core.database import get_db
    from app.main import app

    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    async def mock_db():
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_db] = mock_db
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "new@example.com", "password": "password123"},
    )
    app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
