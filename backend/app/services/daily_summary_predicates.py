"""Finalized-event / uncounted-entry predicate builders (FTY-355, FTY-357).

The reusable WHERE-clause / correlated-EXISTS helpers that decide **which rows
count** toward a day's read-model. The service module
(:mod:`app.services.daily_summary`) owns the read-model assembly — the public
surface, the DTO builders, the aggregators, and target resolution — and imports
these predicate builders, calling them exactly as before.

This module is also the **single canonical home** (FTY-357) for the
finalized-event definition shared with the log-events item read: the finalized
event **status set** (:data:`_FINALIZED_EVENT_STATUSES`) and the
**committed-resolved-item discriminator** (an event's resolved items count while
it is momentarily ``processing`` for an answer-triggered scoped re-estimate iff
it owns an open item-scoped question on a still-``unresolved`` component). That
rule has two renderings that genuinely cannot be one callable — a SQL
correlated-EXISTS (:func:`_scoped_reestimate_processing`, used by the
daily-summary aggregate reads) and an in-memory id-set query
(:func:`_scoped_reestimate_processing_ids`, used by
:func:`app.services.log_events.list_entries_for_day`) — so both live **here**,
derived from the one shared status set, rather than each module hand-rolling its
own copy. ``log_events.py`` imports the status set and the id-set rendering from
this module; a parity test pins that the two renderings select the same events.

The two contracts the service documents are enforced here:

- **Finalized-state filtering.** The exact filter predicate, kept explicit so the
  rule is auditable: ``log_events.voided_at IS NULL AND <finalized-event
  predicate> AND derived_items.status == 'resolved' AND current_value IS NOT
  NULL``. The finalized-event predicate keys on **committed resolved items**, not
  solely on the parent event's transient status (:func:`_finalized_event_condition`):
  a ``resolved`` item counts when its event is ``completed`` or
  ``partially_resolved`` **or** is momentarily ``processing`` as an
  answer-triggered scoped re-estimate of a previously-partial event (FTY-349).
  That scoped-``processing`` clause requires **both** a committed ``resolved``
  sibling **and** an open item-scoped clarification question on a still-``unresolved``
  component, so it cannot match a **first-pass** ``processing`` event during the
  worker's two-commit completion window: a first-pass event owns no such question,
  so nothing counts early. A **voided** event (FTY-321) is excluded outright even
  though its rows are retained; the same ``voided_at IS NULL`` clause gates the
  ``uncounted_entries`` predicates too.
- **Uncounted-entries filtering.** The disjoint ``needs_clarification`` /
  open-item-scoped-question / ``proposed`` predicates that select the
  logged-but-not-yet-counted entries.

These helpers read no raw diary/page text and persist nothing (the SQL builders
emit SQL only; :func:`_scoped_reestimate_processing_ids` runs a single read-only
id query).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.enums import DerivedItemStatus, LogEventStatus
from app.models.derived import (
    ClarificationQuestion,
    DerivedExerciseItem,
    DerivedFoodItem,
)
from app.models.log_events import LogEvent

_FINALIZED_EVENT_STATUSES = (LogEventStatus.COMPLETED, LogEventStatus.PARTIALLY_RESOLVED)


# ── Finalized-state predicate (single source of truth) ─────────────────────────
#
# Both the single-day and range read paths build their queries from these helpers
# so the documented finalized filter is defined exactly once. The predicate:
# ``_finalized_event_condition()`` AND ``derived_*_items.status == 'resolved'`` AND
# the costed-value column ``IS NOT NULL``, windowed by the owning log event's
# ``created_at`` over ``[start, end)``. Day attribution is the event's
# ``created_at``.


def _has_committed_resolved_item() -> ColumnElement[bool]:
    """True when the ``LogEvent`` row already carries ≥1 committed resolved item.

    The first half of the FTY-349 scoped-re-estimate discriminator (paired with
    :func:`_has_open_item_scoped_question`). By the FTY-043/044/278 commit rule a
    ``resolved`` item is only ever committed on a ``completed`` /
    ``partially_resolved`` terminal transition, so this is a **committed** fact, not
    a status. A correlated ``EXISTS`` over the event's own food **or** exercise items
    (aliased so it never collides with the outer join); a committed resolved item is
    a ``resolved`` row with a non-null headline value — the per-item finalized gate.
    """

    food = aliased(DerivedFoodItem)
    exercise = aliased(DerivedExerciseItem)
    food_exists = (
        select(1)
        .where(
            food.log_event_id == LogEvent.id,
            food.status == DerivedItemStatus.RESOLVED,
            food.calories.isnot(None),
        )
        .correlate(LogEvent)
        .exists()
    )
    exercise_exists = (
        select(1)
        .where(
            exercise.log_event_id == LogEvent.id,
            exercise.status == DerivedItemStatus.RESOLVED,
            exercise.active_calories.isnot(None),
        )
        .correlate(LogEvent)
        .exists()
    )
    return or_(food_exists, exercise_exists)


def _has_open_item_scoped_question() -> ColumnElement[bool]:
    """True when the event owns an item-scoped question on a still-``unresolved`` component.

    The second half of the FTY-349 scoped-re-estimate discriminator — the clause a
    **first-pass** ``processing`` event can never satisfy. During the worker's
    two-commit completion window a first-pass event momentarily carries committed
    ``resolved`` rows, but it owns **no** open item-scoped question (it resolved
    cleanly, or its leftovers are plain uncosted rows), so it fails here and never
    counts early. Only a previously-``partially_resolved`` event being re-costed owns
    such a question on a still-unresolved component (FTY-278 shape #3); the row may be
    answered-or-open, so the clause holds until the component resolves.
    """

    question = aliased(ClarificationQuestion)
    component = aliased(DerivedFoodItem)
    return (
        select(1)
        .where(
            question.log_event_id == LogEvent.id,
            question.derived_food_item_id == component.id,
            component.status == DerivedItemStatus.UNRESOLVED,
        )
        .correlate(LogEvent)
        .exists()
    )


def _scoped_reestimate_processing() -> ColumnElement[bool]:
    """A ``processing`` event that is a genuine answer-triggered scoped re-estimate.

    ``processing`` **and both** discriminator clauses: ≥1 already-committed resolved
    sibling (:func:`_has_committed_resolved_item`) **and** ≥1 open item-scoped
    question on a still-unresolved component (:func:`_has_open_item_scoped_question`).
    Requiring the second clause keeps the gate from matching a **first-pass**
    ``processing`` event during the worker's two-commit completion window: it can
    carry committed resolved rows but never an open item-scoped question (FTY-349).
    """

    return and_(
        LogEvent.status == LogEventStatus.PROCESSING,
        _has_committed_resolved_item(),
        _has_open_item_scoped_question(),
    )


def _scoped_reestimate_processing_ids(
    session: Session, owner_id: uuid.UUID, candidate_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """In-memory rendering of the scoped-``processing`` discriminator (FTY-349/357).

    The Python-side twin of the SQL :func:`_scoped_reestimate_processing`, sharing
    this module's one discriminator rule so the log-events item read
    (:func:`app.services.log_events.list_entries_for_day`) never hand-rolls its own
    copy. Given ``candidate_ids`` already narrowed to ``processing`` events, returns
    those that own ≥1 item-scoped clarification question on a still-``unresolved``
    component — the :func:`_has_open_item_scoped_question` clause the SQL rendering
    encodes as a correlated ``EXISTS`` — which is the signature of a
    previously-``partially_resolved`` event being re-costed. A **first-pass**
    ``processing`` event that momentarily carries committed resolved rows during the
    worker's two-commit completion window owns no such question, so it is excluded
    and surfaces nothing (the per-item ``RESOLVED`` + costed-value filter the caller
    applies is *not* a sufficient discriminator on its own, precisely because that
    window exposes committed resolved rows before the terminal transition commits).
    """

    if not candidate_ids:
        return set()
    component = aliased(DerivedFoodItem)
    rows = session.scalars(
        select(ClarificationQuestion.log_event_id)
        .join(component, ClarificationQuestion.derived_food_item_id == component.id)
        .where(
            ClarificationQuestion.user_id == owner_id,
            ClarificationQuestion.log_event_id.in_(candidate_ids),
            component.status == DerivedItemStatus.UNRESOLVED,
        )
    )
    return set(rows)


def _finalized_event_condition() -> ColumnElement[bool]:
    """Event-level gate: whose committed resolved items count toward the day total.

    An event's ``resolved`` items count when the event is terminal-finalized
    (``completed`` / ``partially_resolved``) **or** is momentarily ``processing`` as
    an answer-triggered scoped re-estimate of a previously-partial event (FTY-349) —
    so a partial event's already-counted siblings stay counted for the whole
    re-estimate window and the total never dips and reappears. Keys on committed
    resolved items, not on the transient event status alone.
    """

    return or_(
        LogEvent.status.in_(_FINALIZED_EVENT_STATUSES),
        _scoped_reestimate_processing(),
    )


def _food_window_conditions(
    owner_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[ColumnElement[bool], ...]:
    """WHERE conditions selecting one user's finalized food items in a window."""

    return (
        DerivedFoodItem.user_id == owner_id,
        LogEvent.user_id == owner_id,
        LogEvent.voided_at.is_(None),
        _finalized_event_condition(),
        DerivedFoodItem.status == DerivedItemStatus.RESOLVED,
        DerivedFoodItem.calories.isnot(None),
        LogEvent.created_at >= start_utc,
        LogEvent.created_at < end_utc,
    )


def _exercise_window_conditions(
    owner_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[ColumnElement[bool], ...]:
    """WHERE conditions selecting one user's finalized exercise items in a window."""

    return (
        DerivedExerciseItem.user_id == owner_id,
        LogEvent.user_id == owner_id,
        LogEvent.voided_at.is_(None),
        _finalized_event_condition(),
        DerivedExerciseItem.status == DerivedItemStatus.RESOLVED,
        DerivedExerciseItem.active_calories.isnot(None),
        LogEvent.created_at >= start_utc,
        LogEvent.created_at < end_utc,
    )


# ── Uncounted-entries predicate (logged-but-not-yet-counted) ───────────────────
#
# An entry is *uncounted* when it exists but has not yet been counted toward
# ``intake`` because it awaits a user action. Three disjoint kinds, summed:
#   1. ``needs_clarification`` LOG EVENTS — event-level clarification, no committed
#      items, one per event; attributed by the event's own ``created_at``.
#   2. open ITEM-SCOPED QUESTIONS on ``partially_resolved`` / scoped-``processing``
#      events — one per still-unresolved component that owns a question (resolved
#      siblings count in intake instead), keyed on the component's resolution, not
#      the answer row, so it survives the whole re-estimate window (FTY-349).
#   3. ``proposed`` DERIVED FOOD ITEMS (FTY-196) — a costed-but-unconfirmed label
#      parse, excluded from every finalized read; attributed by the owning
#      ``created_at``.
# Excluded: ``pending`` / **first-pass** ``processing`` events (still estimating),
# ``failed`` events, and finalized entries (already in ``intake``).


def _needs_clarification_window_conditions(
    owner_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[ColumnElement[bool], ...]:
    """WHERE conditions selecting one user's ``needs_clarification`` events in a window."""

    return (
        LogEvent.user_id == owner_id,
        LogEvent.voided_at.is_(None),
        LogEvent.status == LogEventStatus.NEEDS_CLARIFICATION,
        LogEvent.created_at >= start_utc,
        LogEvent.created_at < end_utc,
    )


def _partial_question_window_conditions(
    owner_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[ColumnElement[bool], ...]:
    """WHERE conditions selecting item-scoped questions on still-unresolved components.

    "Open" is keyed on the **component's** resolution, never on the answer row: the
    real answer flow persists the ``ClarificationAnswer`` in the same transaction
    that flips the event ``partially_resolved → processing``, so an
    answered-but-not-yet-resolved question keeps its uncounted entry for the whole
    re-estimate window and drops only when its own component resolves (FTY-349). The
    event-status gate mirrors the finalized filter's scoped-re-estimate clause, so a
    *sibling* question's open entry survives the window too. A single unresolved
    component can own more than one matching question row across re-estimate rounds
    (a fresh open question plus the retained prior answered row), so the callers
    ``COUNT(DISTINCT derived_food_item_id)`` — the component stays exactly one
    uncounted entry across the window and drops only when it resolves.
    """

    component = aliased(DerivedFoodItem)
    component_still_unresolved = (
        select(1)
        .where(
            component.id == ClarificationQuestion.derived_food_item_id,
            component.status == DerivedItemStatus.UNRESOLVED,
        )
        .correlate(ClarificationQuestion)
        .exists()
    )
    return (
        ClarificationQuestion.user_id == owner_id,
        LogEvent.user_id == owner_id,
        LogEvent.voided_at.is_(None),
        or_(
            LogEvent.status == LogEventStatus.PARTIALLY_RESOLVED,
            _scoped_reestimate_processing(),
        ),
        ClarificationQuestion.derived_food_item_id.isnot(None),
        component_still_unresolved,
        LogEvent.created_at >= start_utc,
        LogEvent.created_at < end_utc,
    )


def _proposed_food_window_conditions(
    owner_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[ColumnElement[bool], ...]:
    """WHERE conditions selecting one user's ``proposed`` food items in a window.

    Attribution is the owning ``LogEvent.created_at`` (joined by the caller),
    matching how ``intake`` attributes a day. No event-status filter: a
    ``proposed`` item lands only on a ``completed`` event by construction (FTY-196),
    so the item status alone is the precise predicate.
    """

    return (
        DerivedFoodItem.user_id == owner_id,
        LogEvent.user_id == owner_id,
        LogEvent.voided_at.is_(None),
        DerivedFoodItem.status == DerivedItemStatus.PROPOSED,
        LogEvent.created_at >= start_utc,
        LogEvent.created_at < end_utc,
    )
