"""Postgres-parity guard for the clarify answer round-trip (FTY-171).

The resolve path is DB-heavy in exactly the ways SQLite is too permissive to
prove (*Verify at the highest applicable level*): the ``SELECT … FOR UPDATE``
event lock is a no-op on SQLite, the unique ``question_id`` idempotency anchor
and the ``NOT IN (subquery)`` unanswered-row replacement must hold under
Postgres semantics, and the state-machine transitions commit across several
sessions. This module drives the full loop — estimate → needs_clarification →
answer (service) → re-estimate → completed — against a live Postgres engine
with fixed fixtures and the network-free :class:`FakeProvider`.

Opt-in like the other Postgres guards: the ``pg_engine`` fixture skips when
``FATTY_TEST_DATABASE_URL`` is unset, so the SQLite-only path stays green
without a running Postgres; CI wires a real Postgres (FTY-144).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import EstimationJobStatus, LogEventStatus
from app.estimator.exercise_step import ExerciseCalculateStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationAnswer, ClarificationQuestion, DerivedExerciseItem
from app.models.estimation import EstimationJob
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services import clarification as clarification_service
from tests.conftest import upgrade

RAW_TEXT = "went for a run"
QUESTION = "How long was your run?"


def _seed_user(engine: Engine) -> uuid.UUID:
    factory = create_session_factory(engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id, weight_kg=70.0))
        session.commit()
        return user.id


def _seed_pending_event(engine: Engine, user_id: uuid.UUID) -> uuid.UUID:
    factory = create_session_factory(engine)
    with factory() as session:
        event = LogEvent(user_id=user_id, raw_text=RAW_TEXT, status=LogEventStatus.PENDING)
        session.add(event)
        session.commit()
        return event.id


def _clarify_pipeline(questions: list[str]) -> Pipeline:
    provider = FakeProvider(
        responses=[
            {
                "disposition": "needs_clarification",
                "confidence": 0.2,
                "items": [],
                "clarification_questions": questions,
            }
        ]
    )
    return Pipeline([ParseStep(provider), ExerciseCalculateStep()])


def _resolve_pipeline() -> tuple[Pipeline, FakeProvider]:
    provider = FakeProvider(
        responses=[
            {
                "disposition": "parsed",
                "confidence": 0.95,
                "items": [
                    {
                        "type": "exercise",
                        "name": "run",
                        "quantity_text": "30 min",
                        "unit": "min",
                        "amount": 30,
                    }
                ],
            }
        ]
    )
    return Pipeline([ParseStep(provider), ExerciseCalculateStep()]), provider


def test_answer_round_trip_on_postgres(pg_engine: Engine) -> None:
    """needs_clarification → answer → processing → completed, all under Postgres."""

    upgrade(pg_engine, "head")
    user_id = _seed_user(pg_engine)
    event_id = _seed_pending_event(pg_engine, user_id)
    factory = create_session_factory(pg_engine)

    # First estimate lands on needs_clarification with a persisted question and
    # a terminal job — the production shape the resolve starts from.
    with factory() as session:
        result = process_estimation(
            session,
            log_event_id=event_id,
            user_id=user_id,
            pipeline=_clarify_pipeline([QUESTION, "Road or trail?"]),
        )
        assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
        assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION

    # Resolve one question through the service: the answer persists, the job
    # re-opens, and the same event transitions needs_clarification → processing
    # atomically (the FOR UPDATE lock is real here).
    with factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        question_id = session.scalars(
            select(ClarificationQuestion.id)
            .where(ClarificationQuestion.log_event_id == event_id)
            .order_by(ClarificationQuestion.position.asc())
        ).first()
        assert question_id is not None
        event, resolved = clarification_service.answer_clarification_question(
            session, user_id, user, event_id, question_id, "30 minutes"
        )
        assert resolved is True
        assert event.id == event_id
        assert LogEventStatus(event.status) is LogEventStatus.PROCESSING
        assert event.raw_text == RAW_TEXT

        job = session.scalars(
            select(EstimationJob).where(EstimationJob.log_event_id == event_id)
        ).one()
        assert EstimationJobStatus(job.status) is EstimationJobStatus.QUEUED
        assert job.max_attempts == job.attempts + 3

        # The unique question_id anchor holds under Postgres: a replay converges
        # with no second row and no second transition.
        replay_event, replay_resolved = clarification_service.answer_clarification_question(
            session, user_id, user, event_id, question_id, "30 minutes"
        )
        assert replay_resolved is False
        assert replay_event.id == event_id
        answers = list(
            session.scalars(
                select(ClarificationAnswer).where(ClarificationAnswer.log_event_id == event_id)
            )
        )
        assert [a.answer_text for a in answers] == ["30 minutes"]

        # A fresh answer for the sibling question now conflicts (the event has
        # moved on) and mutates nothing.
        sibling_id = session.scalars(
            select(ClarificationQuestion.id).where(
                ClarificationQuestion.log_event_id == event_id,
                ClarificationQuestion.id != question_id,
            )
        ).one()
        with pytest.raises(clarification_service.NotAwaitingClarification):
            clarification_service.answer_clarification_question(
                session, user_id, user, event_id, sibling_id, "road"
            )

    # The answer-triggered re-estimate completes the same event; the answer is
    # folded into the prompt as structured input and the raw phrase is intact.
    with factory() as session:
        pipeline, provider = _resolve_pipeline()
        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=pipeline
        )
        assert result.event_status is LogEventStatus.COMPLETED
        assert result.job_status is EstimationJobStatus.SUCCEEDED
        assert f"Q: {QUESTION}" in provider.prompts[0]
        assert "A: 30 minutes" in provider.prompts[0]

        events = list(session.scalars(select(LogEvent).where(LogEvent.user_id == user_id)))
        assert len(events) == 1  # A5: never a duplicate entry
        assert events[0].raw_text == RAW_TEXT  # A3: raw phrase never mutated

        item = session.scalars(
            select(DerivedExerciseItem).where(DerivedExerciseItem.log_event_id == event_id)
        ).one()
        assert item.active_calories == 210.0


def test_sibling_answer_committed_after_read_conflicts_on_postgres(pg_engine: Engine) -> None:
    """The locked re-read sees committed sibling state under Postgres, not the
    session's pre-lock identity-map snapshot (FTY-171 review regression).

    The review repro: a session reads the event while it still awaits
    clarification, a sibling answer commits through a second session, and the
    first session then resolves its own question. The ``FOR UPDATE`` re-read
    must refresh (``populate_existing``) so the guard raises
    :class:`~app.services.clarification.NotAwaitingClarification` instead of
    persisting a second answer and re-opening the job for a second re-estimate.
    """

    upgrade(pg_engine, "head")
    user_id = _seed_user(pg_engine)
    event_id = _seed_pending_event(pg_engine, user_id)
    factory = create_session_factory(pg_engine)

    with factory() as session:
        process_estimation(
            session,
            log_event_id=event_id,
            user_id=user_id,
            pipeline=_clarify_pipeline([QUESTION, "Road or trail?"]),
        )

    with factory() as stale_session, factory() as sibling_session:
        # This session reads the event while it still awaits clarification …
        user = stale_session.get(User, user_id)
        assert user is not None
        stale_event = stale_session.get(LogEvent, event_id)
        assert stale_event is not None
        assert LogEventStatus(stale_event.status) is LogEventStatus.NEEDS_CLARIFICATION
        question_ids = list(
            stale_session.scalars(
                select(ClarificationQuestion.id)
                .where(ClarificationQuestion.log_event_id == event_id)
                .order_by(ClarificationQuestion.position.asc())
            )
        )

        # … a sibling answer lands concurrently through a second session and
        # commits the needs_clarification → processing transition …
        sibling_user = sibling_session.get(User, user_id)
        assert sibling_user is not None
        clarification_service.answer_clarification_question(
            sibling_session, user_id, sibling_user, event_id, question_ids[0], "30 minutes"
        )

        # … so the stale session's own resolve must conflict and mutate nothing.
        with pytest.raises(clarification_service.NotAwaitingClarification):
            clarification_service.answer_clarification_question(
                stale_session, user_id, user, event_id, question_ids[1], "road"
            )

    with factory() as session:
        answers = list(
            session.scalars(
                select(ClarificationAnswer.answer_text).where(
                    ClarificationAnswer.log_event_id == event_id
                )
            )
        )
        assert answers == ["30 minutes"]
        job = session.scalars(
            select(EstimationJob).where(EstimationJob.log_event_id == event_id)
        ).one()
        assert EstimationJobStatus(job.status) is EstimationJobStatus.QUEUED


def test_fresh_round_replaces_unanswered_rows_on_postgres(pg_engine: Engine) -> None:
    """The NOT IN (subquery) replacement deletes exactly the open rows on Postgres."""

    upgrade(pg_engine, "head")
    user_id = _seed_user(pg_engine)
    event_id = _seed_pending_event(pg_engine, user_id)
    factory = create_session_factory(pg_engine)

    with factory() as session:
        process_estimation(
            session,
            log_event_id=event_id,
            user_id=user_id,
            pipeline=_clarify_pipeline([QUESTION, "Road or trail?"]),
        )

    with factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        question_id = session.scalars(
            select(ClarificationQuestion.id)
            .where(ClarificationQuestion.log_event_id == event_id)
            .order_by(ClarificationQuestion.position.asc())
        ).first()
        assert question_id is not None
        clarification_service.answer_clarification_question(
            session, user_id, user, event_id, question_id, "30 minutes"
        )

    # Still ambiguous: the fresh round must replace the unanswered sibling while
    # keeping the answered question and its answer.
    with factory() as session:
        result = process_estimation(
            session,
            log_event_id=event_id,
            user_id=user_id,
            pipeline=_clarify_pipeline(["Was it a jog or a sprint?"]),
        )
        assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION

        remaining = sorted(
            session.scalars(
                select(ClarificationQuestion.question_text).where(
                    ClarificationQuestion.log_event_id == event_id
                )
            )
        )
        assert remaining == [QUESTION, "Was it a jog or a sprint?"]
        answers = list(
            session.scalars(
                select(ClarificationAnswer.answer_text).where(
                    ClarificationAnswer.log_event_id == event_id
                )
            )
        )
        assert answers == ["30 minutes"]
