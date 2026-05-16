import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_access_token(user_id: str) -> str:
    expire = _utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "type": "access", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    """Return (raw_token, expires_at). Store only hash_refresh_token(raw_token) in DB."""
    expire = _utcnow() + timedelta(days=settings.refresh_token_expire_days)
    jti = secrets.token_hex(16)
    payload = {"sub": user_id, "type": "refresh", "jti": jti, "exp": expire}
    raw = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return raw, expire


def decode_token(token: str) -> dict:
    """Decode and verify a JWT. Raises JWTError on any failure."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


# ---------------------------------------------------------------------------
# Refresh-token DB hash (SHA-256 of the raw JWT string)
# ---------------------------------------------------------------------------

def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()
