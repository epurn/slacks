"""Estimation job and run ORM models (FTY-040).

Two user-owned tables form the async estimation trust boundary:

- ``estimation_jobs`` — exactly one job per ``log_events`` row (a unique
  ``log_event_id`` is the **idempotency anchor**). It tracks the worker's
  progress (:class:`~app.enums.EstimationJobStatus`) and the bounded-retry
  counters, so a re-delivered or duplicated task can be recognised and skipped
  rather than double-processed.
- ``estimation_runs`` — one auditable record per attempt. It stores the
  reproducibility metadata the data-retention policy requires (model/provider,
  schema version, tool names, source references, assumptions, validation errors)
  plus a **sanitized** trace and error. It deliberately stores no raw prompts, no
  secrets, and no raw user text: the row carries ids and structured facts, not
  sensitive payloads (security baseline + ``docs/security/data-retention.md``).

Both tables carry a ``user_id`` foreign key with ``ON DELETE CASCADE`` for
object-level ownership at the persistence boundary, and both cascade from
``log_event_id`` so deleting a log event removes its job and runs. Retention
follows the owning log event: jobs and runs live until the event, user, or
account is deleted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import EstimationJobStatus, EstimationRunStatus


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class EstimationJob(Base):
    """The single estimation job for a log event, owned by exactly one user.

    ``log_event_id`` is unique: there is at most one job per event, which is the
    idempotency guarantee. ``status`` tracks the worker lifecycle (see
    :class:`~app.enums.EstimationJobStatus`); ``attempts`` counts executed
    attempts against ``max_attempts`` (the bounded-retry policy).
    ``idempotency_key`` is a stable, redelivery-safe key derived from the event
    id.
    """

    __tablename__ = "estimation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    log_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("log_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EstimationJobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    runs: Mapped[list[EstimationRun]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class EstimationRun(Base):
    """An auditable record of one estimation attempt for a log event.

    The metadata columns (``provider`` / ``model`` / ``schema_version`` /
    ``tool_names`` / ``source_refs`` / ``assumptions`` / ``validation_errors``)
    are the reproducibility fields required by ``docs/security/data-retention.md``.
    ``trace`` is a **sanitized** step-by-step record and ``error`` a sanitized
    failure message — neither may contain raw prompts, secrets, or raw user text.
    """

    __tablename__ = "estimation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("estimation_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    log_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("log_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EstimationRunStatus.RUNNING
    )
    # Reproducibility metadata (data-retention). Nullable because the steps that
    # populate them (model/provider calls, tool invocations) are stubbed here and
    # filled by FTY-041/042/043/044; a stubbed run legitimately has none yet.
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_names: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    trace: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    job: Mapped[EstimationJob] = relationship(back_populates="runs")
