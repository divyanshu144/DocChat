#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import tempfile
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
sys.path.insert(0, str(ROOT))


@dataclass
class EndpointMetric:
    name: str
    samples: int
    passed: int
    failed: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _metric(name: str, latencies: list[float], failures: int) -> EndpointMetric:
    return EndpointMetric(
        name=name,
        samples=len(latencies) + failures,
        passed=len(latencies),
        failed=failures,
        mean_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
        p50_ms=round(statistics.median(latencies), 2) if latencies else 0.0,
        p95_ms=round(_percentile(latencies, 95), 2) if latencies else 0.0,
        min_ms=round(min(latencies), 2) if latencies else 0.0,
        max_ms=round(max(latencies), 2) if latencies else 0.0,
    )


def _measure(name: str, samples: int, fn: Callable[[], bool]) -> EndpointMetric:
    latencies: list[float] = []
    failures = 0
    for _ in range(samples):
        started = time.perf_counter()
        ok = fn()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if ok:
            latencies.append(elapsed_ms)
        else:
            failures += 1
    return _metric(name, latencies, failures)


def _print_table(metrics: list[EndpointMetric]) -> None:
    print("\nEndpoint metrics")
    print("name                         pass/total   mean    p50    p95    min    max")
    print("-" * 78)
    for m in metrics:
        print(
            f"{m.name:<28} {m.passed:>3}/{m.samples:<3} "
            f"{m.mean_ms:>7.2f} {m.p50_ms:>6.2f} {m.p95_ms:>6.2f} "
            f"{m.min_ms:>6.2f} {m.max_ms:>6.2f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DocChat API E2E metrics.")
    parser.add_argument("--samples", type=int, default=20, help="Samples per repeated endpoint.")
    parser.add_argument("--chat-samples", type=int, default=10, help="Samples for mocked-agent chat.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path.")
    args = parser.parse_args()
    logging.getLogger("app").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    db_path = Path(tempfile.gettempdir()) / f"docchat_e2e_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ.setdefault("GROQ_API_KEY", "e2e-mocked")

    from fastapi.testclient import TestClient
    from app.main import app

    metrics: list[EndpointMetric] = []
    email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    password = "password123"

    fake_chat_state = {
        "query": "What is attention?",
        "conversation_id": "unused",
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [{"text": "Attention lets a model focus on relevant context."}],
        "answer": "Attention lets a model focus on relevant context.",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 1,
        "grounding_passed": True,
    }

    mock_qdrant = MagicMock()
    mock_qdrant.scroll.return_value = ([], None)

    with ExitStack() as stack:
        stack.enter_context(patch("app.api.chat.agent_graph.ainvoke", new=AsyncMock(return_value=fake_chat_state)))
        stack.enter_context(patch("app.api.ingest.ingest_pdf", new=AsyncMock(return_value="src-pdf")))
        stack.enter_context(patch("app.api.ingest.ingest_youtube", new=AsyncMock(return_value="src-youtube")))
        stack.enter_context(patch("app.api.ingest.ingest_web", new=AsyncMock(return_value="src-web")))
        stack.enter_context(patch("app.api.ingest.get_qdrant_client", return_value=mock_qdrant))
        stack.enter_context(patch("app.api.ingest.get_qdrant_collection"))

        with TestClient(app) as client:
            metrics.append(_measure(
                "health",
                args.samples,
                lambda: client.get("/api/v1/health").status_code == 200,
            ))

            signup_started = time.perf_counter()
            signup = client.post(
                "/api/v1/auth/signup",
                json={"email": email, "password": password},
            )
            signup_ms = (time.perf_counter() - signup_started) * 1000
            if signup.status_code != 201:
                raise RuntimeError(f"signup failed: {signup.status_code} {signup.text}")
            tokens = signup.json()
            headers = {"Authorization": f"Bearer {tokens['access_token']}"}
            metrics.append(_metric("auth signup", [signup_ms], 0))

            metrics.append(_measure(
                "auth login",
                args.samples,
                lambda: client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": password},
                ).status_code == 200,
            ))
            metrics.append(_measure(
                "auth me",
                args.samples,
                lambda: client.get("/api/v1/auth/me", headers=headers).status_code == 200,
            ))
            metrics.append(_measure(
                "folders create",
                args.samples,
                lambda: client.post(
                    "/api/v1/folders",
                    json={"name": f"Folder {uuid.uuid4().hex[:8]}"},
                ).status_code == 201,
            ))
            metrics.append(_measure(
                "folders list",
                args.samples,
                lambda: client.get("/api/v1/folders").status_code == 200,
            ))
            metrics.append(_measure(
                "ingest pdf mocked",
                args.samples,
                lambda: client.post(
                    "/api/v1/ingest/pdf",
                    files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
                ).status_code == 200,
            ))
            metrics.append(_measure(
                "ingest youtube mocked",
                args.samples,
                lambda: client.post(
                    "/api/v1/ingest/youtube",
                    json={"url": "https://youtube.com/watch?v=abc123"},
                ).status_code == 200,
            ))
            metrics.append(_measure(
                "ingest web mocked",
                args.samples,
                lambda: client.post(
                    "/api/v1/ingest/web",
                    json={"url": "https://example.com/article"},
                ).status_code == 200,
            ))
            metrics.append(_measure(
                "sources list mocked",
                args.samples,
                lambda: client.get("/api/v1/sources").status_code == 200,
            ))

            chat_conversation_ids: list[str] = []

            def chat_once() -> bool:
                response = client.post(
                    "/api/v1/chat",
                    headers=headers,
                    json={"query": "What is attention?", "sources": ["pdf"]},
                )
                if response.status_code != 200 or "[DONE]" not in response.text:
                    return False
                conv_id = response.headers.get("x-conversation-id")
                if conv_id:
                    chat_conversation_ids.append(conv_id)
                return True

            metrics.append(_measure("chat SSE mocked agent", args.chat_samples, chat_once))
            metrics.append(_measure(
                "conversations list",
                args.samples,
                lambda: client.get("/api/v1/conversations", headers=headers).status_code == 200,
            ))

            first_conv = chat_conversation_ids[0] if chat_conversation_ids else ""
            if first_conv:
                metrics.append(_measure(
                    "conversation detail",
                    args.samples,
                    lambda: client.get(
                        f"/api/v1/conversations/{first_conv}",
                        headers=headers,
                    ).status_code == 200,
                ))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_url": f"sqlite+aiosqlite:///{db_path}",
        "samples": args.samples,
        "chat_samples": args.chat_samples,
        "notes": [
            "FastAPI routes, auth, SQLite persistence, and SSE framing are exercised end to end.",
            "Agent graph and ingestion backends are mocked to isolate app/API overhead from external LLM, Qdrant, and scraping latency.",
        ],
        "metrics": [asdict(m) for m in metrics],
    }

    _print_table(metrics)
    failures = sum(m.failed for m in metrics)
    print(f"\nFailures: {failures}")

    REPORT_DIR.mkdir(exist_ok=True)
    out_path = args.output or REPORT_DIR / f"e2e_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Report: {out_path}")

    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{db_path}{suffix}")
        path.unlink(missing_ok=True)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
