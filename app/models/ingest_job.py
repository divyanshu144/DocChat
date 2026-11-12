import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IngestJobStatusValue(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


S = IngestJobStatusValue

# The one place that says which status moves are legal. `done` is terminal and immutable: a redelivered or
# late write (a heartbeat landing after completion, a duplicate message) must not reopen a finished job.
# `error` is NOT terminal: the queue's dead-letter redrive, or a user resubmission, may run the job again.
LEGAL_TRANSITIONS: dict[IngestJobStatusValue, frozenset[IngestJobStatusValue]] = {
    S.queued: frozenset({S.queued, S.running, S.error}),   # error: restart sweep, or retries exhausted
    S.running: frozenset({S.running, S.done, S.error, S.queued}),  # queued: retry, or handed back on shutdown
    S.error: frozenset({S.error, S.queued, S.running}),    # retried
    S.done: frozenset({S.done}),
}
TERMINAL = frozenset({S.done})


def can_transition(old: IngestJobStatusValue, new: IngestJobStatusValue) -> bool:
    return new in LEGAL_TRANSITIONS[old]


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[IngestJobStatusValue] = mapped_column(
        Enum(IngestJobStatusValue), nullable=False, default=IngestJobStatusValue.queued
    )
    phase: Mapped[str] = mapped_column(String(100), nullable=False, default="queued")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Queue-path bookkeeping (unused by the local background-task path).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dedupe_key: Mapped[str | None] = mapped_column(String(600), nullable=True, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
