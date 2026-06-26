"""Contract tests for the estimation boundary DTOs (FTY-040)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.enums import EstimationRunStatus
from app.models.estimation import EstimationRun
from app.schemas.estimation import EstimationJobPayload, EstimationRunDTO


def test_job_payload_round_trips_ids() -> None:
    log_event_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Strings are coerced to UUID, mirroring how the worker parses a Celery message.
    payload = EstimationJobPayload.model_validate(
        {"log_event_id": str(log_event_id), "user_id": str(user_id)}
    )

    assert payload.log_event_id == log_event_id
    assert payload.user_id == user_id


def test_job_payload_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        EstimationJobPayload.model_validate(
            {
                "log_event_id": uuid.uuid4(),
                "user_id": uuid.uuid4(),
                "raw_text": "should not be in the payload",
            }
        )


def test_run_dto_builds_from_orm_row() -> None:
    run = EstimationRun(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        attempt=1,
        status=EstimationRunStatus.COMPLETED,
        provider=None,
        model=None,
        schema_version=None,
        tool_names=["stub_parse"],
        source_refs=[],
        assumptions=[],
        validation_errors=[],
        trace=[{"step": "stub_parse", "status": "ok"}],
        error=None,
        created_at=datetime.now(UTC),
    )

    dto = EstimationRunDTO.model_validate(run)

    assert dto.attempt == 1
    assert dto.status is EstimationRunStatus.COMPLETED
    assert dto.tool_names == ["stub_parse"]
