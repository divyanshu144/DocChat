import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.auth import RefreshRequest, refresh
from app.core.database import Base
from app.core.security import create_refresh_token, hash_refresh_token
from app.models.refresh_token import RefreshToken
from app.models.user import User


async def seed(sessions):
    tokens = []
    async with sessions() as session:
        session.add_all([User(id="alice", email="alice@example.com", hashed_password="unused"),
                         User(id="bob", email="bob@example.com", hashed_password="unused")])
        await session.flush()
        for user_id in ("alice", "alice", "bob"):
            raw, expires = create_refresh_token(user_id)
            session.add(RefreshToken(user_id=user_id, token_hash=hash_refresh_token(raw), expires_at=expires))
            tokens.append(raw)
        await session.commit()
    return tokens


@pytest.mark.asyncio
async def test_replay_revokes_all_user_sessions_but_not_other_users():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    first, sibling, other = await seed(sessions)
    async with sessions() as session:
        rotated = await refresh(RefreshRequest(refresh_token=first), session)
        with pytest.raises(HTTPException):
            await refresh(RefreshRequest(refresh_token=first), session)
    async with sessions() as session:
        for raw in (sibling, rotated.refresh_token):
            with pytest.raises(HTTPException) as exc:
                await refresh(RefreshRequest(refresh_token=raw), session)
            assert exc.value.status_code == 401
        assert (await refresh(RefreshRequest(refresh_token=other), session)).refresh_token
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_refresh_cannot_leave_a_usable_successor(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    first, _, _ = await seed(sessions)
    async def attempt():
        async with sessions() as session:
            try:
                return await refresh(RefreshRequest(refresh_token=first), session)
            except HTTPException as exc:
                return exc.status_code
    outcomes = await asyncio.gather(attempt(), attempt())
    assert sum(outcome == 401 for outcome in outcomes) == 1
    async with sessions() as session:
        rows = (await session.execute(select(RefreshToken).where(RefreshToken.user_id == "alice"))).scalars().all()
        assert all(row.revoked for row in rows)
    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_signed_token_does_not_revoke_legitimate_sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    first, _, _ = await seed(sessions)
    unknown, _ = create_refresh_token("alice")
    async with sessions() as session:
        with pytest.raises(HTTPException):
            await refresh(RefreshRequest(refresh_token=unknown), session)
        assert (await refresh(RefreshRequest(refresh_token=first), session)).refresh_token
    await engine.dispose()
