"""Clarification answer (resolve) service — FTY-171, ``log-events.md`` v4.

Resolves one clarification question on the caller's own ``needs_clarification``
event by applying the answer as a **structured detail to the same event** and
re-estimating it. This is the first-class resolve that replaces the retired v3
mechanism (re-submitting a combined phrase through the create path), closing the
audit findings that mechanism produced:

- **A3** — the raw phrase is never mutated: the answer is persisted against the
  question and folded into the re-estimate as structured input; ``raw_text`` is
  untouched by construction (nothing in this path writes it).
- **A5** — no answer ever creates a second log event: the resolve transitions
  and re-estimates the **same** ``event_id`` and inserts no ``log_events`` row.

A fresh, valid answer atomically (one transaction): persists the
``clarification_answers`` row, **re-opens** the event's terminal
``needs_clarification`` estimation job for the answer-triggered re-estimate
(``estimation-jobs.md`` v2), and drives ``needs_clarification → processing``
through the state machine's single mutation path. The caller (router) then
enqueues the re-estimate — commit first, publish after, matching the create
path.

**Idempotent on retry (first-write-wins per question).** The unique
``question_id`` on ``clarification_answers`` is the idempotency anchor: an
already-answered question returns the event's current state with no new row, no
second transition, and no second enqueue; a divergent ``answer`` body on the
replay is ignored. Two concurrent submits for the same question converge — the
event row is locked (``SELECT … FOR UPDATE``, a no-op on SQLite) and the loser
of any remaining insert race catches the unique-index violation and re-reads the
committed sibling.

Authorization fails closed: the event is loaded scoped to the authenticated
owner and the question scoped to that event, so a cross-user or nonexistent
event — or a ``question_id`` that is not one of the event's questions — is
indistinguishable as "not found" and mutates nothing (no existence oracle).

``answer_text`` is sensitive user data (like ``raw_text``): never logged, never
copied into estimation-run ``trace``/``error``, returned only to the owner.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import EstimationJobStatus, LogEventStatus
from app.estimator.processing import DEFAULT_MAX_ATTEMPTS
from app.models.derived import ClarificationAnswer, ClarificationQuestion
from app.models.estimation import EstimationJob
from app.models.identity import User
from app.models.log_events import LogEvent
from app.services import log_events as log_event_service


class ClarificationQuestionNotFound(Exception):
    """Raised when ``question_id`` is not one of the owned event's questions."""


class NotAwaitingClarification(Exception):
    """Raised on a fresh answer for an event not in ``needs_clarification``.

    Nothing is persisted or mutated. Guards the race where the client holds
    questions from an earlier fetch (or a sibling answer lands concurrently) and
    the event has since moved on; a fresh clarification read never serves such a
    question (it is status-gated).
    """


def answer_clarification_question(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    event_id: uuid.UUID,
    question_id: uuid.UUID,
    answer_text: str,
) -> tuple[LogEvent, bool]:
    """Resolve one clarification question with the user's (validated) answer.

    ``answer_text`` is the already-validated, trimmed answer (see
    :class:`~app.schemas.log_events.ClarificationAnswerRequest` — the trust
    boundary that rejects an empty/whitespace/oversized answer with ``422``
    before any work).

    Returns ``(event, resolved)``. ``resolved`` is :data:`True` when this call
    freshly resolved the question — the caller must then enqueue the
    re-estimate and signal ``201`` — and :data:`False` for an idempotent replay
    of an already-answered question (``200``, no enqueue, event at its current
    status so the client reconciles rather than resetting).

    Raises :class:`~app.services.log_events.LogEventForbidden` /
    :class:`~app.services.log_events.LogEventNotFound` /
    :class:`ClarificationQuestionNotFound` (all rendered ``404``, fail closed)
    and :class:`NotAwaitingClarification` (rendered ``409``).
    """

    event = log_event_service.get_event(session, owner_id, current_user, event_id)

    # Serialize concurrent resolves on the same event: the row lock (Postgres;
    # a no-op on SQLite) makes the answered/status checks below read committed
    # sibling state rather than racing it.
    locked = session.scalars(
        select(LogEvent).where(LogEvent.id == event.id).with_for_update()
    ).one_or_none()
    if locked is None:
        raise log_event_service.LogEventNotFound("log event not found")
    event = locked

    question = session.scalars(
        select(ClarificationQuestion).where(
            ClarificationQuestion.id == question_id,
            ClarificationQuestion.log_event_id == event.id,
        )
    ).one_or_none()
    if question is None:
        # Fail closed: a foreign or unknown question id is indistinguishable
        # from a missing one, and nothing is mutated.
        raise ClarificationQuestionNotFound("clarification question not found")

    if _find_answer(session, question.id) is not None:
        # Idempotent replay: the question is already resolved. Return the
        # event's current state; a divergent answer body is ignored (changing a
        # resolved detail afterwards is the corrections path, not a resolve).
        session.commit()  # release the row lock without writing
        return event, False

    if LogEventStatus(event.status) is not LogEventStatus.NEEDS_CLARIFICATION:
        session.rollback()  # release the row lock; nothing persisted or mutated
        raise NotAwaitingClarification("not_awaiting_clarification")

    session.add(
        ClarificationAnswer(
            question_id=question.id,
            log_event_id=event.id,
            user_id=event.user_id,
            answer_text=answer_text,
        )
    )
    _reopen_job(session, event.id)
    try:
        # The single status mutation path; its commit lands the answer row, the
        # re-opened job, and the transition atomically.
        event = log_event_service.transition_event(session, event, LogEventStatus.PROCESSING)
    except IntegrityError:
        # A concurrent submit for the same question committed first and won the
        # unique question_id index. Converge on it as the idempotent replay: no
        # duplicate answer, no second re-estimate.
        session.rollback()
        if _find_answer(session, question_id) is None:
            raise
        event = log_event_service.get_event(session, owner_id, current_user, event_id)
        return event, False
    return event, True


def _find_answer(session: Session, question_id: uuid.UUID) -> ClarificationAnswer | None:
    """Return the persisted answer for ``question_id``, or ``None``."""

    return session.scalars(
        select(ClarificationAnswer).where(ClarificationAnswer.question_id == question_id)
    ).one_or_none()


def _reopen_job(session: Session, log_event_id: uuid.UUID) -> None:
    """Re-open the event's terminal estimation job for the answer-triggered run.

    ``estimation-jobs.md`` v2: the resolve — not the worker — re-opens the job,
    so a redelivered queue task for a terminal job stays a no-op and redelivery
    idempotency is preserved. The job returns to ``queued`` and its
    ``max_attempts`` is extended to grant the re-estimate a fresh bounded retry
    budget; ``attempts`` stays cumulative so run attempt numbers remain
    monotonic and the run history stays an honest audit trail. A missing job
    (an event seeded outside the worker) is fine: the worker's get-or-create
    covers it.
    """

    job = session.scalars(
        select(EstimationJob).where(EstimationJob.log_event_id == log_event_id)
    ).one_or_none()
    if job is None:
        return
    job.status = EstimationJobStatus.QUEUED
    job.max_attempts = job.attempts + DEFAULT_MAX_ATTEMPTS
    session.add(job)
