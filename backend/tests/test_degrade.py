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
    DEFAULT_DEGRADE_HEADROOM_SECONDS,
    DEFAULT_RUN_DEADLINE_SECONDS,
    DEFAULT_SOFT_RUN_DEADLINE_SECONDS,
    PROVIDER_CALL_BUDGET_EXCEEDED,
    WALL_CLOCK_DEADLINE_EXCEEDED,
    BudgetedProvider,
)
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
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
# FTY-425: reserved degrade headroom below the hard ceiling. A slow *multi-call*
# resolution (the real official→reference→model-prior cascade costs several provider
# calls per candidate) that crosses the soft budget must fall forward to the
# **model-prior** degrade (real macros) for its remaining candidates, not eat the
# whole hard budget and spill into the budget-free deterministic coarse prior. These
# drive the REAL OfficialSourceResolveStep + BudgetedProvider + DegradeProducer with an
# injected call-count clock (no real sleeping); the only stub is a prompt-routing
# provider that makes a reference-page extract miss (so a candidate costs two calls to
# resolve) while a model-prior estimate resolves (a degrade costs one). That call-cost
# asymmetry — not present when search is disabled (one call/candidate) — is exactly what
# the soft budget converts to cheap degrades, so reserving more headroom lands more of
# them via the good path.
# --------------------------------------------------------------------------- #

#: Prompt openers that route the fake (from ``searched_reference.py``): the model-prior
#: estimate resolves; a reference-page transcription misses.
_MODEL_PRIOR_MARKER = "nutrition estimator"
_EXTRACT_MARKER = "transcriber"


class _RoutingProvider(FakeProvider):
    """A network-free fake that answers by prompt kind rather than a fixed script.

    A reference-page **extract** (transcriber prompt) always returns ``unresolved`` — the
    page states no facts — so a candidate walks reference → model prior: **two** provider
    calls to resolve. A **model-prior** estimate (estimator prompt) always resolves — so a
    *degrade* costs **one** call. No fixed response count, so the same provider serves any
    mix of resolved/degraded candidates deterministically.
    """

    def __init__(self, *, calories: float = 250.0) -> None:
        super().__init__(responses=[])
        self._calories = calories

    def _complete(self, prompt, schema, *, images, timeout_seconds):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        self.image_counts.append(len(images) if images else 0)
        if _MODEL_PRIOR_MARKER in prompt:
            return _resolved_estimate(calories=self._calories)
        assert _EXTRACT_MARKER in prompt  # the only other provider prompt this run makes
        return {"disposition": "unresolved", "confidence": 0.1}


class _EnabledMissSearchProvider:
    """Search enabled + available, always returning one snippet-less result whose page
    the routing provider misses — so a generic candidate reaches the model-prior tier."""

    @property
    def enabled(self) -> bool:
        return True

    @property
    def available(self) -> bool:
        return True

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product",),
            enabled=True,
            available=True,
        )

    def search(self, query: str) -> SearchResult:
        return SearchResult(
            status=SearchStatus.SUCCESS,
            candidates=(SearchCandidate(url="https://example.test/ref", title="ref"),),
        )


def _page_fetch(url: str, settings: object) -> str:
    """A non-empty inert reference page (the routing provider extracts nothing from it)."""

    return "Reference page. No nutrition facts stated here."


def _multi_call_step(budgeted: BudgetedProvider) -> OfficialSourceResolveStep:
    """The real official step wired so each candidate's resolution costs two calls."""

    return OfficialSourceResolveStep(
        provider=budgeted,
        search_provider=_EnabledMissSearchProvider(),
        fetch_settings=OfficialFetchSettings(),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_page_fetch,
        reference_fetch_fn=_page_fetch,
    )


def _budgeted_default(
    fake: FakeProvider, *, per_call: float, soft_deadline: float | None = None
) -> BudgetedProvider:
    """A budgeted provider at the **default** hard ceiling and (unless overridden) the
    default soft deadline, on the call-count clock (elapsed = calls_made * per_call)."""

    clock = _CallCountClock(per_call=per_call)
    soft = DEFAULT_SOFT_RUN_DEADLINE_SECONDS if soft_deadline is None else soft_deadline
    budgeted = BudgetedProvider(fake, clock=clock, soft_deadline_seconds=soft)
    clock.provider = budgeted
    return budgeted


def _generic_pending(n: int) -> list[CandidateDraft]:
    return [
        CandidateDraft(name=f"stew {i}", quantity_text="150g", unit="g", amount=150.0)
        for i in range(n)
    ]


def _run_multi_call_meal(*, per_call: float, soft_deadline: float | None) -> EstimationContext:
    """Run an 8-item multi-call meal through the real step at ``per_call`` latency."""

    fake = _RoutingProvider(calories=250.0)
    budgeted = _budgeted_default(fake, per_call=per_call, soft_deadline=soft_deadline)
    step = _multi_call_step(budgeted)
    context = _context()
    context.pending_official_candidates = _generic_pending(8)
    result = Pipeline([step]).run(context)
    # Never a raised hard breach: the graceful soft-degradation kept the run alive.
    assert result.outcome is PipelineOutcome.COMPLETED
    return context


