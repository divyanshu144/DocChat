from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """FastAPI dependency that enforces API key auth when API_KEY is configured.

    When API_KEY is not set in config (the default), this is a no-op so local
    development works without any extra configuration.
    """
    from app.core.config import settings
    if settings.api_key is None:
        return  # Auth disabled — dev / single-tenant mode
    if key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
