import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, settings
from app.core.database import create_all_tables
from app.agent.nodes.retriever import close_retriever_client
from app.core.rate_limit import rate_limiter
from app.core.telemetry import RequestTelemetryMiddleware
from app.services.llm import close_llm_clients
from app.api import auth
from app.api import chat
from app.api import conversations
from app.api import folders
from app.api import health
from app.api import metrics
from app.api import ingest

logger = logging.getLogger("app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_DEFAULT_JWT_SECRET_KEY = Settings.model_fields["jwt_secret_key"].default


def _refuse_default_secret_in_production() -> None:
    """Raise if JWT_SECRET_KEY is still the value shipped in this repo and
    debug mode is off. A signing key anyone can read from source control
    must never sign real tokens outside local development. Pulled out as
    its own function so it is testable without going through the whole
    FastAPI lifespan (which TestClient only runs when used as a context
    manager, not how this repo's tests instantiate it)."""
    if settings.jwt_secret_key == _DEFAULT_JWT_SECRET_KEY and not settings.debug:
        raise RuntimeError(
            "JWT_SECRET_KEY is still the default value shipped in this repo. "
            "Set a real, random JWT_SECRET_KEY in .env before running with DEBUG=false."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _refuse_default_secret_in_production()
    await create_all_tables()
    await ingest.recover_interrupted_ingest_jobs()
    logger.info("startup", extra={"app": settings.app_name, "version": settings.version})
    try:
        yield
    finally:
        try:
            await close_retriever_client()
        finally:
            await close_llm_clients()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)


@app.middleware("http")
async def limit_requests(request: Request, call_next):
    limits = {
        f"{settings.api_prefix}/auth/login": settings.login_rate_limit,
        f"{settings.api_prefix}/auth/signup": settings.signup_rate_limit,
        f"{settings.api_prefix}/chat": settings.chat_rate_limit,
    }
    path = request.url.path.rstrip("/")
    if request.method == "POST" and path in limits:
        host = request.client.host if request.client else "unknown"
        retry_after = rate_limiter.check((path, host), limits[path], settings.rate_limit_window_seconds)
        if retry_after:
            return JSONResponse(
                {"detail": "Too many requests; please retry later"}, status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
    return await call_next(request)


app.add_middleware(RequestTelemetryMiddleware)


app.include_router(auth.router, prefix=settings.api_prefix, tags=["Auth"])
app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(metrics.router, prefix=settings.api_prefix)
app.include_router(ingest.router, prefix=settings.api_prefix, tags=["Ingest"])
app.include_router(chat.router, prefix=settings.api_prefix, tags=["Chat"])
app.include_router(folders.router, prefix=settings.api_prefix, tags=["Folders"])
app.include_router(conversations.router, prefix=settings.api_prefix, tags=["Conversations"])

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(_STATIC_DIR / "index.html")
