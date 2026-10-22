"""Ingestion queue contract. Message bodies carry references (job id, storage key, URL), never document text."""
import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import settings

SCHEMA_VERSION = 1
SOURCE_TYPES = ("pdf", "youtube", "web")
_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class MessageError(ValueError):
    """The body is not a valid ingest message. Never include the body in the error."""


@dataclass(frozen=True)
class IngestMessage:
    job_id: str
    source_type: str
    storage_key: str | None = None
    url: str | None = None
    filename: str | None = None
    content_type: str | None = None
    correlation_id: str | None = None

    def to_body(self) -> str:
        return json.dumps({"v": SCHEMA_VERSION, **asdict(self)}, separators=(",", ":"))

    @classmethod
    def from_body(cls, body: str) -> "IngestMessage":
        try:
            data = json.loads(body)
        except (TypeError, ValueError):
            raise MessageError("Message is not valid JSON") from None
        if not isinstance(data, dict) or data.get("v") != SCHEMA_VERSION:
            raise MessageError("Unsupported message version")
        fields = {k: data.get(k) for k in cls.__dataclass_fields__}
        if not isinstance(fields["job_id"], str) or not _ID.fullmatch(fields["job_id"]):
            raise MessageError("Invalid job_id")
        if fields["source_type"] not in SOURCE_TYPES:
            raise MessageError("Invalid source_type")
        for name, value in fields.items():
            if value is not None and not isinstance(value, str):
                raise MessageError(f"Invalid {name}")
        if fields["source_type"] == "pdf" and not fields["storage_key"]:
            raise MessageError("pdf message requires storage_key")
        if fields["source_type"] != "pdf" and not fields["url"]:
            raise MessageError("url message requires url")
        return cls(**fields)


@dataclass(frozen=True)
class ReceivedMessage:
    receipt: str
    receive_count: int
    message: IngestMessage | None  # None = poison body; leave it for the redrive policy


class JobQueue(Protocol):
    def send(self, message: IngestMessage) -> None: ...
    def receive(self, max_messages: int, wait_seconds: int) -> list[ReceivedMessage]: ...
    def delete(self, receipt: str) -> None: ...
    def change_visibility(self, receipt: str, seconds: int) -> None: ...


def backoff_seconds(receive_count: int) -> int:
    """Delay before the next attempt: base * 2^(n-1), capped. receive_count is 1 on the first attempt."""
    delay = settings.ingest_retry_base_delay_s * 2 ** max(receive_count - 1, 0)
    return min(delay, settings.ingest_retry_max_delay_s)


@lru_cache()
def get_queue() -> JobQueue:
    if settings.queue_backend != "sqs":
        raise RuntimeError("No remote queue configured (QUEUE_BACKEND=local)")
    from app.services.queueing.sqs import SQSQueue
    return SQSQueue(settings.sqs_queue_url, region=settings.aws_region or None)
