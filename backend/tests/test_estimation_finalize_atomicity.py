"""Atomicity tests for the estimation worker's terminal finalize (FTY-358).

These pin the transaction-boundary contract of
:func:`app.estimator.processing._finalize`: each terminal outcome commits its
persisted derived rows, its ``run``/``job`` status, and the event's status
transition in a **single** database transaction — the one inside
:func:`~app.services.log_events.transition_event`. There is no longer a window in
which resolved rows are durably committed while the event is still ``processing``.

The tests drive ``_finalize`` directly, in the exact state
:func:`~app.estimator.processing.process_estimation` leaves before it (event
``processing``, job/run ``running``), so they can spy on ``session.commit`` and
observe durability from an independent session on the same file-backed database:

- each terminal outcome (COMPLETED / NEEDS_CLARIFICATION / FAILED-terminal) issues
  exactly one commit and leaves the derived rows + statuses durable together;
- an illegal transition on the COMPLETED path (forced via a seam that makes
  ``transition_event`` raise) commits **nothing** — the event stays ``processing``
  with no resolved rows, proving the persisted rows can no longer outlive a
  rejected transition;
- the retry (non-terminal FAILED) branch commits once and transitions nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import (
    DerivedItemStatus,
    EstimationJobStatus,
    EstimationRunStatus,
    LogEventStatus,
)
from app.estimator import processing
from app.estimator.pipeline import (
    ClarificationDraft,
    EstimationContext,
    PipelineOutcome,
    PipelineResult,
    ResolvedFoodItem,
)
from app.estimator.processing import _finalize
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationJob, EstimationRun
from app.models.log_events import LogEvent
from app.services.log_events import IllegalTransition, transition_event

RAW_TEXT = "150g rice and dal at 7pm"


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _seed_event(client: TestClient, email: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Register a user and create a pending event; return ``(user_id, event_id)``."""

    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"

    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": RAW_TEXT},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


