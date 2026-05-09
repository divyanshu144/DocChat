import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.core.config import settings
from app.core.database import create_all_tables
from app.api import health
from app.api import ingest
from app.api import chat

logger = logging.getLogger("app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    logger.info("startup", extra={"app": settings.app_name, "version": settings.version})
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)


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
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )
        raise
    finally:
        duration = time.perf_counter() - start
        status = response.status_code if response else 500
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status,
                "duration_s": round(duration, 4),
            },
        )


app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(ingest.router, prefix=settings.api_prefix, tags=["Ingest"])
app.include_router(chat.router, prefix=settings.api_prefix, tags=["Chat"])


@app.get("/")
async def root():
    return {"status": "ok", "app": settings.app_name, "version": settings.version}
