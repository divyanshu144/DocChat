"""ECS task scale-in protection, so autoscaling never stops a worker that is mid-job.

Uses the ECS agent endpoint (ECS_AGENT_URI, present on Fargate). Protection is on while at least one job is
in flight and off when idle. It expires by itself if the worker dies. Every failure is swallowed: without the
endpoint (local runs, or an error) the worker simply runs unprotected and logs a content-free warning.
"""
import asyncio
import json
import logging
import os
import urllib.request

logger = logging.getLogger("worker")

RENEW_EVERY_S = 60


def _put(url: str, body: dict) -> None:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="PUT",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310 - fixed local agent URL
        response.read()


class TaskProtection:
    def __init__(self, agent_uri: str | None = None, *, expires_minutes: int = 5, send=_put):
        uri = os.environ.get("ECS_AGENT_URI") if agent_uri is None else agent_uri
        self.url = f"{uri.rstrip('/')}/task-protection/v1/state" if uri else None
        self.expires_minutes = expires_minutes
        self._send = send
        self._active = 0
        self.enabled = False
        self.failed = False

    async def _set(self, enabled: bool) -> None:
        if not self.url:
            return
        body = {"ProtectionEnabled": enabled}
        if enabled:
            body["ExpiresInMinutes"] = self.expires_minutes
        try:
            await asyncio.to_thread(self._send, self.url, body)
            self.enabled, self.failed = enabled, False
        except Exception:
            if not self.failed:  # one line per outage, never the error text
                logger.warning("task_protection_unavailable")
            self.failed = True

    async def job_started(self) -> None:
        self._active += 1
        if self._active == 1:
            await self._set(True)

    async def job_finished(self) -> None:
        self._active = max(self._active - 1, 0)
        if self._active == 0 and (self.enabled or self.failed):
            await self._set(False)

    async def renew(self) -> None:
        if self._active > 0:
            await self._set(True)
