"""Database password from Secrets Manager, read when a connection is opened (AWS mode only).

RDS rotates its managed master password every 7 days and changes it in the database in place, so a password
copied into an environment variable at task start stops working for new connections after the first rotation.
This provider keeps a short cache, supports a forced refresh, and never logs or returns the secret in errors.
"""
import asyncio
import json
import time


class SecretReadError(RuntimeError):
    """The password could not be read. The message never includes secret content."""


class DbPasswordProvider:
    def __init__(self, secret_id: str, *, region: str | None = None, client=None, ttl: float = 60.0,
                 clock=time.monotonic):
        self.secret_id = secret_id
        self._region = region
        self._client_obj = client
        self.ttl = ttl
        self._clock = clock
        self._value: str | None = None
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def _client(self):
        if self._client_obj is None:
            import boto3
            from botocore.config import Config
            self._client_obj = boto3.client(
                "secretsmanager", region_name=self._region,
                config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=3, read_timeout=5))
        return self._client_obj

    def _fetch(self) -> str:
        try:
            raw = self._client.get_secret_value(SecretId=self.secret_id)["SecretString"]
            return json.loads(raw)["password"]
        except Exception:
            raise SecretReadError("Could not read the database password secret") from None

    async def get(self, *, force: bool = False) -> str:
        async with self._lock:
            fresh = self._value is not None and self._clock() - self._fetched_at < self.ttl
            if force or not fresh:
                self._value = await asyncio.to_thread(self._fetch)
                self._fetched_at = self._clock()
            return self._value
