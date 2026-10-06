"""Prometheus scrape surface. Use a private network or configured bearer token."""
import secrets

from fastapi import APIRouter, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings
from app.core import metrics as instrumentation

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(authorization: str = Header(default="")):
    if settings.metrics_bearer_token:
        expected = f"Bearer {settings.metrics_bearer_token}".encode()
        if not secrets.compare_digest(authorization.encode(), expected):
            raise HTTPException(401, "Metrics authorization required")
    return Response(generate_latest(instrumentation.metrics.registry),
                    headers={"Content-Type": CONTENT_TYPE_LATEST})