def _outcome_of(item: ResolvedFoodItem) -> str:
    if _degraded_labels(item):
        # Coarse deterministic prior fingerprint (200 kcal/100g) ⇒ budget-free last-ditch;
        # any other per-100g value ⇒ a real model-prior degrade.
        return "budget_free" if item.calories_per_100g == pytest.approx(200.0) else "model_prior"
    return "resolved"


def test_reserved_headroom_lands_overflow_degrade_on_the_model_prior_path() -> None:
    """The FTY-425 fix: with the reshaped (wider) reserved headroom, the slow meal's
    overflow candidate degrades via the **model-prior** path with real, non-null macros
    and lands inside the hard ceiling — where the pre-FTY-425 narrower headroom (soft at
    45 s) spilled that same candidate into the budget-free deterministic coarse prior."""

    # NEW: default reserved headroom (soft 30 s below the 75 s hard ceiling).
    new_context = _run_multi_call_meal(per_call=8.0, soft_deadline=None)
    new_outcomes = [_outcome_of(item) for item in new_context.resolved_food_items]
    # No candidate spilled into the budget-free coarse prior; the overflow degraded rows
    # all carry real model-prior macros.
    assert "budget_free" not in new_outcomes
    degraded = [item for item in new_context.resolved_food_items if _degraded_labels(item)]
    assert degraded, "the slow meal must fall forward to degraded estimates"
    for item in degraded:
        assert item.source_type == MODEL_PRIOR_SOURCE_TYPE
        assert item.calories_per_100g == pytest.approx(250.0)  # the real rough estimate
        assert item.protein_g is not None and item.protein_g > 0  # never a silent null
        assert _degraded_labels(item) == ["degraded:run_wall_clock_deadline_exceeded"]

    # OLD: the pre-FTY-425 narrower reserved headroom (soft 45 s) forced under this exact
    # slow meal — resolution eats more of the budget, so the last candidate spills into the
    # budget-free coarse prior. This is the regression the reshape fixes.
    old_context = _run_multi_call_meal(per_call=8.0, soft_deadline=45.0)
    old_outcomes = [_outcome_of(item) for item in old_context.resolved_food_items]
    assert "budget_free" in old_outcomes


def test_reserved_headroom_relationship_fits_the_degrade_producers_own_calls() -> None:
    """AC (b): the soft deadline is pinned exactly the reserved headroom below the hard
    ceiling, and that headroom fits several per-candidate model-prior degrade calls."""

    assert (
        DEFAULT_SOFT_RUN_DEADLINE_SECONDS
        == DEFAULT_RUN_DEADLINE_SECONDS - DEFAULT_DEGRADE_HEADROOM_SECONDS
    )
    # Sized for a slow ~10-15 s/call CLI provider: at least ~3 fall-forward model-prior
    # degrade calls fit in the reserved window before the hard ceiling.
    slow_per_call = 12.0
    assert DEFAULT_DEGRADE_HEADROOM_SECONDS / slow_per_call >= 3.0
    # And the whole hard budget still terminates inside the live smoke's 90 s poll window.
    assert DEFAULT_RUN_DEADLINE_SECONDS < 90.0


def test_runaway_still_degrades_budget_free_at_the_hard_ceiling() -> None:
    """AC (c): a run so slow the degrade producer can never afford a model-prior call
    still stops at the hard ceiling and falls to the budget-free deterministic prior as
    the last-ditch (never removed, only narrowed), terminating inside the poll window."""

    fake = _RoutingProvider(calories=250.0)
    # 40 s/call: resolving the first candidate (2 calls) already lands elapsed at 80 s —
    # past the 75 s hard ceiling — so every later candidate has zero provider headroom.
    budgeted = _budgeted_default(fake, per_call=40.0, soft_deadline=None)
    step = _multi_call_step(budgeted)
    context = _context()
    context.pending_official_candidates = _generic_pending(3)

    result = Pipeline([step]).run(context)

    assert result.outcome is PipelineOutcome.COMPLETED  # never a terminal failure
    outcomes = [_outcome_of(item) for item in context.resolved_food_items]
    assert "budget_free" in outcomes  # the last-ditch deterministic prior still fires
    for item in context.resolved_food_items:
        if _outcome_of(item) == "budget_free":
            assert item.calories_per_100g == pytest.approx(200.0)  # coarse prior
            assert item.protein_g is not None and item.protein_g > 0  # still macros (FTY-418)
    # The hard ceiling still bounded the work: no provider call was charged past it, so the
    # run terminates well inside the 90 s poll window (max elapsed 80 s < 90 s).
    assert budgeted._clock() - budgeted._started_at < 90.0


def test_in_budget_meal_is_unchanged_by_the_reshaped_headroom() -> None:
    """Regression: a normal in-budget run (fast provider) never crosses the (lower) soft
    deadline, so it still resolves every candidate exactly — no degraded rows."""

    fake = _RoutingProvider(calories=250.0)
    budgeted = _budgeted_default(fake, per_call=1.0, soft_deadline=None)  # 1 s/call: fast
    step = _multi_call_step(budgeted)
    context = _context()
    context.pending_official_candidates = _generic_pending(8)

    result = Pipeline([step]).run(context)

    assert result.outcome is PipelineOutcome.COMPLETED
    # 8 candidates × 2 calls each, all exact — nothing degraded (16 calls, elapsed 16 s).
    assert all(_degraded_labels(item) == [] for item in context.resolved_food_items)
    assert budgeted.calls_made == 16


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
