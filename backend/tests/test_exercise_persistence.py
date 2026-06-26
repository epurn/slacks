"""End-to-end persistence tests for the exercise calculator through the worker (FTY-043).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`ExerciseCalculateStep` (parse backed by the
network-free :class:`FakeProvider`) against the migrated SQLite database, proving the
acceptance criteria across the trust boundary: a known activity with a duration and a
profile weight resolves into a ``resolved`` exercise item carrying the exact net
active calories; an unknown activity routes to ``needs_clarification``; and a missing
body weight fails closed with nothing persisted and no MET guessed.
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
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.exercise_step import ExerciseCalculateStep
from app.estimator.met_table import MET_TABLE_VERSION
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedExerciseItem
from app.models.estimation import EstimationRun
from app.models.identity import UserProfile


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _pipeline(item: dict[str, object]) -> Pipeline:
    """A real parse + exercise pipeline whose provider returns one parsed exercise."""

    provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [item]}]
    )
    return Pipeline([ParseStep(provider), ExerciseCalculateStep()])


def _seed_event(
    client: TestClient, email: str, raw_text: str = "a 30 min run"
) -> tuple[uuid.UUID, uuid.UUID]:
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


def _set_weight(session: Session, user_id: uuid.UUID, weight_kg: float) -> None:
    profile = session.scalars(select(UserProfile).where(UserProfile.user_id == user_id)).one()
    profile.weight_kg = weight_kg
    session.add(profile)
    session.commit()


def _exercise(session: Session, event_id: uuid.UUID) -> list[DerivedExerciseItem]:
    return list(
        session.scalars(
            select(DerivedExerciseItem).where(DerivedExerciseItem.log_event_id == event_id)
        )
    )


def test_exercise_resolves_with_active_calories_and_completes(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "exercise-ok@example.com")
    _set_weight(session, user_id, 70.0)
    pipeline = _pipeline(
        {"type": "exercise", "name": "run", "quantity_text": "30 min", "unit": "min", "amount": 30}
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    exercises = _exercise(session, event_id)
    assert [e.name for e in exercises] == ["run"]
    # running MET 7.0, 70 kg, 30 min: (7.0 - 1) * 70 * 0.5 = 210.0
    assert exercises[0].active_calories == 210.0
    assert exercises[0].status == DerivedItemStatus.RESOLVED
    assert exercises[0].user_id == user_id

    # The MET-table version is recorded as run evidence (reproducibility).
    run = session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id)).one()
    assert f"met_table:{MET_TABLE_VERSION}" in run.source_refs


def test_unknown_activity_needs_clarification(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "exercise-unknown@example.com")
    _set_weight(session, user_id, 70.0)
    pipeline = _pipeline(
        {"type": "exercise", "name": "teleporting", "quantity_text": "30 min", "amount": 30}
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    # No exercise rows are committed on the clarification path.
    assert _exercise(session, event_id) == []


def test_missing_weight_fails_closed(client: TestClient, session: Session) -> None:
    # No profile weight set: the burn cannot be computed, so the event fails closed
    # rather than guessing — terminal on the first attempt, nothing persisted.
    user_id, event_id = _seed_event(client, "exercise-noweight@example.com")
    pipeline = _pipeline(
        {"type": "exercise", "name": "run", "quantity_text": "30 min", "unit": "min", "amount": 30}
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.FAILED
    assert result.event_status is LogEventStatus.FAILED
    assert result.should_retry is False
    assert _exercise(session, event_id) == []
