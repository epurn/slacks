"""Per-run provider-call / wall-clock ceiling tests (FTY-363).

These pin the run-scoped ceiling that stops a single estimation attempt from making
an unbounded number of sequential provider calls or running unbounded wall-clock:

- a run whose steps would call the provider past the budget terminates ``failed``,
  non-retryable, within the budgeted number of calls — not in an unbounded loop;
- a run whose wall-clock passes the deadline mid-run (injected clock, no real sleep)
  fails closed the same way, with a sanitized content-free reason;
- an in-budget run is unchanged — it completes, and the wrapped provider's recorded
  identity is preserved;
- through the worker the terminal maps ``processing → failed`` immediately (no extra
  attempt burned), and the default (``pipeline=None``) worker path wraps its built
  provider in the budgeted provider (wired and reachable).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import EstimationJobStatus, LogEventStatus
from app.estimator import worker_pipeline
from app.estimator.pipeline import EstimationContext, Pipeline, PipelineOutcome, StepFailed
from app.estimator.processing import process_estimation
from app.estimator.run_budget import (
    PROVIDER_CALL_BUDGET_EXCEEDED,
    WALL_CLOCK_DEADLINE_EXCEEDED,
    BudgetedProvider,
    RunBudgetExceeded,
)
from app.llm.base import Provider
from app.llm.providers.fake import FakeProvider

RAW_TEXT = "4 toppables brand crackers with 1tbsp dill pickle hummus"


class _Echo(BaseModel):
    """Minimal schema so the stub step can drive a real ``structured_completion``."""

    value: int


class _LoopStep:
    """A step that calls the provider ``calls`` times — a stand-in for a run whose
    official/reference/model-prior cascade would make more calls than the budget."""

    name = "loop"

    def __init__(self, provider: Provider, *, calls: int) -> None:
        self._provider = provider
        self._calls = calls

    def run(self, context: EstimationContext) -> None:
        for _ in range(self._calls):
            # The prompt deliberately carries the raw user text; the ceiling's terminal
            # reason must still be content-free (asserted below).
            self._provider.structured_completion(f"estimate: {context.raw_text}", _Echo)


def _context() -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=RAW_TEXT)


def _fake(count: int) -> FakeProvider:
    """A fake scripted with ``count`` valid ``_Echo`` payloads and a recorded model."""

    return FakeProvider(responses=[{"value": 1}] * count, model="fake-model")


def test_provider_call_budget_terminates_run_within_budget() -> None:
    fake = _fake(count=50)
    budgeted = BudgetedProvider(fake, max_provider_calls=3, deadline_seconds=10_000.0)
    # The step would make 20 calls; the ceiling must stop it at the budget.
    result = Pipeline([_LoopStep(budgeted, calls=20)]).run(_context())

    assert result.outcome is PipelineOutcome.FAILED
    assert result.retryable is False  # deterministic: a re-run hits the same bound
    assert result.error == PROVIDER_CALL_BUDGET_EXCEEDED
    # Bounded — exactly the budget reached the provider, not an unbounded loop.
    assert len(fake.prompts) == 3
    assert budgeted.calls_made == 3


def test_wall_clock_deadline_terminates_run_with_injected_clock() -> None:
    fake = _fake(count=50)
    # Injected monotonic clock: 0 at construction, then 10, 20 (under the 50s deadline),
    # then 60 (over it) on the third call — no real sleeping.
    ticks = iter([0.0, 10.0, 20.0, 60.0])
    budgeted = BudgetedProvider(
        fake,
        max_provider_calls=10_000,
        deadline_seconds=50.0,
        clock=lambda: next(ticks),
    )
    result = Pipeline([_LoopStep(budgeted, calls=20)]).run(_context())

    assert result.outcome is PipelineOutcome.FAILED
    assert result.retryable is False
    assert result.error == WALL_CLOCK_DEADLINE_EXCEEDED
    # Two calls landed before the clock crossed the deadline; the third failed closed.
    assert len(fake.prompts) == 2
    assert budgeted.calls_made == 2


def test_terminal_reason_is_content_free() -> None:
    fake = _fake(count=50)
    budgeted = BudgetedProvider(fake, max_provider_calls=1, deadline_seconds=10_000.0)
    context = _context()
    result = Pipeline([_LoopStep(budgeted, calls=5)]).run(context)

    # The reason is a fixed label, never the raw entry text the prompt carried.
    assert result.error == PROVIDER_CALL_BUDGET_EXCEEDED
    assert RAW_TEXT not in (result.error or "")
    for entry in context.trace:
        assert RAW_TEXT not in repr(entry)


def test_in_budget_run_completes_and_preserves_provider_identity() -> None:
    fake = _fake(count=10)
    budgeted = BudgetedProvider(fake, max_provider_calls=10, deadline_seconds=10_000.0)
    # Identity is mirrored so a budgeted run's recorded provider/model (FTY-255) is
    # byte-identical to an un-budgeted run.
    assert budgeted.name == fake.name
    assert budgeted.model == fake.model == "fake-model"

    result = Pipeline([_LoopStep(budgeted, calls=2)]).run(_context())

    assert result.outcome is PipelineOutcome.COMPLETED
    assert result.error is None
    assert budgeted.calls_made == 2
    assert len(fake.prompts) == 2


def test_run_budget_exceeded_is_a_step_failed() -> None:
    # A ``StepFailed`` subclass, so the pipeline maps a breach to a terminal,
    # non-retryable failure and no step's LLM-error handling swallows it.
    assert issubclass(RunBudgetExceeded, StepFailed)


# --------------------------------------------------------------------------- #
# Worker integration.
# --------------------------------------------------------------------------- #


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _seed_event(client: TestClient, email: str) -> tuple[uuid.UUID, uuid.UUID]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": RAW_TEXT},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


def test_worker_maps_ceiling_breach_to_failed_without_burning_attempts(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "ceiling@example.com")
    budgeted = BudgetedProvider(_fake(count=50), max_provider_calls=3, deadline_seconds=10_000.0)
    pipeline = Pipeline([_LoopStep(budgeted, calls=20)])

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    # Deterministic terminal: processing → failed immediately, exactly one attempt.
    assert result.job_status is EstimationJobStatus.FAILED
    assert result.event_status is LogEventStatus.FAILED
    assert result.should_retry is False
    assert result.attempts == 1
    assert budgeted.calls_made == 3

    # A redelivery is an idempotent no-op — the terminal job is not reprocessed, so no
    # second attempt is burned on the same input.
    again = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)
    assert again.job_status is EstimationJobStatus.FAILED
    assert again.run_id is None
    assert again.attempts == 1


def test_default_worker_path_wraps_provider_in_run_budget(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production ``pipeline=None`` path wraps its built provider (wired/reachable)."""

    user_id, event_id = _seed_event(client, "wrapped@example.com")
    built = FakeProvider(responses=[], model="fake-model")
    monkeypatch.setattr(worker_pipeline, "build_provider", lambda _settings: built)

    captured: dict[str, Provider] = {}

    def _spy(wrapped: Provider, **kwargs: object) -> BudgetedProvider:
        captured["wrapped"] = wrapped
        return BudgetedProvider(wrapped, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(worker_pipeline, "BudgetedProvider", _spy)

    # The build path constructs the real pipeline (no network at construction) and runs
    # it; the fake has no scripted response, so the run fails, but the wrap happened
    # before the pipeline ran — which is all this asserts.
    process_estimation(session, log_event_id=event_id, user_id=user_id)

    assert captured["wrapped"] is built
