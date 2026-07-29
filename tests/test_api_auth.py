from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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


@pytest.mark.asyncio
async def test_refresh_rotates_refresh_tokens():
    from app.api.auth import LoginRequest, RefreshRequest, login, refresh
    from app.core.database import Base
    from app.core.security import hash_password
    from app.models.user import User

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models.refresh_token  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        session.add(User(email="demo@example.com", hashed_password=hash_password("password123")))
        await session.commit()

        login_tokens = await login(LoginRequest(email="demo@example.com", password="password123"), session)
        refresh_a = login_tokens.refresh_token

        rotated_once = await refresh(RefreshRequest(refresh_token=refresh_a), session)
        refresh_b = rotated_once.refresh_token

        assert refresh_b != refresh_a
        with pytest.raises(HTTPException) as exc:
            await refresh(RefreshRequest(refresh_token=refresh_a), session)
        assert exc.value.status_code == 401

        rotated_twice = await refresh(RefreshRequest(refresh_token=refresh_b), session)
        refresh_c = rotated_twice.refresh_token

        assert refresh_c != refresh_b
        assert rotated_once.access_token
        assert rotated_twice.access_token

    await engine.dispose()