def _prep_processing_state(
    session: Session,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    *,
    attempts: int = 1,
    max_attempts: int = 3,
) -> tuple[EstimationJob, LogEvent, EstimationRun]:
    """Advance a fresh event to the exact state ``_finalize`` is invoked in.

    The event is claimed (``pending → processing``) and a ``running`` job/run are
    committed, mirroring :func:`process_estimation` right before it calls
    ``_finalize``. Returns ``(job, event, run)``.
    """

    event = session.get(LogEvent, event_id)
    assert event is not None
    transition_event(session, event, LogEventStatus.PROCESSING)

    job = EstimationJob(
        log_event_id=event_id,
        user_id=user_id,
        status=EstimationJobStatus.RUNNING,
        attempts=attempts,
        max_attempts=max_attempts,
        idempotency_key=str(event_id),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    run = EstimationRun(
        job_id=job.id,
        log_event_id=event_id,
        user_id=user_id,
        attempt=attempts,
        status=EstimationRunStatus.RUNNING,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return job, event, run


def _context(event_id: uuid.UUID, user_id: uuid.UUID) -> EstimationContext:
    return EstimationContext(log_event_id=event_id, user_id=user_id, raw_text=RAW_TEXT)


def _with_resolved_food(context: EstimationContext) -> EstimationContext:
    """Add one realistically-shaped resolved food item to ``context``.

    Persisting it writes a ``resolved`` ``derived_food_items`` row plus its
    ``evidence_sources`` provenance row — the sensitive nutrition rows whose
    atomic commit this story guards.
    """

    context.resolved_food_items.append(
        ResolvedFoodItem(
            name="white rice",
            quantity_text="1 serving",
            unit=None,
            amount=1.0,
            grams=150.0,
            calories=205.0,
            protein_g=4.3,
            carbs_g=44.5,
            fat_g=0.4,
            product_id=None,
            source_type="trusted_nutrition_database",
            source_ref="usda_fdc:168880",
            content_hash="hash-rice",
            fetched_at=datetime(2026, 7, 11, tzinfo=UTC),
            calories_per_100g=137.0,
            protein_per_100g=2.9,
            carbs_per_100g=29.7,
            fat_per_100g=0.3,
        )
    )
    return context


def _commit_spy(session: Session) -> list[int]:
    """Wrap ``session.commit`` with a call counter; return the (mutable) call log."""

    real: Callable[[], None] = session.commit
    calls: list[int] = []

    def spy() -> None:
        calls.append(1)
        real()

    session.commit = spy  # type: ignore[method-assign]
    return calls


def _get_event(session: Session, event_id: uuid.UUID) -> LogEvent:
    event = session.get(LogEvent, event_id)
    assert event is not None
    return event


def _get_job(session: Session, job_id: uuid.UUID) -> EstimationJob:
    job = session.get(EstimationJob, job_id)
    assert job is not None
    return job


def _get_run(session: Session, run_id: uuid.UUID) -> EstimationRun:
    run = session.get(EstimationRun, run_id)
    assert run is not None
    return run


def _resolved_food_rows(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(
            select(DerivedFoodItem).where(
                DerivedFoodItem.log_event_id == event_id,
                DerivedFoodItem.status == DerivedItemStatus.RESOLVED,
            )
        )
    )


def test_completed_finalize_commits_once_and_persists_atomically(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "atomic-completed@example.com")
    job, event, run = _prep_processing_state(session, user_id, event_id)
    context = _with_resolved_food(_context(event_id, user_id))

    calls = _commit_spy(session)
    result = PipelineResult(PipelineOutcome.COMPLETED, None)
    out = _finalize(session, job, event, run, result, context)

    # Exactly one commit — the transition's — flushed the whole terminal state.
    assert len(calls) == 1
    assert out.event_status is LogEventStatus.COMPLETED

    # Rows, run/job status, and event status are all durable together after it.
    assert _get_event(session, event_id).status == LogEventStatus.COMPLETED
    assert _get_job(session, job.id).status == EstimationJobStatus.SUCCEEDED
    assert _get_run(session, run.id).status == EstimationRunStatus.COMPLETED
    foods = _resolved_food_rows(session, event_id)
    assert len(foods) == 1
    assert foods[0].calories == 205.0


def test_needs_clarification_finalize_commits_once_and_persists_atomically(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "atomic-clarify@example.com")
    job, event, run = _prep_processing_state(session, user_id, event_id)
    context = _context(event_id, user_id)
    context.clarification_questions.append(
        ClarificationDraft(text="How much milk?", options=["1 cup", "a splash"])
    )

    calls = _commit_spy(session)
    result = PipelineResult(PipelineOutcome.NEEDS_CLARIFICATION, "ambiguous")
    out = _finalize(session, job, event, run, result, context)

    assert len(calls) == 1
    assert out.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _get_event(session, event_id).status == LogEventStatus.NEEDS_CLARIFICATION
    assert _get_job(session, job.id).status == EstimationJobStatus.NEEDS_CLARIFICATION
    assert _get_run(session, run.id).status == EstimationRunStatus.NEEDS_CLARIFICATION
    questions = list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )
    assert len(questions) == 1
    assert questions[0].question_text == "How much milk?"


def test_failed_terminal_finalize_commits_once_and_persists_no_rows(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "atomic-failed@example.com")
    # attempts == max_attempts so a retryable failure is nonetheless terminal.
    job, event, run = _prep_processing_state(session, user_id, event_id, attempts=3, max_attempts=3)
    context = _context(event_id, user_id)

    calls = _commit_spy(session)
    result = PipelineResult(PipelineOutcome.FAILED, "boom", retryable=True)
    out = _finalize(session, job, event, run, result, context)

    assert len(calls) == 1
    assert out.should_retry is False
    assert out.event_status is LogEventStatus.FAILED
    assert _get_event(session, event_id).status == LogEventStatus.FAILED
    assert _get_job(session, job.id).status == EstimationJobStatus.FAILED
    failed_run = _get_run(session, run.id)
    assert failed_run.status == EstimationRunStatus.FAILED
    assert failed_run.error == "boom"
    # A failed outcome persists no derived data.
    assert _resolved_food_rows(session, event_id) == []


def test_illegal_transition_on_completed_commits_nothing(
    client: TestClient, session: Session, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, event_id = _seed_event(client, "atomic-illegal@example.com")
    job, event, run = _prep_processing_state(session, user_id, event_id)
    context = _with_resolved_food(_context(event_id, user_id))

    # Seam: force the event transition to be rejected. The guard runs before any
    # commit, so nothing the COMPLETED branch staged may become durable.
    def _reject(_session: Session, _event: LogEvent, _target: LogEventStatus) -> LogEvent:
        raise IllegalTransition("forced illegal transition")

    monkeypatch.setattr(processing, "transition_event", _reject)

    calls = _commit_spy(session)
    result = PipelineResult(PipelineOutcome.COMPLETED, None)
    with pytest.raises(IllegalTransition):
        _finalize(session, job, event, run, result, context)

    # _finalize committed nothing; discard the staged-but-uncommitted mutations.
    assert calls == []
    session.rollback()

    # An independent session sees only durable state: the event never left
    # ``processing``, no resolved rows were committed, and the run/job stayed
    # ``running`` — the rows can no longer outlive a rejected transition.
    factory = create_session_factory(db_engine)
    with factory() as verify:
        assert _get_event(verify, event_id).status == LogEventStatus.PROCESSING
        assert (
            list(
                verify.scalars(
                    select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
                )
            )
            == []
        )
        assert _get_job(verify, job.id).status == EstimationJobStatus.RUNNING
        assert _get_run(verify, run.id).status == EstimationRunStatus.RUNNING


def test_retry_branch_commits_once_and_transitions_nothing(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "atomic-retry@example.com")
    # attempts < max_attempts so a retryable failure keeps the job running.
    job, event, run = _prep_processing_state(session, user_id, event_id, attempts=1, max_attempts=3)
    context = _context(event_id, user_id)

    calls = _commit_spy(session)
    result = PipelineResult(PipelineOutcome.FAILED, "transient", retryable=True)
    out = _finalize(session, job, event, run, result, context)

    # One commit, and no transition: the event stays ``processing``.
    assert len(calls) == 1
    assert out.should_retry is True
    assert _get_event(session, event_id).status == LogEventStatus.PROCESSING
    assert _get_job(session, job.id).status == EstimationJobStatus.RUNNING
    assert _get_run(session, run.id).status == EstimationRunStatus.FAILED
    assert _resolved_food_rows(session, event_id) == []
