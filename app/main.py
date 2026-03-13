import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings
from app.core.database import create_all_tables
from app.api import health
from app.api import documents
from app.api import conversations

logger = logging.getLogger("app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    await create_all_tables()

    # Pre-load ONNX singletons so the first request doesn't pay the cold-start penalty.
    # Both fastembed and FlashRank download their models on first instantiation (~100-300ms
    # after the first run when models are cached locally).
    loop = asyncio.get_event_loop()
    from app.services.retrieval import _get_embedder
    from app.services.reranker import _get_ranker
    await loop.run_in_executor(None, _get_embedder)
    if settings.rerank_enabled:
        await loop.run_in_executor(None, _get_ranker)

    logger.info("startup", extra={"app": settings.app_name, "version": settings.version})
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.perf_counter()
    response = None

    try:
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response
    except Exception:
        logger.exception(
            "request_failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        raise
    finally:
        duration = time.perf_counter() - start
        status_code = response.status_code if response is not None else 500
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_s": round(duration, 4),
            },
        )


# Include API routers
app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(documents.router, prefix=settings.api_prefix, tags=["Documents"])
app.include_router(conversations.router, prefix=settings.api_prefix, tags=["Conversations"])


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root():
    return FileResponse(_STATIC_DIR / "index.html")
