"""Rough-estimate degrade producer + soft-degradation fall-forward tests (FTY-371).

These drive the estimator side of the never-fail directive with network-free fakes:

- the degrade producer turns an interpreted-but-unresolved candidate into a rough
  ``resolved`` row (never a silent zero) in both **primary** (one bounded model-prior
  call) and **budget-free** (zero provider calls) modes, each carrying rough model-prior
  provenance and a content-free ``degraded:<reason>`` assumption;
- a slow multi-component resolution that crosses the **soft** budget falls forward to
  rough estimates for its remaining candidates and reaches ``completed`` **within** the
  hard ceiling — proven with a call-counting stub provider and an injected clock (no real
  sleeping), a regression against the live ``run_wall_clock_deadline_exceeded`` casualty;
- a run completing **within** the soft budget never invokes the degrade producer and its
  resolved rows carry normal (non-rough) provenance.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.degrade import (
    COARSE_ENERGY_DENSITY_KCAL_PER_100G,
    DEGRADED_DEFAULT_SERVING_ASSUMPTION,
    DegradeProducer,
    degraded_assumption,
)
from app.estimator.fdc import ProductFacts
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_step import FoodResolveStep
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    Pipeline,
    PipelineOutcome,
    ResolvedFoodItem,
)
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.run_budget import (
    PROVIDER_CALL_BUDGET_EXCEEDED,
    WALL_CLOCK_DEADLINE_EXCEEDED,
    BudgetedProvider,
)
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource

_HARD_DEADLINE = 75.0
_SOFT_DEADLINE = 10.0


def _context() -> EstimationContext:
    return EstimationContext(
        log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text="a homemade dinner"
    )


def _resolved_estimate(*, calories: float = 250.0, confidence: float = 0.85) -> dict[str, Any]:
    """A model-prior per-100g estimate the fake provider returns for one candidate."""

    return {
        "disposition": "resolved",
        "confidence": confidence,
        "facts": {
            "basis": "per_100g",
            "calories": calories,
            "protein_g": 8.0,
            "carbs_g": 30.0,
            "fat_g": 10.0,
        },
        "assumptions": ["typical recipe"],
    }


class _DisabledSearchProvider:
    """Search disabled, so a candidate falls straight to the model-prior tier."""

    @property
    def enabled(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return False

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product",),
            enabled=False,
            available=False,
        )

    def search(self, query: str) -> SearchResult:  # pragma: no cover - search disabled
        return SearchResult(status=SearchStatus.PARTIAL)


def _unused_fetch(url: str, settings: object) -> str:  # pragma: no cover - search disabled
    raise AssertionError("fetch must not run when search is disabled")


class _CallCountClock:
    """A deterministic monotonic clock keyed to the budgeted provider's call count.

    ``elapsed = calls_made * per_call`` — advancing exactly ``per_call`` seconds per
    provider call, so a test can place the soft crossing between two candidates without
    counting the exact number of internal ``clock()`` reads (the budgeted provider and
    the soft/headroom checks each read it, and this clock is idempotent between calls).
    """

    def __init__(self, *, per_call: float) -> None:
        self.per_call = per_call
        self.provider: BudgetedProvider | None = None

    def __call__(self) -> float:
        calls = 0 if self.provider is None else self.provider.calls_made
        return calls * self.per_call


def _budgeted(fake: FakeProvider, *, per_call: float) -> BudgetedProvider:
    clock = _CallCountClock(per_call=per_call)
    budgeted = BudgetedProvider(
        fake,
        deadline_seconds=_HARD_DEADLINE,
        soft_deadline_seconds=_SOFT_DEADLINE,
        clock=clock,
    )
    clock.provider = budgeted
    return budgeted


def _official_step(provider: object, **kwargs: Any) -> OfficialSourceResolveStep:
    return OfficialSourceResolveStep(
        provider=provider,  # type: ignore[arg-type]
        search_provider=_DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
        **kwargs,
    )


def _degraded_labels(item: ResolvedFoodItem) -> list[str]:
    return [a for a in item.assumptions if a.startswith("degraded:")]


# --------------------------------------------------------------------------- #
# The degrade producer in isolation.
# --------------------------------------------------------------------------- #


def test_primary_mode_makes_one_provider_call_and_marks_the_estimate_degraded() -> None:
    provider = FakeProvider(responses=[_resolved_estimate(calories=250.0)])
    producer = DegradeProducer(provider=provider)
    context = _context()
    candidate = CandidateDraft(name="lentil stew", quantity_text="150g", unit="g", amount=150.0)

    item = producer.degrade_food_candidate(
        context, candidate, reason=WALL_CLOCK_DEADLINE_EXCEEDED, index=0, budget_free=False
    )

    assert len(provider.prompts) == 1  # primary mode spends exactly one model-prior call
    assert item.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert item.calories == pytest.approx(375.0)  # 250/100g * 150g — a real rough number
    assert item.grams == pytest.approx(150.0)
    assert _degraded_labels(item) == ["degraded:run_wall_clock_deadline_exceeded"]
    # The content-free label is surfaced on the run for provenance.
    assert "degraded:run_wall_clock_deadline_exceeded" in context.assumptions


def test_budget_free_mode_makes_zero_provider_calls_and_still_resolves() -> None:
    # A provider with no scripted response: budget-free mode must never touch it.
    provider = FakeProvider(responses=[])
    producer = DegradeProducer(provider=provider)
    context = _context()
    candidate = CandidateDraft(name="mystery stew", quantity_text="150g", unit="g", amount=150.0)

    item = producer.degrade_food_candidate(
        context, candidate, reason=PROVIDER_CALL_BUDGET_EXCEEDED, index=0, budget_free=True
    )

    assert provider.prompts == []  # ZERO provider calls
    assert item.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert item.calories == pytest.approx(
        round(150.0 / 100.0 * COARSE_ENERGY_DENSITY_KCAL_PER_100G, 1)
    )
    assert item.calories > 0  # a real rough row, never a silent zero
    # FTY-418: a resolved rough row carries macros (honestly rough, marked
    # estimated), never a silent null — 150 g at the documented mixed-food split.
    assert item.protein_g == pytest.approx(15.0)  # 150g * 10/100g
    assert item.carbs_g == pytest.approx(37.5)  # 150g * 25/100g
    assert item.fat_g == pytest.approx(10.1)  # 150g * 6.7/100g
    assert item.field_provenance is not None
    assert item.field_provenance["protein_g"] == "estimated"
    labels = set(item.assumptions)
    assert "degraded:run_provider_call_budget_exceeded" in labels
    assert DEGRADED_DEFAULT_SERVING_ASSUMPTION in labels


def test_budget_free_amountless_candidate_uses_a_coarse_default_serving() -> None:
    provider = FakeProvider(responses=[])
    producer = DegradeProducer(provider=provider)
    context = _context()
    candidate = CandidateDraft(name="mystery snack")

    item = producer.degrade_food_candidate(
        context, candidate, reason=WALL_CLOCK_DEADLINE_EXCEEDED, index=None, budget_free=True
    )

    assert provider.prompts == []
    assert item.grams == pytest.approx(100.0)  # one coarse default serving
    assert item.calories == pytest.approx(200.0)
    assert DEGRADED_DEFAULT_SERVING_ASSUMPTION in item.assumptions


def test_budget_free_counted_everyday_food_uses_a_food_aware_portion() -> None:
    # FTY-418: even the emergency provider-free prior must give a counted everyday
    # food a realistic per-slice gram mass ("1 slice of mozzarella" ≈ 22 g), never a
    # flat 100 g slice, and carry macros rather than a silent null.
    provider = FakeProvider(responses=[])
    producer = DegradeProducer(provider=provider)
    context = _context()
    candidate = CandidateDraft(name="mozzarella", quantity_text="1 slice", unit="slice", amount=1.0)

    item = producer.degrade_food_candidate(
        context, candidate, reason=WALL_CLOCK_DEADLINE_EXCEEDED, index=0, budget_free=True
    )

    assert provider.prompts == []
    assert item.grams == pytest.approx(22.0)  # food-aware slice, not a flat 100 g
    assert item.calories == pytest.approx(44.0)  # 22g * 200/100g
    assert item.protein_g is not None and item.protein_g > 0
    # The food-aware portion label replaces the coarse default-serving assumption.
    assert any("estimated_common_portion:mozzarella" in a for a in item.assumptions)
    assert DEGRADED_DEFAULT_SERVING_ASSUMPTION not in item.assumptions


def test_primary_falls_back_to_the_deterministic_prior_when_the_estimate_is_unusable() -> None:
    # The provider is consulted (one call) but returns an unresolved disposition, so the
    # producer degrades to the deterministic coarse prior rather than failing the entry.
    provider = FakeProvider(responses=[{"disposition": "unresolved", "confidence": 0.1}])
    producer = DegradeProducer(provider=provider)
    context = _context()
    candidate = CandidateDraft(
        name="leftover casserole", quantity_text="150g", unit="g", amount=150.0
    )

    item = producer.degrade_food_candidate(
        context, candidate, reason=WALL_CLOCK_DEADLINE_EXCEEDED, index=0, budget_free=False
    )

    assert len(provider.prompts) == 1
    assert item.calories == pytest.approx(300.0)  # coarse prior: 150g * 200/100g
    assert item.protein_g == pytest.approx(15.0)  # FTY-418: rough macros, never null
    assert DEGRADED_DEFAULT_SERVING_ASSUMPTION in item.assumptions


def test_degraded_assumption_rejects_non_content_free_reasons() -> None:
    # Only the fixed breach labels are allowed, so a raw phrase can never leak into the
    # degraded assumption.
    with pytest.raises(ValueError, match="content-free"):
        degraded_assumption("a homemade dinner")


# --------------------------------------------------------------------------- #
# Soft-degradation fall-forward through the resolution step.
# --------------------------------------------------------------------------- #


def _two_pending() -> tuple[CandidateDraft, CandidateDraft]:
    return (
        CandidateDraft(name="lentil stew", quantity_text="150g", unit="g", amount=150.0),
        CandidateDraft(name="barley soup", quantity_text="200g", unit="g", amount=200.0),
    )


def test_soft_budget_crossing_falls_forward_to_rough_within_the_hard_ceiling() -> None:
    first, second = _two_pending()
    # per_call 11s > soft 10s: the first candidate resolves exactly (one model-prior
    # call), crossing the soft deadline; the second falls forward to a rough estimate.
    fake = FakeProvider(
        responses=[_resolved_estimate(calories=250.0), _resolved_estimate(calories=180.0)]
    )
    budgeted = _budgeted(fake, per_call=11.0)
    step = _official_step(budgeted)
    context = _context()
    context.pending_official_candidates = [first, second]

    result = Pipeline([step]).run(context)

    assert result.outcome is PipelineOutcome.COMPLETED
    assert [item.name for item in context.resolved_food_items] == ["lentil stew", "barley soup"]
    exact, degraded = context.resolved_food_items
    assert _degraded_labels(exact) == []  # the in-flight candidate resolved exactly
    assert _degraded_labels(degraded) == ["degraded:run_wall_clock_deadline_exceeded"]
    assert degraded.calories > 0
    # Landed inside the hard ceiling: two calls (candidate-1 exact + candidate-2 primary
    # degrade), never breaching the 75s deadline (max elapsed 22s).
    assert budgeted.calls_made == 2


class _ForbiddenDegrade(DegradeProducer):
    """A degrade producer that fails the test if the fall-forward ever invokes it."""

    def degrade_food_candidate(self, *args: Any, **kwargs: Any) -> ResolvedFoodItem:
        raise AssertionError("degrade producer must not run within the soft budget")


def test_within_soft_budget_never_invokes_the_degrade_producer() -> None:
    first, second = _two_pending()
    fake = FakeProvider(
        responses=[_resolved_estimate(calories=250.0), _resolved_estimate(calories=180.0)]
    )
    budgeted = _budgeted(fake, per_call=1.0)  # 1s/call stays far under the 10s soft deadline
    step = _official_step(budgeted, degrade_producer=_ForbiddenDegrade(provider=fake))
    context = _context()
    context.pending_official_candidates = [first, second]

    result = Pipeline([step]).run(context)

    assert result.outcome is PipelineOutcome.COMPLETED
    assert len(context.resolved_food_items) == 2
    # No resolved row carries a degraded assumption; both used the normal exact path.
    for item in context.resolved_food_items:
        assert _degraded_labels(item) == []
    assert budgeted.calls_made == 2


# --------------------------------------------------------------------------- #
# The soft-budget API on the budgeted provider.
# --------------------------------------------------------------------------- #


def test_soft_budget_reason_reports_without_raising() -> None:
    fake = FakeProvider(responses=[{"value": 1}] * 50)
    budgeted = _budgeted(fake, per_call=6.0)

    assert budgeted.soft_budget_reason() is None  # 0 calls: headroom
    assert budgeted.can_make_provider_call() is True


def test_can_make_provider_call_is_false_past_the_hard_deadline() -> None:
    fake = FakeProvider(responses=[{"value": 1}] * 50)
    # Clock reads 0 at construction (start time) then 100s afterwards — past the hard
    # deadline: no headroom, and the soft reason reports the wall-clock breach without
    # raising. No real sleeping.
    ticks = iter([0.0, *([100.0] * 8)])
    budgeted = BudgetedProvider(
        fake,
        deadline_seconds=_HARD_DEADLINE,
        soft_deadline_seconds=_SOFT_DEADLINE,
        clock=lambda: next(ticks),
    )

    assert budgeted.can_make_provider_call() is False
    assert budgeted.soft_budget_reason() == WALL_CLOCK_DEADLINE_EXCEEDED


# --------------------------------------------------------------------------- #
# End-to-end persistence: the degraded row is committed against the real datastore.
# --------------------------------------------------------------------------- #


class _MissingFoodSource:
    """A network-free USDA stand-in that is enabled but resolves nothing (every
    generic candidate misses and defers to the web-evidence/degrade path)."""

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        return None


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


def test_soft_degraded_candidate_persists_as_a_resolved_rough_row(
    client: TestClient, session: Session
) -> None:
    """The full parse -> food -> official pipeline lands the degraded candidate as a
    committed ``resolved`` row with rough model-prior provenance and the content-free
    degraded assumption — proven against the real datastore, not just in memory."""

    user_id, event_id = _seed_event(
        client, "degrade-e2e@example.com", "lentil stew and barley soup"
    )
    parse_provider = FakeProvider(
        responses=[
            {
                "disposition": "parsed",
                "confidence": 0.95,
                "items": [
                    {
                        "type": "food",
                        "name": "lentil stew",
                        "quantity_text": "150g",
                        "unit": "g",
                        "amount": 150,
                    },
                    {
                        "type": "food",
                        "name": "barley soup",
                        "quantity_text": "200g",
                        "unit": "g",
                        "amount": 200,
                    },
                ],
            }
        ]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    fake = FakeProvider(
        responses=[_resolved_estimate(calories=250.0), _resolved_estimate(calories=180.0)]
    )
    budgeted = _budgeted(fake, per_call=11.0)  # crosses the 10s soft deadline after one call
    pipeline = Pipeline(
        [
            ParseStep(parse_provider),
            FoodResolveStep(FoodResolver(session=session, source=_MissingFoodSource())),
            _official_step(budgeted),
        ]
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )
    by_name = {food.name: food for food in foods}
    degraded = by_name["barley soup"]
    assert degraded.status == DerivedItemStatus.RESOLVED
    assert degraded.calories is not None and degraded.calories > 0  # never a silent zero

    evidence = {
        source.derived_food_item_id: source
        for source in session.scalars(
            select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
        )
    }
    degraded_evidence = evidence[degraded.id]
    assert degraded_evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert degraded_evidence.assumptions is not None
    assert "degraded:run_wall_clock_deadline_exceeded" in degraded_evidence.assumptions
    # The exactly-resolved sibling carries no degraded provenance.
    assert not any(
        a.startswith("degraded:") for a in (evidence[by_name["lentil stew"].id].assumptions or [])
    )
    # No raw diary phrase leaks into the run trace/assumptions/source refs (sanitized).
    run_blob = repr(result)
    assert "lentil stew and barley soup" not in run_blob
