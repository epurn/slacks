"""Clarification answer (resolve) round-trip tests — FTY-171, ``log-events.md`` v4.

The answer endpoint is the trust-loop's resolve: it applies a structured detail
to the **same** ``needs_clarification`` event and re-estimates it. These tests
drive the full loop through the API plus the real worker core
(:func:`app.estimator.processing.process_estimation` with the network-free
:class:`FakeProvider`), proving the acceptance criteria:

- answering resolves the same entry (``needs_clarification → processing →
  completed``) and the entry then counts toward the day's totals;
- the raw phrase is never mutated and no duplicate event is created (A3);
- an empty/whitespace answer is rejected ``422`` with no state change and no
  new row (A5);
- the resolve is idempotent on retry (one answer row, one re-estimate);
- a fresh answer for an event that moved on is ``409`` and mutates nothing;
- cross-user / nonexistent / foreign-question access fails closed as ``404``;
- the job is re-opened for the answer-triggered run and a still-ambiguous
  re-estimate replaces the unanswered question rows;
- the sensitive answer text never reaches logs or the sanitized run record.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import EstimationJobStatus, LogEventStatus
from app.estimator.exercise_step import ExerciseCalculateStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationAnswer, ClarificationQuestion, DerivedExerciseItem
from app.models.estimation import EstimationJob, EstimationRun
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services import clarification as clarification_service
from tests.conftest import RecordingEnqueuer

RAW_TEXT = "went for a run"
QUESTION = "How long was your run?"
ANSWER = "30 minutes"


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _register(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user, returning ``(user_id, auth_header_value)``."""

    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _create_event(client: TestClient, user_id: str, auth: str, raw_text: str = RAW_TEXT) -> str:
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": raw_text},
    )
    assert created.status_code == 201
    return str(created.json()["id"])


def _clarify_question(text: str) -> dict[str, object]:
    if "road or trail" in text.casefold():
        options = ["Road", "Trail"]
    elif "jog or a sprint" in text.casefold():
        options = ["Jog", "Sprint"]
    else:
        options = ["15 minutes", "30 minutes", "45 minutes"]
    return {"text": text, "options": options}


def _clarify_pipeline(questions: list[str]) -> Pipeline:
    """A real parse pipeline whose provider routes to needs_clarification.

    The parse step draws its replies through the FTY-158/159 self-consistency
    sampler (first window 2, unanimous early stop), so the scripted reply is
    duplicated once per window sample.
    """

    provider = FakeProvider(
        responses=[
            {
                "disposition": "needs_clarification",
                "confidence": 0.2,
                "items": [],
                "clarification_questions": [_clarify_question(question) for question in questions],
            }
        ]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    return Pipeline([ParseStep(provider), ExerciseCalculateStep()])


def _resolve_pipeline(item: dict[str, object]) -> tuple[Pipeline, FakeProvider]:
    """A real parse + exercise pipeline returning one parsed item, plus its provider."""

    provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [item]}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    return Pipeline([ParseStep(provider), ExerciseCalculateStep()]), provider


def _set_weight(session: Session, user_id: str, weight_kg: float = 70.0) -> None:
    profile = session.scalars(
        select(UserProfile).where(UserProfile.user_id == uuid.UUID(user_id))
    ).one()
    profile.weight_kg = weight_kg
    session.add(profile)
    session.commit()


def _drive_to_needs_clarification(
    client: TestClient,
    session: Session,
    email: str,
    *,
    questions: list[str] | None = None,
    raw_text: str = RAW_TEXT,
) -> tuple[str, str, str, list[str]]:
    """Create an event through the API and estimate it to ``needs_clarification``.

    Runs the real worker core with a clarifying fake-provider parse, so the
    event, its terminal job, and its persisted question rows are exactly what
    production writes. Returns ``(user_id, auth, event_id, question_ids)``.
    """

    user_id, auth = _register(client, email)
    _set_weight(session, user_id)
    event_id = _create_event(client, user_id, auth, raw_text)
    result = process_estimation(
        session,
        log_event_id=uuid.UUID(event_id),
        user_id=uuid.UUID(user_id),
        pipeline=_clarify_pipeline(questions or [QUESTION]),
    )
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION

    read = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )
    assert read.status_code == 200
    question_ids = [q["id"] for q in read.json()["questions"]]
    return user_id, auth, event_id, question_ids


