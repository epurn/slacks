"""Unit tests for the log-event status state machine (FTY-030).

The transition map is a named contract other stories extend; these tests pin the
legal/illegal transitions and prove that the only mutation path rejects an
illegal transition (an acceptance criterion) without a database.
"""

from __future__ import annotations

import pytest

from app.enums import LogEventStatus
from app.services.log_events import (
    LEGAL_TRANSITIONS,
    IllegalTransition,
    is_legal_transition,
    transition_event,
)


def test_transition_map_covers_every_status() -> None:
    # Every status in the enum has an explicit (possibly empty) transition set,
    # so no status is silently undefined.
    assert set(LEGAL_TRANSITIONS) == set(LogEventStatus)


def test_terminal_statuses_have_no_outgoing_transitions() -> None:
    assert LEGAL_TRANSITIONS[LogEventStatus.COMPLETED] == frozenset()
    assert LEGAL_TRANSITIONS[LogEventStatus.FAILED] == frozenset()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (LogEventStatus.PENDING, LogEventStatus.COMPLETED),
        (LogEventStatus.PENDING, LogEventStatus.PROCESSING),
        (LogEventStatus.PROCESSING, LogEventStatus.COMPLETED),
        (LogEventStatus.PROCESSING, LogEventStatus.FAILED),
        (LogEventStatus.PROCESSING, LogEventStatus.NEEDS_CLARIFICATION),
        (LogEventStatus.NEEDS_CLARIFICATION, LogEventStatus.PROCESSING),
    ],
)
def test_legal_transitions(current: LogEventStatus, target: LogEventStatus) -> None:
    assert is_legal_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (LogEventStatus.PENDING, LogEventStatus.FAILED),
        (LogEventStatus.PENDING, LogEventStatus.NEEDS_CLARIFICATION),
        (LogEventStatus.COMPLETED, LogEventStatus.PENDING),
        (LogEventStatus.COMPLETED, LogEventStatus.PROCESSING),
        (LogEventStatus.FAILED, LogEventStatus.PROCESSING),
        (LogEventStatus.PENDING, LogEventStatus.PENDING),
    ],
)
def test_illegal_transitions(current: LogEventStatus, target: LogEventStatus) -> None:
    assert not is_legal_transition(current, target)


class _FakeEvent:
    """Minimal stand-in for the ORM row to exercise transition logic offline."""

    def __init__(self, status: LogEventStatus) -> None:
        self.status = status


class _FakeSession:
    def add(self, _obj: object) -> None: ...
    def commit(self) -> None: ...
    def refresh(self, _obj: object) -> None: ...


def test_transition_event_rejects_illegal_transition() -> None:
    event = _FakeEvent(LogEventStatus.COMPLETED)
    with pytest.raises(IllegalTransition):
        transition_event(_FakeSession(), event, LogEventStatus.PENDING)  # type: ignore[arg-type]
    # The event is left untouched when the transition is rejected.
    assert event.status == LogEventStatus.COMPLETED
