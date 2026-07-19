"""Worker integration tests for the estimation core (FTY-040).

These drive :func:`app.estimator.processing.process_estimation` against the same
migrated SQLite database the API writes to, proving the acceptance criteria end
to end with a stub pipeline:

- a pending event is claimed and driven ``pending → processing → completed``;
- re-delivery is idempotent (no second run, no re-advance);
- a failing step retries up to the bound, then marks the event ``failed``;
- a clarifying step is terminal (``needs_clarification``);
- ownership is enforced when loading the event (fail closed);
- the run record stores sanitized metadata only — never the raw text.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import EstimationJobStatus, EstimationRunStatus, LogEventStatus
from app.estimator.pipeline import (
    EstimationContext,
    NeedsClarification,
    Pipeline,
    StepError,
    StepFailed,
    StubCalculateStep,
    StubParseStep,
)
from app.estimator.processing import (
    DEFAULT_MAX_INFRA_RETRY_ATTEMPTS,
    EstimationEventNotFound,
    process_estimation,
)
from app.models.estimation import EstimationJob, EstimationRun
from app.models.log_events import LogEvent

RAW_TEXT = "150g rice and dal at 7pm"


def _stub_pipeline() -> Pipeline:
    """The FTY-040 stub pipeline, used here to exercise the worker state machine
    independently of the real (provider-driven) FTY-042 parse step."""

    return Pipeline([StubParseStep(), StubCalculateStep()])


class _FailStep:
    name = "always_fails"

    def run(self, context: EstimationContext) -> None:
        raise StepError("transient_failure")


class _UnparseableStep:
    name = "unparseable"

    def run(self, context: EstimationContext) -> None:
        # A deterministic non-food classification — the only terminal-``failed`` class
        # after FTY-372 (an infra failure never lands ``failed``).
        raise StepFailed("unparseable_input")


class _ClarifyStep:
    name = "asks"

    def run(self, context: EstimationContext) -> None:
        raise NeedsClarification("ambiguous")


def _seed_event(
    client: TestClient, email: str, raw_text: str = RAW_TEXT
) -> tuple[uuid.UUID, uuid.UUID]:
    """Register a user and create a pending event; return ``(user_id, event_id)``."""

    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"

    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": raw_text},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _runs_for(session: Session, event_id: uuid.UUID) -> list[EstimationRun]:
    return list(
        session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id))
    )


def _jobs_for(session: Session, event_id: uuid.UUID) -> list[EstimationJob]:
    return list(
        session.scalars(select(EstimationJob).where(EstimationJob.log_event_id == event_id))
    )


def test_completed_end_to_end_drives_state_machine(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "complete@example.com")

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=_stub_pipeline()
    )

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert result.attempts == 1
    assert result.should_retry is False

    event = session.get(LogEvent, event_id)
    assert event is not None and event.status == LogEventStatus.COMPLETED

    runs = _runs_for(session, event_id)
    assert len(runs) == 1
    assert runs[0].status == EstimationRunStatus.COMPLETED
    assert runs[0].attempt == 1


def test_redelivery_is_idempotent(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "idempotent@example.com")

    first = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=_stub_pipeline()
    )
    second = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=_stub_pipeline()
    )

    # The second delivery is a no-op: same terminal job, no new run, no new run id.
    assert first.job_status is EstimationJobStatus.SUCCEEDED
    assert second.job_status is EstimationJobStatus.SUCCEEDED
    assert second.run_id is None
    assert second.attempts == first.attempts == 1

    runs = _runs_for(session, event_id)
    assert len(runs) == 1
    jobs = _jobs_for(session, event_id)
    assert len(jobs) == 1


def test_transient_exhaustion_with_nothing_interpreted_stays_still_working(
    client: TestClient, session: Session
) -> None:
    """A transient failure that exhausts the bound with **nothing interpreted** never
    lands ``failed`` (FTY-372): the event stays ``processing`` (honest still-working)
    with a bounded, long-backoff auto-retry, well past the standard attempt bound."""

    user_id, event_id = _seed_event(client, "retry@example.com")
    # No parse step runs, so nothing is interpreted; every attempt fails transiently.
    failing = Pipeline([_FailStep()])

    # First two attempts fail transiently and ask for a standard retry; the event stays
    # ``processing`` and the job stays ``running``.
    for attempt in (1, 2):
        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=failing, max_attempts=3
        )
        assert result.should_retry is True
        assert result.attempts == attempt
        assert result.job_status is EstimationJobStatus.RUNNING
        # A standard transient retry leaves the countdown to the task's own schedule.
        assert result.retry_countdown_seconds is None
        event = session.get(LogEvent, event_id)
        assert event is not None and event.status == LogEventStatus.PROCESSING

    # The third attempt reaches the standard bound but does NOT fail: with nothing
    # interpreted the event stays still-working ``processing`` with a scheduled
    # long-backoff auto-retry.
    bound = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=failing, max_attempts=3
    )
    assert bound.should_retry is True
    assert bound.attempts == 3
    assert bound.job_status is EstimationJobStatus.RUNNING
    assert bound.event_status is LogEventStatus.PROCESSING
    # The still-working retry uses the long infra backoff (minutes), not the standard one.
    assert bound.retry_countdown_seconds is not None
    assert bound.retry_countdown_seconds >= 300

    # It keeps re-queuing (never ``failed``) until the extended infra ceiling, then stays
    # deferred still-working — still ``processing``, no auto-retry — and never terminal.
    result = bound
    while result.should_retry:
        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=failing, max_attempts=3
        )
    assert result.attempts == DEFAULT_MAX_INFRA_RETRY_ATTEMPTS
    assert result.event_status is LogEventStatus.PROCESSING
    assert result.job_status is EstimationJobStatus.RUNNING

    event = session.get(LogEvent, event_id)
    assert event is not None and event.status == LogEventStatus.PROCESSING
    runs = _runs_for(session, event_id)
    assert all(run.status == EstimationRunStatus.FAILED for run in runs)
    assert all(run.error == "transient_failure" for run in runs)


def test_unparseable_input_is_terminal_failed(client: TestClient, session: Session) -> None:
    """A deterministic non-food classification still lands terminal ``failed`` (FTY-372
    preserves the ``empty_input`` / narrowed ``unparseable_input`` terminal class)."""

    user_id, event_id = _seed_event(client, "unparseable@example.com")

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=Pipeline([_UnparseableStep()])
    )

    assert result.should_retry is False
    assert result.job_status is EstimationJobStatus.FAILED
    assert result.event_status is LogEventStatus.FAILED

    runs = _runs_for(session, event_id)
    assert len(runs) == 1
    assert runs[0].status == EstimationRunStatus.FAILED
    assert runs[0].error == "unparseable_input"


def test_needs_clarification_is_terminal(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "clarify@example.com")

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=Pipeline([_ClarifyStep()])
    )

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert result.should_retry is False

    # Terminal: re-delivery does not retry or create a new run.
    again = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=Pipeline([_ClarifyStep()])
    )
    assert again.run_id is None
    runs = _runs_for(session, event_id)
    assert len(runs) == 1
    assert runs[0].status == EstimationRunStatus.NEEDS_CLARIFICATION


def test_worker_enforces_ownership_fails_closed(client: TestClient, session: Session) -> None:
    _user_id, event_id = _seed_event(client, "owner@example.com")
    attacker_id = uuid.uuid4()

    with pytest.raises(EstimationEventNotFound):
        process_estimation(session, log_event_id=event_id, user_id=attacker_id)

    # The event was never claimed, and no run was created for the attacker.
    event = session.get(LogEvent, event_id)
    assert event is not None and event.status == LogEventStatus.PENDING
    runs = _runs_for(session, event_id)
    assert runs == []


def test_run_record_is_sanitized(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "sanitized@example.com")

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=_stub_pipeline())

    run = session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id)).one()
    # Reproducibility metadata is present; raw user text never is.
    assert run.tool_names == ["stub_parse", "stub_calculate"]
    assert run.user_id == user_id
    assert RAW_TEXT not in str(run.trace)
    assert run.error is None
