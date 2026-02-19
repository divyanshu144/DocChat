import logging
import time
import uuid

from fastapi import FastAPI, Request
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

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.perf_counter()

    try:
        response = await call_next(request)
        return response
    except Exception:
        # Log exception with stack trace
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
        status_code = getattr(locals().get("response", None), "status_code", 500)

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

    # (Note: this line won't be reached because of the return above.)
    # It's here to show intent; better to set the header before returning.
    # response.headers["x-request-id"] = request_id

# Include API routers
app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(documents.router, prefix=settings.api_prefix, tags=["Documents"])
app.include_router(conversations.router, prefix=settings.api_prefix, tags=["Conversations"])

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }

@app.on_event("startup")
async def startup_event():
    await create_all_tables()
    logger.info("startup", extra={"app": settings.app_name, "version": settings.version})