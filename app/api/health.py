from datetime import datetime, timezone
import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.agent.nodes.retriever import _get_http_client

router = APIRouter()


async def _database_probe() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _qdrant_probe() -> None:
    response = await _get_http_client().get(
        f"http://{settings.qdrant_host}:{settings.qdrant_port}/collections", timeout=3.0
    )
    response.raise_for_status()


async def _probe(check) -> str:
    try:
        await asyncio.wait_for(check(), timeout=3.0)
        return "ok"
    except Exception:
        return "error"


@router.get("/health")
async def health_check():
    """Dependency readiness; failures return 503 without exposing connection details."""
    database, qdrant = await asyncio.gather(_probe(_database_probe), _probe(_qdrant_probe))
    ready = database == qdrant == "ok"
    return JSONResponse({
        "status": "ok" if ready else "error",
        "dependencies": {"database": database, "qdrant": qdrant},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.version,
    }, status_code=200 if ready else 503)


@router.get("/health/serving")
async def serving_readiness():
    """Optional local-model readiness; never issues a completion or affects /health."""
    if settings.llm_provider != "local":
        return {"status": "not_applicable", "provider": settings.llm_provider}
    from app.services.llm import _get_client, validate_local_endpoint

    try:
        validate_local_endpoint()
        if not settings.local_chat_model.strip():
            raise ValueError("Missing model")
        response = await _get_client().get("/models", timeout=3.0)
        response.raise_for_status()
        models = response.json().get("data", [])
        ready = any(model.get("id") == settings.local_chat_model for model in models)
    except Exception:
        ready = False
    return JSONResponse({"status": "ok" if ready else "error", "provider": "local"},
                        status_code=200 if ready else 503)