def _post_answer(
    client: TestClient, user_id: str, auth: str, event_id: str, question_id: str, answer: str
) -> httpx.Response:
    return cast(
        httpx.Response,
        client.post(
            f"/api/users/{user_id}/log-events/{event_id}/clarification/answers",
            headers={"Authorization": auth},
            json={"question_id": question_id, "answer": answer},
        ),
    )


def _event_rows(session: Session, user_id: str) -> list[LogEvent]:
    return list(session.scalars(select(LogEvent).where(LogEvent.user_id == uuid.UUID(user_id))))


def _answer_rows(session: Session, event_id: str) -> list[ClarificationAnswer]:
    return list(
        session.scalars(
            select(ClarificationAnswer).where(
                ClarificationAnswer.log_event_id == uuid.UUID(event_id)
            )
        )
    )


def test_answer_resolves_same_entry_and_it_counts(
    client: TestClient, session: Session, enqueuer: RecordingEnqueuer
) -> None:
    """The winnable clarify loop: ask → answer → same entry re-estimates → counts."""

    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client, session, "answer-flow@example.com"
    )

    resp = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)

    # Fresh resolve: 201, the SAME event, now processing; re-estimate enqueued
    # (one create enqueue + one answer enqueue).
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == event_id
    assert body["status"] == "processing"
    assert body["raw_text"] == RAW_TEXT
    assert [str(e) for e, _u in enqueuer.calls] == [event_id, event_id]

    # The answer re-opened the terminal job for the answer-triggered run with a
    # fresh bounded retry budget (estimation-jobs.md v2).
    job = session.scalars(
        select(EstimationJob).where(EstimationJob.log_event_id == uuid.UUID(event_id))
    ).one()
    assert EstimationJobStatus(job.status) is EstimationJobStatus.QUEUED
    assert job.max_attempts == job.attempts + 3

    # The worker re-estimates the same event with the answer folded in as
    # structured input — the raw phrase is passed through unchanged.
    pipeline, provider = _resolve_pipeline(
        {"type": "exercise", "name": "run", "quantity_text": "30 min", "unit": "min", "amount": 30}
    )
    result = process_estimation(
        session,
        log_event_id=uuid.UUID(event_id),
        user_id=uuid.UUID(user_id),
        pipeline=pipeline,
    )
    assert result.event_status is LogEventStatus.COMPLETED
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    prompt = provider.prompts[0]
    assert RAW_TEXT in prompt
    assert "<clarification_answers>" in prompt
    assert f"Q: {QUESTION}" in prompt
    assert f"A: {ANSWER}" in prompt

    # A3/A5: the raw phrase was never mutated and no second event exists.
    events = _event_rows(session, user_id)
    assert len(events) == 1
    assert events[0].raw_text == RAW_TEXT

    # The resolved entry counts toward the day's totals.
    item = session.scalars(
        select(DerivedExerciseItem).where(DerivedExerciseItem.log_event_id == uuid.UUID(event_id))
    ).one()
    # running MET 7.0, 70 kg, 30 min: (7.0 - 1) * 70 * 0.5 = 210.0
    assert item.active_calories == 210.0
    summary = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
    )
    assert summary.status_code == 200
    assert summary.json()["exercise"]["active_calories"] == 210.0

    # The answered question is resolved: the status-gated read serves nothing.
    read = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )
    assert read.json() == {"questions": []}

    # The sensitive answer text never lands in the sanitized run record.
    runs = list(
        session.scalars(
            select(EstimationRun).where(EstimationRun.log_event_id == uuid.UUID(event_id))
        )
    )
    assert len(runs) == 2
    assert [run.attempt for run in runs] == [1, 2]
    for run in runs:
        recorded = f"{run.trace!r} {run.error!r} {run.assumptions!r} {run.validation_errors!r}"
        assert ANSWER not in recorded
        assert QUESTION not in recorded
        assert RAW_TEXT not in recorded


