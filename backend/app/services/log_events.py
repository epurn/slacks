"""Log-event service and status state machine (FTY-030).

This module owns two contracts:

1. **Object-level authorization.** Every access path runs through
   :func:`_authorize`, which fails closed: a caller may only create, list, or
   read *their own* log events. A mismatch raises :class:`LogEventForbidden`,
   which the router renders as ``404`` so the API never confirms another user's
   events exist.

2. **The log-event status state machine.** :data:`LEGAL_TRANSITIONS` is the
   named, single-source-of-truth transition map for
   :class:`~app.enums.LogEventStatus`. Later stories (the Milestone 4 estimator)
   drive the ``processing``/``failed``/``needs_clarification`` transitions by
   reusing this map, not by redefining the vocabulary. FTY-030 implements
   creation at ``pending`` and the ``pending → completed`` transition; an illegal
   transition is rejected with :class:`IllegalTransition`.

``raw_text`` is sensitive personal data and is never written to logs.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import LogEventStatus
from app.models.derived import ClarificationAnswer, ClarificationQuestion
from app.models.identity import User
from app.models.log_events import LogEvent
from app.timeutils import current_day, day_bounds_utc, user_timezone

#: The log-event status state machine: each status maps to the set of statuses
#: it may legally transition to. Terminal statuses map to an empty set. This is
#: the named contract other stories extend; do not redefine it elsewhere.
#:
#: - ``pending`` → ``processing`` (estimator picks the event up) or
#:   ``completed`` (the direct path FTY-030 exercises before the estimator
#:   exists).
#: - ``processing`` → ``completed`` / ``failed`` / ``needs_clarification``
#:   (estimator outcomes, Milestone 4).
#: - ``needs_clarification`` → ``processing`` (re-run after the user clarifies).
#: - ``completed`` / ``failed`` are terminal.
LEGAL_TRANSITIONS: dict[LogEventStatus, frozenset[LogEventStatus]] = {
    LogEventStatus.PENDING: frozenset({LogEventStatus.PROCESSING, LogEventStatus.COMPLETED}),
    LogEventStatus.PROCESSING: frozenset(
        {
            LogEventStatus.COMPLETED,
            LogEventStatus.FAILED,
            LogEventStatus.NEEDS_CLARIFICATION,
        }
    ),
    LogEventStatus.NEEDS_CLARIFICATION: frozenset({LogEventStatus.PROCESSING}),
    LogEventStatus.COMPLETED: frozenset(),
    LogEventStatus.FAILED: frozenset(),
}


class LogEventForbidden(Exception):
    """Raised when a caller tries to access log events they do not own."""


class LogEventNotFound(Exception):
    """Raised when a log event does not exist for the owning user."""


class IllegalTransition(Exception):
    """Raised when a status change is not permitted by :data:`LEGAL_TRANSITIONS`."""


def is_legal_transition(current: LogEventStatus, target: LogEventStatus) -> bool:
    """Return whether ``current → target`` is a permitted status transition."""

    return target in LEGAL_TRANSITIONS.get(current, frozenset())


def create_event(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    raw_text: str,
    idempotency_key: str | None = None,
) -> tuple[LogEvent, bool]:
    """Create — or idempotently replay — a ``pending`` log event for ``owner_id``.

    ``raw_text`` is the already-validated, trimmed user input (see the create
    DTO). The event starts at :attr:`~app.enums.LogEventStatus.PENDING`; the
    estimator (Milestone 4) advances it later.

    Returns ``(event, created)``. ``created`` is :data:`True` for a fresh insert
    and :data:`False` for an idempotent replay, so the router enqueues the
    estimation job **only** on a fresh create and signals ``201`` vs ``200``.

    Idempotency (FTY-096) is **first-write-wins**, keyed per user:

    - **No ``idempotency_key``** → always a fresh ``pending`` event (the original
      behaviour; back-compatible).
    - **Key supplied, no event yet for ``(owner_id, key)``** → create it, store
      the key, return ``(event, True)``.
    - **Key supplied, an event already exists** → return that existing event at
      its current status, create no row, return ``(event, False)``. A divergent
      ``raw_text`` on the replay is ignored — the stored event is authoritative.

    The create path is race-safe: two concurrent same-key submits collide on the
    ``(user_id, idempotency_key)`` unique index; the loser catches the integrity
    violation, re-reads the now-committed sibling, and returns it as a replay —
    never a ``500``, never a duplicate.
    """

    _authorize(owner_id, current_user)

    if idempotency_key is not None:
        existing = _find_by_key(session, owner_id, idempotency_key)
        if existing is not None:
            return existing, False

    event = LogEvent(
        user_id=owner_id,
        raw_text=raw_text,
        status=LogEventStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    session.add(event)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent same-key submit committed first and won the unique index.
        # Re-read its event and return it as the idempotent replay. A no-key
        # create cannot hit this index, so re-raise anything unexpected.
        session.rollback()
        if idempotency_key is None:
            raise
        existing = _find_by_key(session, owner_id, idempotency_key)
        if existing is None:
            raise
        return existing, False

    session.refresh(event)
    return event, True


def list_events_for_day(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    day: date | None = None,
) -> list[LogEvent]:
    """Return ``owner_id``'s events whose ``created_at`` falls on ``day``.

    The calendar day is resolved in the user's profile timezone (falling back to
    UTC), so "Today" matches what the user sees locally rather than a server
    clock. When ``day`` is omitted it defaults to the current day in that zone.
    Results are ordered oldest-first for a stable timeline.
    """

    _authorize(owner_id, current_user)
    if day is None:
        day = current_day(session, owner_id)
    tz = user_timezone(session, owner_id)
    start_utc, end_utc = day_bounds_utc(day, tz)

    return list(
        session.scalars(
            select(LogEvent)
            .where(
                LogEvent.user_id == owner_id,
                LogEvent.created_at >= start_utc,
                LogEvent.created_at < end_utc,
            )
            .order_by(LogEvent.created_at.asc(), LogEvent.id.asc())
        )
    )


def get_event(
    session: Session, owner_id: uuid.UUID, current_user: User, event_id: uuid.UUID
) -> LogEvent:
    """Return a single event by id, enforcing that the caller owns it.

    The query is scoped to ``owner_id`` so a cross-user id is indistinguishable
    from a missing one (no existence oracle); both raise
    :class:`LogEventNotFound`, which the router renders as ``404``.
    """

    _authorize(owner_id, current_user)
    event = session.scalars(
        select(LogEvent).where(LogEvent.id == event_id, LogEvent.user_id == owner_id)
    ).one_or_none()
    if event is None:
        raise LogEventNotFound("log event not found")
    return event


def list_clarification_questions(
    session: Session, owner_id: uuid.UUID, current_user: User, event_id: uuid.UUID
) -> list[ClarificationQuestion]:
    """Return an owned event's open (unanswered) clarification questions, ordered.

    Ownership is enforced by delegating to :func:`get_event`: a cross-user or
    nonexistent ``event_id`` raises :class:`LogEventNotFound` (rendered ``404``),
    so the read is fail-closed with no existence oracle. The estimator persisted
    these rows (FTY-042); this is purely a read path.

    The read is **status-gated, not row-driven** (``log-events.md`` v4):
    questions are served only while the event is in ``needs_clarification`` — the
    only status in which a fresh answer can be accepted — so the client never
    renders a chip whose answer would ``409``. An event in any other status, or
    one with no unanswered rows, returns an empty list; the cases are
    indistinguishable (**no status oracle**). An answered question is resolved
    and not re-served: a fresh clarification round replaces the unanswered rows
    (FTY-171), so this serves exactly the questions still open.

    ``question_text`` is sensitive (tied to the user's log, like ``raw_text``): it
    is returned only to the owner and never written to logs.
    """

    event = get_event(session, owner_id, current_user, event_id)
    if LogEventStatus(event.status) is not LogEventStatus.NEEDS_CLARIFICATION:
        return []
    answered_ids = select(ClarificationAnswer.question_id)
    return list(
        session.scalars(
            select(ClarificationQuestion)
            .where(
                ClarificationQuestion.log_event_id == event_id,
                ClarificationQuestion.id.not_in(answered_ids),
            )
            .order_by(ClarificationQuestion.position.asc(), ClarificationQuestion.id.asc())
        )
    )


def transition_event(session: Session, event: LogEvent, target: LogEventStatus) -> LogEvent:
    """Move ``event`` to ``target`` if the state machine permits it.

    The single mutation path for status. Raises :class:`IllegalTransition` for a
    transition not in :data:`LEGAL_TRANSITIONS` so callers cannot bypass the
    contract. FTY-030 exercises ``pending → completed``; the estimator stories
    reuse this function for their transitions.
    """

    current = LogEventStatus(event.status)
    if not is_legal_transition(current, target):
        raise IllegalTransition(f"illegal transition {current.value} -> {target.value}")
    event.status = target
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s log events."""

    if owner_id != current_user.id:
        raise LogEventForbidden("cross-user log-event access denied")


def _find_by_key(session: Session, owner_id: uuid.UUID, idempotency_key: str) -> LogEvent | None:
    """Return ``owner_id``'s event for ``idempotency_key``, or ``None``.

    The lookup is scoped to ``owner_id`` so the key namespace is per-user: one
    user's key can never address another user's event (FTY-096 security).
    """

    return session.scalars(
        select(LogEvent).where(
            LogEvent.user_id == owner_id,
            LogEvent.idempotency_key == idempotency_key,
        )
    ).one_or_none()
