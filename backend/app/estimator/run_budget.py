"""Per-run provider-call / wall-clock ceiling for one estimation attempt (FTY-363).

A single estimation run must not make an unbounded number of sequential provider
calls or run unbounded wall-clock time. The official/reference/model-prior cascade
for a multi-item branded phrase (plus the parse self-consistency sampler and any
re-interpretation) is a chain of sequential provider round-trips with no *total*
bound of its own — only per-call timeouts (``app.llm.base``) and the attempt-level
retry bound (``processing.DEFAULT_MAX_ATTEMPTS``), neither of which caps the number
of calls *within one attempt*. Without a run-scoped ceiling a pathological input can
keep the log event ``processing`` for minutes, past the live food smoke's
``POLL_TIMEOUT_SECONDS = 90.0`` poll window.

:class:`BudgetedProvider` wraps the run's provider and enforces the ceiling at the
one chokepoint every step shares — :meth:`Provider.structured_completion`. Every
call is counted and time-checked *before* it is forwarded; exceeding either bound
raises :class:`RunBudgetExceeded`, a :class:`~app.estimator.pipeline.StepFailed`
subclass. Because it is a ``StepFailed``, the pipeline ends the run terminally and
**non-retryably** (``processing → failed``, immediate — no attempt is burned on a
re-run that would hit the same bound), and the recorded reason is a fixed,
content-free label (never a prompt, provider output, user text, or credential). The
ceiling is a runaway-cost / denial-of-service guard, so failing closed on breach is
the security-preferred behaviour.

The bound is *distinct* from the attempt-level retry bounds in ``processing.py``:
those cap how many times a transiently-failing attempt is re-run; this caps the
total sequential provider work *within one attempt*. Both stay in force.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from app.estimator.pipeline import StepFailed
from app.llm.base import ImageInput, OutputT, Provider

#: Maximum total provider (LLM) calls one estimation run may make across all steps.
#: Chosen to comfortably clear the honest worst case — a real multi-item branded
#: phrase (the ``branded-crackers-and-hummus`` smoke fixture: two branded items)
#: whose components resolve through the official → reference → model-prior cascade.
#: That path's parse self-consistency sampling (~4 calls), plus each item's bounded
#: identity-variant × search-result × page/snippet extract walk before it accepts,
#: stays well under this bound when it resolves early and short-circuits; a run that
#: exhausts every variant/result/tier for multiple items without resolving is a
#: runaway we *want* to fail closed rather than let thrash the 90s poll window.
#: A conservative documented default; tunable like ``DEFAULT_MAX_ATTEMPTS``.
DEFAULT_MAX_PROVIDER_CALLS = 128

#: Maximum wall-clock time (seconds) one estimation run may spend before it fails
#: closed. Below the food smoke's ``POLL_TIMEOUT_SECONDS = 90.0`` so a runaway run
#: terminates *inside* the poll window instead of leaving the event ``processing``
#: past it. The honest worst-case fixture resolves in far less than this live. The
#: deadline is checked at each provider-call boundary (a run makes no unbounded work
#: between calls), so a single in-flight call can overshoot by its own per-call
#: timeout — that residual is the pre-existing FTY-113 per-call bound, out of scope
#: here; the ~15s margin below 90s absorbs a typical in-flight call plus the commit.
DEFAULT_RUN_DEADLINE_SECONDS = 75.0

#: Content-free, sanitized terminal-failure reasons persisted on the run's ``error``.
#: Fixed labels — never raw prompts, provider output, user text, or credentials.
PROVIDER_CALL_BUDGET_EXCEEDED = "run_provider_call_budget_exceeded"
WALL_CLOCK_DEADLINE_EXCEEDED = "run_wall_clock_deadline_exceeded"

#: The full set of run-budget breach reasons. A :class:`RunBudgetExceeded` flattens to
#: a ``StepFailed`` :class:`PipelineResult` carrying one of these as its ``error``; the
#: reason string is the only signal that survives to a finalizer, so paths that must
#: fail the *whole run* closed on a ceiling breach (the scoped re-estimate finalizer,
#: FTY-363) match ``result.error`` against this set via :func:`is_run_budget_breach`.
RUN_BUDGET_REASONS = frozenset({PROVIDER_CALL_BUDGET_EXCEEDED, WALL_CLOCK_DEADLINE_EXCEEDED})


def is_run_budget_breach(reason: str | None) -> bool:
    """True iff ``reason`` is a per-run ceiling breach label (FTY-363).

    A run-budget breach is a *run-level*, non-retryable failure — distinct from a
    per-component scoped step failure — so a finalizer uses this to route it to a
    terminal ``processing → failed`` transition instead of reopening a question.
    """

    return reason in RUN_BUDGET_REASONS


class RunBudgetExceeded(StepFailed):
    """Terminal, non-retryable: one run hit its per-run provider-call/wall-clock ceiling.

    A :class:`~app.estimator.pipeline.StepFailed` subclass, so the pipeline maps it
    ``processing → failed`` immediately without consuming a retry (re-running the same
    input would hit the same bound). ``reason`` is one of the fixed content-free labels
    above; no step catches ``StepFailed``, so it always reaches the pipeline runner.
    """


class BudgetedProvider(Provider):
    """Wrap a provider so one estimation run cannot exceed a call/time ceiling.

    Delegates :meth:`structured_completion` to ``wrapped`` after counting the call and
    checking the wall-clock deadline; the wrapped provider still owns its own timeouts,
    transient-retry, and schema validation. The recorded provider identity
    (``name``/``model``, FTY-255) mirrors ``wrapped`` so a budgeted run's audit fields
    are byte-identical to an un-budgeted one.

    The counter and start time are per-instance, so the worker builds a fresh
    ``BudgetedProvider`` per attempt. The FTY-158 parse sampler makes concurrent calls,
    so the counter/deadline check is guarded by a lock.
    """

    def __init__(
        self,
        wrapped: Provider,
        *,
        max_provider_calls: int = DEFAULT_MAX_PROVIDER_CALLS,
        deadline_seconds: float = DEFAULT_RUN_DEADLINE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._wrapped = wrapped
        self.name = wrapped.name
        self.model = wrapped.model
        self._max_provider_calls = max_provider_calls
        self._deadline_seconds = deadline_seconds
        # Injectable monotonic clock seam (mirrors the injectable-sleep pattern): tests
        # pass a fake that advances past the deadline without any real wall-clock wait.
        self._clock = clock
        self._started_at = clock()
        self._calls_made = 0
        self._lock = threading.Lock()

    @property
    def calls_made(self) -> int:
        """How many provider calls this run has forwarded (test/introspection only)."""

        return self._calls_made

    def structured_completion(
        self,
        prompt: str,
        schema: type[OutputT],
        *,
        images: Sequence[ImageInput] | None = None,
    ) -> OutputT:
        self._charge_or_fail()
        return self._wrapped.structured_completion(prompt, schema, images=images)

    def _charge_or_fail(self) -> None:
        """Check both bounds and reserve a call slot, or fail closed on breach.

        The deadline is checked before the count so an over-time run stops even with
        call budget to spare. Fixed content-free reasons only — never any call content.
        """

        with self._lock:
            if self._clock() - self._started_at > self._deadline_seconds:
                raise RunBudgetExceeded(WALL_CLOCK_DEADLINE_EXCEEDED)
            if self._calls_made >= self._max_provider_calls:
                raise RunBudgetExceeded(PROVIDER_CALL_BUDGET_EXCEEDED)
            self._calls_made += 1

    def _complete(
        self,
        prompt: str,
        schema: Any,
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:  # pragma: no cover - never invoked
        # ``structured_completion`` is fully overridden to delegate to the wrapped
        # provider (which owns retries/validation), so this base hook is never reached;
        # it exists only to satisfy the abstract ``Provider`` interface.
        raise NotImplementedError
