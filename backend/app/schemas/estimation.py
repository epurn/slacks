"""Estimation boundary DTOs (FTY-040).

Two contracts:

- :class:`EstimationJobPayload` — the **Celery job payload**: the minimal,
  validated message published when a log event is created. It carries only the
  event and owner ids, never sensitive text, so queue logs cannot leak personal
  data. The worker re-validates it at the trust boundary before processing.
- :class:`EstimationRunDTO` — the shape of an auditable estimation run record.
  Every field is sanitized reproducibility metadata; no raw prompts, secrets, or
  raw user text appear here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import EstimationRunStatus


class EstimationJobPayload(BaseModel):
    """The message enqueued on log-event creation and consumed by the worker.

    ``extra="forbid"`` so a malformed or padded message is rejected at the trust
    boundary rather than silently accepted.
    """

    model_config = ConfigDict(extra="forbid")

    log_event_id: uuid.UUID
    user_id: uuid.UUID


class EstimationRunDTO(BaseModel):
    """Read model for an :class:`~app.models.estimation.EstimationRun` row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    log_event_id: uuid.UUID
    user_id: uuid.UUID
    attempt: int
    status: EstimationRunStatus
    provider: str | None
    model: str | None
    schema_version: str | None
    tool_names: list[str]
    source_refs: list[str]
    assumptions: list[str]
    validation_errors: list[str]
    trace: list[dict[str, object]]
    error: str | None
    created_at: datetime
