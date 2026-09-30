import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IngestJobStatusValue(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