def test_still_ambiguous_reestimate_replaces_unanswered_questions(
    client: TestClient, session: Session
) -> None:
    """A fresh clarification round replaces the open rows; answered ones are kept."""

    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client,
        session,
        "answer-fresh-round@example.com",
        questions=[QUESTION, "Road or trail?"],
    )
    assert len(question_ids) == 2

    resp = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)
    assert resp.status_code == 201

    # The re-estimate is still genuinely ambiguous and raises a fresh round.
    result = process_estimation(
        session,
        log_event_id=uuid.UUID(event_id),
        user_id=uuid.UUID(user_id),
        pipeline=_clarify_pipeline(["Was it a jog or a sprint?"]),
    )
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION

    # The read serves exactly the fresh round's question: the answered question
    # is kept-but-resolved and the stale unanswered sibling was replaced.
    read = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )
    questions = read.json()["questions"]
    assert [q["text"] for q in questions] == ["Was it a jog or a sprint?"]

    remaining = list(
        session.scalars(
            select(ClarificationQuestion).where(
                ClarificationQuestion.log_event_id == uuid.UUID(event_id)
            )
        )
    )
    remaining_texts = sorted(q.question_text for q in remaining)
    assert remaining_texts == [QUESTION, "Was it a jog or a sprint?"]

    # The kept answer still carries the accumulated detail for the next round.
    answers = _answer_rows(session, event_id)
    assert [a.answer_text for a in answers] == [ANSWER]

    # Answering the fresh round's question works (the loop stays winnable).
    fresh = _post_answer(client, user_id, auth, event_id, questions[0]["id"], "a jog")
    assert fresh.status_code == 201
    assert fresh.json()["status"] == "processing"


def test_empty_and_whitespace_answers_rejected_422(
    client: TestClient, session: Session, enqueuer: RecordingEnqueuer
) -> None:
    """A5 regression: an empty answer is rejected before any work — no state
    change, no new row, no enqueue, and never a duplicate entry."""

    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client, session, "answer-empty@example.com"
    )
    enqueue_count = len(enqueuer.calls)

    for bad in ["", "   ", "\n\t"]:
        resp = _post_answer(client, user_id, auth, event_id, question_ids[0], bad)
        assert resp.status_code == 422

    polled = client.get(
        f"/api/users/{user_id}/log-events/{event_id}",
        headers={"Authorization": auth},
    )
    assert polled.json()["status"] == "needs_clarification"
    assert polled.json()["raw_text"] == RAW_TEXT
    assert _answer_rows(session, event_id) == []
    assert len(_event_rows(session, user_id)) == 1  # no duplicate entry (A5)
    assert len(enqueuer.calls) == enqueue_count  # no re-estimate published


def test_request_boundary_validation(client: TestClient, session: Session) -> None:
    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client, session, "answer-validation@example.com"
    )
    url = f"/api/users/{user_id}/log-events/{event_id}/clarification/answers"
    headers = {"Authorization": auth}

    oversized = client.post(
        url, headers=headers, json={"question_id": question_ids[0], "answer": "x" * 301}
    )
    malformed_id = client.post(
        url, headers=headers, json={"question_id": "not-a-uuid", "answer": ANSWER}
    )
    missing_answer = client.post(url, headers=headers, json={"question_id": question_ids[0]})
    unknown_key = client.post(
        url,
        headers=headers,
        json={"question_id": question_ids[0], "answer": ANSWER, "raw_text": "injected"},
    )
    wrong_type = client.post(
        url, headers=headers, json={"question_id": question_ids[0], "answer": 4}
    )

    for resp in (oversized, malformed_id, missing_answer, unknown_key, wrong_type):
        assert resp.status_code == 422
    assert _answer_rows(session, event_id) == []


