"""Worker never-fail degrade / still-working routing tests (FTY-372).

These drive :func:`app.estimator.processing.process_estimation` against the migrated
SQLite database (no broker) with a stub pipeline that reproduces the residual
hard-exhaustion cases the FTY-371 in-pipeline soft-degrade does not already handle:

- a per-run ceiling breach (``RunBudgetExceeded``) **with** interpreted candidates
  lands ``completed`` with rough, honestly-labelled degrade rows — and makes **zero**
  additional provider calls (budget-free producer), committed atomically;
- the same breach **with nothing interpreted** keeps the event in the honest
  still-working ``processing`` state with a scheduled bounded, long-backoff auto-retry;
- a transient failure that exhausts the attempt bound degrades (with candidates) rather
  than failing;
- every degrade/still-working reason stays content-free (no raw diary text in
  ``run.error`` / ``run.trace``).

Terminal ``failed`` for deterministic non-food input and the standard-retry path are
covered in ``test_estimation_worker.py``; the scoped re-estimate breach is covered in
``test_item_scoped_partial_resolution.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, EstimationRunStatus, LogEventStatus
from app.estimator.degrade import (
    PROVIDER_TRANSIENT_EXHAUSTED,
    DegradeProducer,
    degraded_assumption,
)
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    Pipeline,
    StepError,
)
from app.estimator.processing import DEFAULT_MAX_INFRA_RETRY_ATTEMPTS, process_estimation
from app.estimator.run_budget import WALL_CLOCK_DEADLINE_EXCEEDED, RunBudgetExceeded
from app.llm.base import ImageInput, OutputT, Provider
from app.models.derived import DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource

RAW_TEXT = "banh mi on a brioche bun with shredded carrot, sriracha mayo, cucumber"


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


class _ExplodingProvider(Provider):
    """A provider that fails the test loudly if the budget-free degrade calls it.

    The worker safety-net degrade must make **no** provider call (FTY-372 uses the
    budget-free producer), so any ``structured_completion`` here is a contract breach.
    """

    name = "exploding"

    def __init__(self) -> None:
        super().__init__(timeout_seconds=1.0, max_retries=0)

    def structured_completion(
        self,
        prompt: str,
        schema: type[OutputT],
        *,
        images: Sequence[ImageInput] | None = None,
    ) -> OutputT:  # pragma: no cover - must never run in a budget-free degrade
        raise AssertionError("budget-free degrade must not make a provider call")

    def _complete(
        self,
        prompt: str,
        schema: Any,
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:  # pragma: no cover - never reached
        raise AssertionError("budget-free degrade must not make a provider call")


def _budget_free_producer() -> DegradeProducer:
    """A degrade producer whose provider explodes if a call is ever made."""

    return DegradeProducer(provider=_ExplodingProvider())


def _candidate() -> CandidateDraft:
    return CandidateDraft(name="banh mi", quantity_text="1 sandwich", unit=None, amount=1.0)


class _InterpretThenBreachStep:
    """Interpret one food candidate, then breach the per-run ceiling (hard exhaustion)."""

    name = "interpret_then_breach"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.food_candidates.append(_candidate())
        raise RunBudgetExceeded(WALL_CLOCK_DEADLINE_EXCEEDED)


class _BreachStep:
    """Breach the per-run ceiling before anything is interpreted (parse-phase breach)."""

    name = "breach"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        raise RunBudgetExceeded(WALL_CLOCK_DEADLINE_EXCEEDED)


class _InterpretThenTransientStep:
    """Interpret one candidate, then fail transiently (retryable ``StepError``)."""

    name = "interpret_then_transient"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.food_candidates.append(_candidate())
        raise StepError("transient_failure")


def _runs(session: Session, event_id: uuid.UUID) -> list[EstimationRun]:
    return list(
        session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id))
    )


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence(session: Session, event_id: uuid.UUID) -> list[EvidenceSource]:
    return list(
        session.scalars(select(EvidenceSource).where(EvidenceSource.log_event_id == event_id))
    )


def test_budget_breach_with_candidates_degrades_completed_rough_zero_calls(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "ncf-budget-candidates@example.com")

    result = process_estimation(
        session,
        log_event_id=event_id,
        user_id=user_id,
        pipeline=Pipeline([_InterpretThenBreachStep()]),
        degrade_producer=_budget_free_producer(),  # explodes on any provider call
    )

    # Never ``failed``: the interpreted candidate is committed as a rough estimate.
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert result.should_retry is False

    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    assert foods[0].name == "banh mi"
    assert foods[0].calories is not None and foods[0].calories > 0

    # The rough row carries the content-free degraded provenance marking.
    evidence = _evidence(session, event_id)
    assert len(evidence) == 1
    assert degraded_assumption(WALL_CLOCK_DEADLINE_EXCEEDED) in (evidence[0].assumptions or [])

    # A completed degrade is not a failure — no ``error`` on the run.
    run = _runs(session, event_id)[0]
    assert run.status == EstimationRunStatus.COMPLETED
    assert run.error is None


def test_budget_breach_with_nothing_interpreted_stays_still_working(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "ncf-budget-none@example.com")

    result = process_estimation(
        session,
        log_event_id=event_id,
        user_id=user_id,
        pipeline=Pipeline([_BreachStep()]),
        degrade_producer=_budget_free_producer(),
    )

    # Never ``failed``: nothing to estimate, so the event stays still-working
    # ``processing`` with a scheduled long-backoff auto-retry.
    assert result.event_status is LogEventStatus.PROCESSING
    assert result.job_status is EstimationJobStatus.RUNNING
    assert result.should_retry is True
    assert result.retry_countdown_seconds is not None and result.retry_countdown_seconds >= 300

    assert _foods(session, event_id) == []
    run = _runs(session, event_id)[0]
    assert run.status == EstimationRunStatus.FAILED
    # The run error is the fixed, content-free ceiling label — no raw diary text.
    assert run.error == WALL_CLOCK_DEADLINE_EXCEEDED
    assert RAW_TEXT not in str(run.trace)


def test_still_working_retries_are_bounded_then_deferred(
    client: TestClient, session: Session
) -> None:
    """The still-working state re-queues up to the extended ceiling, then stays
    deferred (still ``processing``, no auto-retry) — never terminal ``failed``."""

    user_id, event_id = _seed_event(client, "ncf-budget-bounded@example.com")
    pipeline = Pipeline([_BreachStep()])

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)
    while result.should_retry:
        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=pipeline
        )

    # Bounded: it stops re-queuing exactly at the extended infra ceiling.
    assert result.attempts == DEFAULT_MAX_INFRA_RETRY_ATTEMPTS
    assert result.should_retry is False
    # Deferred, not failed: the event is still ``processing`` and the job non-terminal.
    assert result.event_status is LogEventStatus.PROCESSING
    assert result.job_status is EstimationJobStatus.RUNNING


def test_transient_exhaustion_with_candidates_degrades_completed(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "ncf-transient-candidates@example.com")
    pipeline = Pipeline([_InterpretThenTransientStep()])

    # The standard retries do not degrade yet — they ask the caller to retry.
    for _ in range(2):
        result = process_estimation(
            session,
            log_event_id=event_id,
            user_id=user_id,
            pipeline=pipeline,
            max_attempts=3,
            degrade_producer=_budget_free_producer(),
        )
        assert result.should_retry is True
        assert result.event_status is LogEventStatus.PROCESSING

    # The attempt that reaches the bound degrades to a rough estimate — not ``failed``.
    final = process_estimation(
        session,
        log_event_id=event_id,
        user_id=user_id,
        pipeline=pipeline,
        max_attempts=3,
        degrade_producer=_budget_free_producer(),
    )
    assert final.event_status is LogEventStatus.COMPLETED
    assert final.job_status is EstimationJobStatus.SUCCEEDED
    assert final.should_retry is False

    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    evidence = _evidence(session, event_id)
    # A transient-exhaustion degrade carries the transient-exhausted degraded label.
    assert degraded_assumption(PROVIDER_TRANSIENT_EXHAUSTED) in (evidence[0].assumptions or [])
