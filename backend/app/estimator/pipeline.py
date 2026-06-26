"""The pluggable estimation pipeline contract (FTY-040).

This module defines the **step interface** the estimator step stories
(FTY-042 parse, FTY-043 exercise math, FTY-044 food resolution) implement, and
the runner that drives an ordered list of steps to a single terminal outcome.
FTY-040 ships only *stub* steps so the worker, idempotency, retry, and state
machine can be exercised end-to-end before any real parsing or calculation
exists.

Design
------

A step receives a mutable :class:`EstimationContext` and records what it did onto
it (tool names, source references, assumptions, validation errors, a sanitized
trace). A step signals a non-success outcome by raising:

- :class:`NeedsClarification` — terminal, **not** retryable: the input is
  ambiguous and only the user can resolve it.
- :class:`StepFailed` — terminal, **not** retryable: the input is deterministically
  unprocessable (empty/garbage/unparseable, or model output that failed schema
  validation), so retrying the same input cannot help. The worker fails the event
  immediately instead of burning retries.
- :class:`StepError` — a *retryable* failure (transient provider/tool error); the
  worker retries up to the bounded limit before giving up.

Anything written to the context must be **sanitized**: no raw prompts, no
secrets, no raw user text. The context carries ids and structured facts only,
matching ``docs/security/data-retention.md``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.llm.base import Provider


class NeedsClarification(Exception):
    """Raised by a step when the input is ambiguous and needs the user.

    Terminal and non-retryable: retrying the same ambiguous input cannot succeed,
    so the worker drives the event to ``needs_clarification`` rather than burning
    retries. ``reason`` is a short, sanitized label (never raw user text).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StepFailed(Exception):
    """Raised by a step on a deterministic, terminal failure (non-retryable).

    Unlike :class:`StepError`, retrying the same input cannot succeed: the input is
    empty/garbage/unparseable, or the model's output failed schema validation and
    is rejected (fail closed). The worker drives the event straight to ``failed``
    without consuming retries. ``reason`` is a short, sanitized label — never raw
    prompts, secrets, or raw user text — because it is persisted on the run.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StepError(Exception):
    """Raised by a step on a retryable failure (e.g. a transient tool error).

    ``message`` must be sanitized — a short description or error class, never raw
    prompts, secrets, or raw user text — because it is persisted on the run.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PipelineOutcome(StrEnum):
    """The single terminal outcome of running the pipeline over one event."""

    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


@dataclass(frozen=True)
class CandidateDraft:
    """A parsed, unresolved food/exercise candidate accumulated by the parse step.

    A neutral value object the parse step (FTY-042) fills and the worker persists
    into ``derived_food_items`` / ``derived_exercise_items``. It carries the
    structured parse only — name and raw portion phrase plus an optional
    best-effort unit/amount — and never any energy value (resolution is
    FTY-043/044). It is *not* sanitized run metadata: it is product data persisted
    to its own user-owned table, never copied into the run ``trace``.
    """

    name: str
    quantity_text: str = ""
    unit: str | None = None
    amount: float | None = None


@dataclass
class EstimationContext:
    """Mutable accumulator threaded through the pipeline steps.

    ``raw_text`` is the untrusted user input the steps parse; it is **never**
    copied into ``trace`` or any persisted *run* field. ``food_candidates`` /
    ``exercise_candidates`` / ``clarification_questions`` are the structured parse
    products the worker persists into their own user-owned tables on a successful
    or needs-clarification outcome. The remaining fields are the sanitized,
    structured record the worker writes onto the :class:`EstimationRun`.
    """

    log_event_id: uuid.UUID
    user_id: uuid.UUID
    raw_text: str
    provider: str | None = None
    model: str | None = None
    schema_version: str | None = None
    tool_names: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    food_candidates: list[CandidateDraft] = field(default_factory=list)
    exercise_candidates: list[CandidateDraft] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)

    def record_step(self, name: str, status: str) -> None:
        """Append a sanitized trace entry for a completed step.

        Only the step name and a status label are recorded — never inputs,
        outputs, prompts, or user text.
        """

        self.trace.append({"step": name, "status": status})


@runtime_checkable
class EstimationStep(Protocol):
    """A single estimation pipeline step.

    Implementations (FTY-042/043/044) carry a stable ``name`` and mutate the
    context in :meth:`run`, raising :class:`NeedsClarification` or
    :class:`StepError` to signal a non-success outcome.
    """

    @property
    def name(self) -> str:
        """A stable identifier for the step, recorded in the run trace."""
        ...

    def run(self, context: EstimationContext) -> None:
        """Execute the step against ``context``; mutate it in place."""
        ...


@dataclass(frozen=True)
class StubParseStep:
    """Placeholder for the NL parse step (FTY-042). A no-op that records itself."""

    name: str = "stub_parse"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.record_step(self.name, "ok")


@dataclass(frozen=True)
class StubCalculateStep:
    """Placeholder for the calculation step (FTY-043/044). Records itself only."""

    name: str = "stub_calculate"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.record_step(self.name, "ok")


@dataclass(frozen=True)
class PipelineResult:
    """The outcome of a pipeline run plus an optional sanitized error message.

    ``retryable`` is only meaningful for a ``FAILED`` outcome: ``True`` for a
    transient :class:`StepError` (the worker may retry within its bound) and
    ``False`` for a deterministic :class:`StepFailed` (the worker fails closed
    immediately). ``COMPLETED`` / ``NEEDS_CLARIFICATION`` are terminal regardless.
    """

    outcome: PipelineOutcome
    error: str | None = None
    retryable: bool = True


class Pipeline:
    """An ordered list of estimation steps run to a single terminal outcome.

    The steps run in order. The first :class:`NeedsClarification` ends the run as
    ``needs_clarification``; the first :class:`StepFailed` ends it as ``failed``
    (terminal, non-retryable); the first :class:`StepError` ends it as ``failed``
    (retryable). If every step completes, the outcome is ``completed``. The
    runner never inspects or copies ``context.raw_text`` into the result.
    """

    def __init__(self, steps: list[EstimationStep]) -> None:
        self._steps = steps

    @property
    def steps(self) -> list[EstimationStep]:
        return list(self._steps)

    def run(self, context: EstimationContext) -> PipelineResult:
        for step in self._steps:
            try:
                step.run(context)
            except NeedsClarification as exc:
                context.record_step(step.name, "needs_clarification")
                return PipelineResult(PipelineOutcome.NEEDS_CLARIFICATION, exc.reason)
            except StepFailed as exc:
                context.record_step(step.name, "failed")
                return PipelineResult(PipelineOutcome.FAILED, exc.reason, retryable=False)
            except StepError as exc:
                context.record_step(step.name, "failed")
                return PipelineResult(PipelineOutcome.FAILED, exc.message, retryable=True)
        return PipelineResult(PipelineOutcome.COMPLETED, None)


def default_pipeline(provider: Provider) -> Pipeline:
    """Build the v1 estimation pipeline: real NL parse then stub calculate.

    The parse step (FTY-042) turns the event text into schema-validated candidates
    using ``provider``; the calculation step is still a stub until FTY-043/044
    replace it. The worker contract (claim → run → transition) is unchanged.
    """

    # Imported here rather than at module top to avoid a cycle: the parse step
    # imports the context/exception types defined above in this module.
    from app.estimator.parse import ParseStep

    return Pipeline([ParseStep(provider), StubCalculateStep()])