def test_idempotent_replay_converges(
    client: TestClient, session: Session, enqueuer: RecordingEnqueuer
) -> None:
    """A re-sent answer converges to the one resolved entry: no new row, no
    second transition, no double re-estimate, and the replay reflects the
    event's current status."""

    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client, session, "answer-idempotent@example.com"
    )

    fresh = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)
    assert fresh.status_code == 201
    enqueues_after_fresh = len(enqueuer.calls)

    replay = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)
    assert replay.status_code == 200
    assert replay.json()["id"] == event_id
    assert replay.json()["status"] == "processing"

    # A divergent body under the same question id is ignored (first-write-wins).
    divergent = _post_answer(client, user_id, auth, event_id, question_ids[0], "90 minutes")
    assert divergent.status_code == 200

    answers = _answer_rows(session, event_id)
    assert [a.answer_text for a in answers] == [ANSWER]
    assert len(enqueuer.calls) == enqueues_after_fresh  # no orphaned second re-estimate

    # Once the re-estimate completes, the replay reflects the terminal status —
    # the client reconciles rather than resetting the entry.
    pipeline, _provider = _resolve_pipeline(
        {"type": "exercise", "name": "run", "quantity_text": "30 min", "unit": "min", "amount": 30}
    )
    process_estimation(
        session, log_event_id=uuid.UUID(event_id), user_id=uuid.UUID(user_id), pipeline=pipeline
    )
    late_replay = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)
    assert late_replay.status_code == 200
    assert late_replay.json()["status"] == "completed"
    assert len(enqueuer.calls) == enqueues_after_fresh
    assert len(_event_rows(session, user_id)) == 1


def test_fresh_answer_after_event_moved_on_conflicts(
    client: TestClient, session: Session, enqueuer: RecordingEnqueuer
) -> None:
    """A fresh answer for a question whose event already left
    needs_clarification (a sibling answer drove it to processing) is 409 and
    mutates nothing."""

    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client,
        session,
        "answer-conflict@example.com",
        questions=[QUESTION, "Road or trail?"],
    )

    first = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)
    assert first.status_code == 201
    enqueue_count = len(enqueuer.calls)

    stale = _post_answer(client, user_id, auth, event_id, question_ids[1], "road")
    assert stale.status_code == 409
    assert stale.json()["detail"] == {"error": "not_awaiting_clarification"}
    assert [a.answer_text for a in _answer_rows(session, event_id)] == [ANSWER]
    assert len(enqueuer.calls) == enqueue_count

    polled = client.get(
        f"/api/users/{user_id}/log-events/{event_id}",
        headers={"Authorization": auth},
    )
    assert polled.json()["status"] == "processing"


def test_sibling_answer_committed_after_read_still_conflicts(
    client: TestClient, session: Session, enqueuer: RecordingEnqueuer
) -> None:
    """The post-lock status check reads committed sibling state, not the
    session's pre-lock identity-map snapshot (FTY-171 review regression).

    Single-threaded interleaving: this session loads the event while it still
    awaits clarification, a sibling answer then commits through another session
    (the API client's) and moves the event on, and only then does this session
    resolve its own question. Without ``populate_existing`` on the locked
    re-read, the stale snapshot lets the resolve through — persisting a second
    answer and enqueueing a second re-estimate; it must instead raise
    :class:`~app.services.clarification.NotAwaitingClarification` (the 409) and
    mutate nothing.
    """

    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client,
        session,
        "answer-stale-read@example.com",
        questions=[QUESTION, "Road or trail?"],
    )

    # Warm this session's identity map: the event is loaded while still
    # awaiting clarification and stays loaded (expire_on_commit=False).
    stale_event = session.scalars(select(LogEvent).where(LogEvent.id == uuid.UUID(event_id))).one()
    assert LogEventStatus(stale_event.status) is LogEventStatus.NEEDS_CLARIFICATION

    # The sibling answer lands "concurrently": it commits through the API's own
    # session, resolving its question and driving the event to processing.
    sibling = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)
    assert sibling.status_code == 201
    enqueue_count = len(enqueuer.calls)

    user = session.get(User, uuid.UUID(user_id))
    assert user is not None
    with pytest.raises(clarification_service.NotAwaitingClarification):
        clarification_service.answer_clarification_question(
            session,
            uuid.UUID(user_id),
            user,
            uuid.UUID(event_id),
            uuid.UUID(question_ids[1]),
            "road",
        )

    # Nothing persisted or mutated: one answer row, no second re-estimate, and
    # the event stays where the sibling left it.
    assert [a.answer_text for a in _answer_rows(session, event_id)] == [ANSWER]
    assert len(enqueuer.calls) == enqueue_count
    status = session.scalars(
        select(LogEvent.status).where(LogEvent.id == uuid.UUID(event_id))
    ).one()
    assert LogEventStatus(status) is LogEventStatus.PROCESSING


