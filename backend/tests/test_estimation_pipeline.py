"""Unit tests for the pluggable estimation pipeline contract (FTY-040).

These pin the step interface and the runner's outcome mapping without a database:
the stub steps complete, a clarifying step is terminal, a failing step is
retryable, and the runner never copies raw user text into the trace.
"""

from __future__ import annotations

import uuid

import pytest

from app.estimator.pipeline import (
    EstimationContext,
    NeedsClarification,
    Pipeline,
    PipelineOutcome,
    StepError,
    StubCalculateStep,
    StubParseStep,
    default_pipeline,
)
from app.estimator.processing import (
    RETRY_BACKOFF_MAX_SECONDS,
    retry_countdown,
)


def _context(raw_text: str = "two eggs") -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=raw_text)


class _ClarifyStep:
    name = "clarify"

    def run(self, context: EstimationContext) -> None:
        raise NeedsClarification("ambiguous_quantity")


class _FailStep:
    name = "boom"

    def run(self, context: EstimationContext) -> None:
        raise StepError("transient_tool_error")


class _LeakStep:
    """A buggy step that raises with the raw text in its message."""

    name = "leak"

    def __init__(self, raw_text: str) -> None:
        self._raw = raw_text

    def run(self, context: EstimationContext) -> None:
        raise RuntimeError(f"crashed handling {self._raw}")


def test_default_pipeline_completes_and_records_stub_steps() -> None:
    context = _context()

    result = default_pipeline().run(context)

    assert result.outcome is PipelineOutcome.COMPLETED
    assert result.error is None
    assert context.tool_names == [StubParseStep().name, StubCalculateStep().name]
    assert [entry["step"] for entry in context.trace] == [
        StubParseStep().name,
        StubCalculateStep().name,
    ]


def test_needs_clarification_is_terminal_outcome() -> None:
    context = _context()

    result = Pipeline([StubParseStep(), _ClarifyStep()]).run(context)

    assert result.outcome is PipelineOutcome.NEEDS_CLARIFICATION
    assert result.error == "ambiguous_quantity"
    # The clarifying step is recorded but the later steps never run.
    assert context.trace[-1] == {"step": "clarify", "status": "needs_clarification"}


def test_step_error_is_failed_outcome() -> None:
    context = _context()

    result = Pipeline([_FailStep(), StubCalculateStep()]).run(context)

    assert result.outcome is PipelineOutcome.FAILED
    assert result.error == "transient_tool_error"
    # The calculate step after the failure does not run.
    assert "stub_calculate" not in context.tool_names


def test_pipeline_never_copies_raw_text_into_trace() -> None:
    private_text = "150g rice and dal at 7pm with my partner"
    context = _context(raw_text=private_text)

    default_pipeline().run(context)

    serialized = str(context.trace)
    assert private_text not in serialized


@pytest.mark.parametrize(
    ("retries", "expected"),
    [(0, 10), (1, 20), (2, 40), (6, 600)],
)
def test_retry_countdown_is_exponential_and_capped(retries: int, expected: int) -> None:
    assert retry_countdown(retries) == expected
    assert retry_countdown(retries) <= RETRY_BACKOFF_MAX_SECONDS
