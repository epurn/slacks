"""Never-fail dogfood regression gate (FTY-373).

Locks in the FTY-370 never-fail contract (implemented by FTY-371 recognition +
degrade producer and FTY-372 worker routing) against the **exact** phrases that
failed in the 2026-07-16 live dogfood database, so a future change that
reintroduces a terminal ``failed`` for informal/homemade food or infra trouble
fails CI without needing an authenticated live provider.

The live-local ``make food-smoke`` band assertions for these same phrases live as
data in ``app/ops/food_dogfood_fixtures.json``; this module is the network-free
CI-enforced half, reusing the FTY-371/FTY-372 seams (``ParseStep`` +
``FakeProvider`` self-consistency; ``process_estimation`` with a stub pipeline and
the budget-free degrade producer). The three invariants pinned here mirror the
story Scope:

- ``nicorette 4mg gum`` (was ``unparseable_input``) parses to a recognized
  candidate, while a genuine non-food control still routes to
  ``unparseable_input``;
- the exact banh-mi phrase, forced past the run budget with an interpreted
  candidate, degrades to a rough ``completed`` estimate — never terminal
  ``failed``, and with **zero** extra provider calls;
- a ``provider_transient_error`` that exhausts the attempt bound degrades (with a
  candidate) rather than failing.

The exact phrases are operator-approved regression fixtures. They live only as
test data / smoke JSON, never in ``backend/app`` executable source, so the
estimator's no-special-case scan
(``test_exact_snack_phrase_resolution.test_no_implementation_special_cases_the_exact_phrase_or_its_brands``)
keeps holding.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.degrade import (
    PROVIDER_TRANSIENT_EXHAUSTED,
    DegradeProducer,
    degraded_assumption,
)
from app.estimator.parse import ParseStep
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    Pipeline,
    StepError,
    StepFailed,
)
from app.estimator.processing import process_estimation
from app.estimator.run_budget import WALL_CLOCK_DEADLINE_EXCEEDED, RunBudgetExceeded
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.base import ImageInput, OutputT, Provider
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource

#: The exact 2026-07-16 live-repro phrase — failed ×3 in the dogfood DB
#: (``run_wall_clock_deadline_exceeded`` then ``provider_transient_error``).
#: Operator-approved regression fixture; food text only.
_BANH_MI_PHRASE = (
    "homemade banh mi on a brioche style bun with shredded carrot, siracha mayo, "
    "cucumber, green onion and 3 ground pork meat"
)
#: The nicorette pair: the was-``unparseable`` form and its already-completing twin.
_NICORETTE_4MG = "nicorette 4mg gum"
_NICORETTE_BRAND = "nicorette brand gum"


# --------------------------------------------------------------------------- #
# Recognition: informal / consumable phrases parse to an estimate, not unparseable
# --------------------------------------------------------------------------- #


def _context(raw_text: str) -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=raw_text)


def _sampled(reply: dict[str, Any]) -> list[dict[str, Any] | LLMError]:
    return [reply for _ in range(SELF_CONSISTENCY_FIRST_WINDOW)]


def _parsed(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"disposition": "parsed", "confidence": 0.9, "items": items}


def _unparseable() -> dict[str, Any]:
    return {"disposition": "unparseable", "confidence": 0.0, "reason": "not a log"}


@pytest.mark.parametrize(
    ("raw_text", "item"),
    [
        (_NICORETTE_4MG, {"type": "food", "name": "nicorette gum", "quantity_text": "1 piece"}),
        (_NICORETTE_BRAND, {"type": "food", "name": "nicorette gum", "quantity_text": "1 piece"}),
        (
            _BANH_MI_PHRASE,
            {"type": "food", "name": "banh mi", "quantity_text": "1 sandwich", "amount": 1},
        ),
    ],
)
def test_never_fail_phrase_parses_to_a_recognized_candidate(
    raw_text: str, item: dict[str, Any]
) -> None:
    provider = FakeProvider(responses=_sampled(_parsed([item])))
    context = _context(raw_text)

    ParseStep(provider).run(context)

    # Recognized as a loggable food/consumable candidate — never unparseable.
    assert [candidate.name for candidate in context.food_candidates] == [item["name"]]
    assert context.clarification_questions == []


@pytest.mark.parametrize("raw_text", ["how's the weather", "asdf qwerty"])
def test_genuine_non_food_control_still_routes_to_unparseable(raw_text: str) -> None:
    provider = FakeProvider(responses=_sampled(_unparseable()))
    context = _context(raw_text)

    with pytest.raises(StepFailed) as exc:
        ParseStep(provider).run(context)

    assert exc.value.reason == "unparseable_input"


# --------------------------------------------------------------------------- #
# Degrade: an infra breach on an interpreted phrase never lands terminal `failed`
# --------------------------------------------------------------------------- #


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _seed_event(client: TestClient, email: str, raw_text: str) -> tuple[uuid.UUID, uuid.UUID]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": raw_text},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


class _ExplodingProvider(Provider):
    """Fails loudly if the budget-free degrade ever makes a provider call."""

    name = "exploding"

    def __init__(self) -> None:
        super().__init__(timeout_seconds=1.0, max_retries=0)

    def structured_completion(
        self,
        prompt: str,
        schema: type[OutputT],
        *,
        images: Sequence[ImageInput] | None = None,
    ) -> OutputT:  # pragma: no cover - must never run in a budget-free degrade
        raise AssertionError("budget-free degrade must not make a provider call")

    def _complete(
        self,
        prompt: str,
        schema: Any,
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:  # pragma: no cover - never reached
        raise AssertionError("budget-free degrade must not make a provider call")


def _budget_free_producer() -> DegradeProducer:
    return DegradeProducer(provider=_ExplodingProvider())


def _banh_mi_candidate() -> CandidateDraft:
    return CandidateDraft(name="banh mi", quantity_text="1 sandwich", unit=None, amount=1.0)


class _InterpretThenBreachStep:
    """Interpret the banh-mi candidate, then breach the per-run wall-clock ceiling."""

    name = "interpret_then_breach"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.food_candidates.append(_banh_mi_candidate())
        raise RunBudgetExceeded(WALL_CLOCK_DEADLINE_EXCEEDED)


class _InterpretThenTransientStep:
    """Interpret the banh-mi candidate, then fail transiently (retryable)."""

    name = "interpret_then_transient"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.food_candidates.append(_banh_mi_candidate())
        raise StepError("transient_failure")


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence(session: Session, event_id: uuid.UUID) -> list[EvidenceSource]:
    return list(
        session.scalars(select(EvidenceSource).where(EvidenceSource.log_event_id == event_id))
    )


def test_banh_mi_run_deadline_breach_degrades_completed_never_failed(
    client: TestClient, session: Session
) -> None:
    """The exact banh-mi phrase, forced past the wall-clock deadline with an
    interpreted candidate, degrades to a rough ``completed`` estimate — the exact
    ``run_wall_clock_deadline_exceeded`` failure the live DB showed, now non-fatal."""

    user_id, event_id = _seed_event(client, "ncf-banh-mi-deadline@example.com", _BANH_MI_PHRASE)

    result = process_estimation(
        session,
        log_event_id=event_id,
        user_id=user_id,
        pipeline=Pipeline([_InterpretThenBreachStep()]),
        degrade_producer=_budget_free_producer(),  # explodes on any provider call
    )

    # Never ``failed``: the interpreted candidate is committed as a rough estimate.
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert result.should_retry is False

    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    assert foods[0].calories is not None and foods[0].calories > 0

    # The rough row carries the content-free degraded provenance marking, and the
    # raw diary text never leaks into a persisted evidence assumption.
    evidence = _evidence(session, event_id)
    assert len(evidence) == 1
    assert degraded_assumption(WALL_CLOCK_DEADLINE_EXCEEDED) in (evidence[0].assumptions or [])
    assert _BANH_MI_PHRASE not in " ".join(evidence[0].assumptions or [])


def test_banh_mi_transient_exhaustion_degrades_never_failed(
    client: TestClient, session: Session
) -> None:
    """The other live-DB failure mode: a ``provider_transient_error`` that exhausts
    the attempt bound degrades to a rough estimate rather than failing the entry."""

    user_id, event_id = _seed_event(client, "ncf-banh-mi-transient@example.com", _BANH_MI_PHRASE)
    pipeline = Pipeline([_InterpretThenTransientStep()])

    # The standard retries ask the caller to retry (still-working), not fail.
    for _ in range(2):
        result = process_estimation(
            session,
            log_event_id=event_id,
            user_id=user_id,
            pipeline=pipeline,
            max_attempts=3,
            degrade_producer=_budget_free_producer(),
        )
        assert result.should_retry is True
        assert result.event_status is LogEventStatus.PROCESSING

    # The attempt that reaches the bound degrades — never terminal ``failed``.
    final = process_estimation(
        session,
        log_event_id=event_id,
        user_id=user_id,
        pipeline=pipeline,
        max_attempts=3,
        degrade_producer=_budget_free_producer(),
    )
    assert final.event_status is LogEventStatus.COMPLETED
    assert final.job_status is EstimationJobStatus.SUCCEEDED
    assert final.should_retry is False

    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    evidence = _evidence(session, event_id)
    assert degraded_assumption(PROVIDER_TRANSIENT_EXHAUSTED) in (evidence[0].assumptions or [])