def test_cross_user_and_unknown_access_fails_closed(client: TestClient, session: Session) -> None:
    """Cross-user event, nonexistent event, and a foreign question id are all an
    indistinguishable 404, with nothing persisted (no existence oracle)."""

    bob_id, bob_auth, bob_event_id, bob_question_ids = _drive_to_needs_clarification(
        client, session, "answer-bob@example.com"
    )
    alice_id, alice_auth, alice_event_id, alice_question_ids = _drive_to_needs_clarification(
        client, session, "answer-alice@example.com"
    )

    via_bob_path = _post_answer(
        client, bob_id, alice_auth, bob_event_id, bob_question_ids[0], ANSWER
    )
    via_alice_path = _post_answer(
        client, alice_id, alice_auth, bob_event_id, bob_question_ids[0], ANSWER
    )
    unknown_event = _post_answer(
        client, alice_id, alice_auth, str(uuid.uuid4()), alice_question_ids[0], ANSWER
    )
    # A well-formed question id that belongs to a different event fails closed
    # too — the question is resolved scoped to the addressed event.
    foreign_question = _post_answer(
        client, alice_id, alice_auth, alice_event_id, str(uuid.uuid4()), ANSWER
    )
    cross_event_question = _post_answer(
        client, alice_id, alice_auth, alice_event_id, bob_question_ids[0], ANSWER
    )

    for resp in (
        via_bob_path,
        via_alice_path,
        unknown_event,
        foreign_question,
        cross_event_question,
    ):
        assert resp.status_code == 404
    assert _answer_rows(session, bob_event_id) == []
    assert _answer_rows(session, alice_event_id) == []
    for event_id in (bob_event_id, alice_event_id):
        event = session.scalars(select(LogEvent).where(LogEvent.id == uuid.UUID(event_id))).one()
        assert LogEventStatus(event.status) is LogEventStatus.NEEDS_CLARIFICATION


def test_requires_authentication(client: TestClient, session: Session) -> None:
    user_id, _auth, event_id, question_ids = _drive_to_needs_clarification(
        client, session, "answer-noauth@example.com"
    )
    url = f"/api/users/{user_id}/log-events/{event_id}/clarification/answers"
    body = {"question_id": question_ids[0], "answer": ANSWER}

    missing = client.post(url, json=body)
    bad_token = client.post(url, headers={"Authorization": "Bearer not-a-real-token"}, json=body)

    assert missing.status_code == 401
    assert bad_token.status_code == 401


def test_answer_and_question_text_absent_from_logs(
    client: TestClient, session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, auth, event_id, question_ids = _drive_to_needs_clarification(
        client, session, "answer-nolog@example.com"
    )

    with caplog.at_level("DEBUG"):
        resp = _post_answer(client, user_id, auth, event_id, question_ids[0], ANSWER)

    assert resp.status_code == 201
    assert ANSWER not in caplog.text
    assert QUESTION not in caplog.text
    assert RAW_TEXT not in caplog.text
