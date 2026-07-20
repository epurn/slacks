"""The rough-estimate degrade producer (FTY-371).

Realizes the estimator side of the never-fail directive (``food-resolution.md``
**Budget/transience-degraded rough estimates**, ``estimation-jobs.md`` v7): turn an
interpreted-but-unresolved food candidate into a rough, honestly-labelled
``resolved`` estimate rather than letting the run hit the FTY-363 hard ceiling and
fail. It is used two ways, both of which always commit a rough ``resolved`` row (never
a silent zero-valued ``unresolved`` row) so the entry is acknowledged and correctable:

- **primary mode** (the soft-degradation fall-forward, FTY-371): a slow multi-component
  resolution that crosses the soft budget switches its remaining candidates here; the
  producer may spend one bounded model-prior call per candidate *within remaining
  budget*, falling to the deterministic prior when that estimate is unusable or the
  hard-ceiling headroom is gone;
- **budget-free mode** (the worker safety net, wired by FTY-372): makes **no** provider
  call at all — a deterministic coarse default-serving rough estimate — so degradation
  is always possible even when the run's provider budget is fully spent.

Every degraded item carries rough ``model_prior`` provenance plus a content-free
``degraded:<reason>`` assumption (built only from the fixed run-budget / transient
breach labels — never raw diary text, prompts, or provider output), so it stays visibly
distinguishable from trusted/exact/saved/edited values and user-editable like any rough
estimate. Deterministic plausibility caps still apply — an implausible primary estimate
falls back to the bounded coarse prior rather than being laundered into a rough number.
The producer never raises: a food entry the user typed in good faith is never returned
``failed`` because the run ran out of budget.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.estimator.common_portions import resolve_common_portion_grams
from app.estimator.evidence_utils import _content_hash, _record_source_ref
from app.estimator.food_serving import NutritionFacts, resolve_grams
from app.estimator.interpretation_tools import add_evidence_record, evidence_status_labels
from app.estimator.model_prior import _estimate_model_prior
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
    StepFailed,
)
from app.estimator.resolved_item import _build_item, _default_serving_grams
from app.estimator.resolved_plausibility import check_resolved_food_total
from app.estimator.run_budget import RUN_BUDGET_REASONS
from app.estimator.searched_reference import (
    MODEL_PRIOR_SOURCE,
    MODEL_PRIOR_SOURCE_TYPE,
    _identity_query,
    searched_reference_from_estimate,
)
from app.llm.base import Provider
from app.schemas.official_source import EstimateDisposition, FactBasis
from app.settings import DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR, EstimatorClarifyMode

#: A bounded-retry transient-provider exhaustion is also a degrade trigger
#: (``estimation-jobs.md`` v7, wired by FTY-372); accepted here so the producer's reason
#: vocabulary is forward-compatible without FTY-372 editing this module. Content-free.
PROVIDER_TRANSIENT_EXHAUSTED = "provider_transient_error"

#: The closed set of content-free reasons a degraded assumption may carry: the FTY-363
#: run-budget breach labels plus the transient-exhaustion label. Anything else is
#: rejected so a raw phrase can never reach the ``degraded:<reason>`` assumption.
DEGRADE_REASONS = frozenset(RUN_BUDGET_REASONS | {PROVIDER_TRANSIENT_EXHAUSTED})

#: Coarse deterministic default serving mass (grams) for the budget-free rough estimate,
#: used when the logged quantity cannot be resolved to grams and no provider headroom
#: remains to estimate a portion. A documented rough prior — one typical solid-food
#: serving — not a measured value; the estimate is labelled degraded and stays editable.
COARSE_DEFAULT_SERVING_GRAMS = 100.0

#: Coarse deterministic mixed-food energy density (kcal per 100 g) for the budget-free
#: rough estimate. A middle-of-the-road prior for a typical mixed food — comfortably
#: inside the per-100g plausibility bound (``food-resolution.md``: ≤ 900 kcal/100g) —
#: documented rough and honestly labelled, never presented as a trusted per-100g fact.
COARSE_ENERGY_DENSITY_KCAL_PER_100G = 200.0

#: Documented per-100g macro split for the coarse energy-density prior (FTY-418). A
#: typical mixed food splits its energy ≈ 50 % carbohydrate / 20 % protein / 30 % fat;
#: at 200 kcal/100g that is 25 g carbs, 10 g protein, 6.7 g fat (Atwater-consistent:
#: 25·4 + 10·4 + 6.7·9 ≈ 200). A resolved rough estimate must carry macros rather than
#: a silent ``null`` (``food-resolution.md``: a tier that produces calories produces
#: macros); these are honestly-rough, marked ``estimated``, and scale with the grams.
COARSE_PROTEIN_PER_100G = 10.0
COARSE_CARBS_PER_100G = 25.0
COARSE_FAT_PER_100G = 6.7

#: Content-free provenance labels for a budget/transience-degraded estimate.
DEGRADED_DEFAULT_SERVING_ASSUMPTION = "degraded_default_serving"
_DETERMINISTIC_PRIOR_ASSUMPTION = "estimated from deterministic degrade prior"
_PRIMARY_MODEL_PRIOR_ASSUMPTION = "estimated from model prior"


def degraded_assumption(reason: str) -> str:
    """Build the content-free ``degraded:<reason>`` provenance label (FTY-370/371).

    ``reason`` must be one of the fixed :data:`DEGRADE_REASONS` breach labels; any other
    value is rejected so the assumption can never carry raw diary text, a prompt, or
    provider output.
    """

    if reason not in DEGRADE_REASONS:
        raise ValueError(f"non-content-free degrade reason: {reason!r}")
    return f"degraded:{reason}"


@dataclass(frozen=True)
class DegradeProducer:
    """Turn interpreted-but-unresolved food candidates into rough degraded estimates.

    Holds the run's (budgeted) provider and the estimate-first rough-fallback config it
    shares with the resolution tiers. :meth:`degrade_food_candidate` always returns a
    ``resolved`` :class:`~app.estimator.pipeline.ResolvedFoodItem` — never raising and
    never a silent zero — in either the bounded ``primary`` mode or the provider-free
    ``budget_free`` mode.
    """

    provider: Provider
    clarify_mode: EstimatorClarifyMode = "estimate_first"
    model_prior_confidence_floor: float = DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR
    step_name: str = "degrade"

    def degrade_food_candidate(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        *,
        reason: str,
        index: int | None,
        budget_free: bool,
    ) -> ResolvedFoodItem:
        """Produce one rough degraded ``resolved`` item for ``candidate``.

        ``reason`` is the content-free breach/exhaustion label the degraded assumption is
        built from. ``budget_free`` forces the deterministic coarse prior with **no**
        provider call (the worker safety net after the hard ceiling was already hit);
        otherwise the bounded model-prior primary mode is tried first and the
        deterministic prior is the fallback when it is unusable.
        """

        assumption = degraded_assumption(reason)
        item = None if budget_free else self._primary(context, candidate, index)
        via_primary = item is not None
        if item is None:
            item = self._deterministic(context, candidate)
        item = _append_assumption(item, assumption)
        self._record(context, index, via_primary=via_primary, budget_free=budget_free)
        for label in item.assumptions:
            if label not in context.assumptions:
                context.assumptions.append(label)
        return item

    def _primary(
        self, context: EstimationContext, candidate: CandidateDraft, index: int | None
    ) -> ResolvedFoodItem | None:
        """Bounded model-prior rough estimate; ``None`` to fall back to the coarse prior.

        Reuses the low-level model-prior estimate + shared serving-math builder, but
        never raises: a provider/schema failure, a non-resolved or low-confidence
        estimate, an unusable/unscalable serving, an implausible resolved total, or a
        hard-ceiling breach mid-call all return ``None`` so the caller degrades to the
        deterministic prior instead of failing the entry.
        """

        _record_source_ref(context, MODEL_PRIOR_SOURCE)
        try:
            estimate, failure = _estimate_model_prior(
                self.provider, candidate, evidence_labels=evidence_status_labels(context)
            )
            if (
                failure is not None
                or estimate is None
                or estimate.disposition is not EstimateDisposition.RESOLVED
                or estimate.confidence < self.model_prior_confidence_floor
            ):
                return None
            reference = searched_reference_from_estimate(
                estimate, source_ref=MODEL_PRIOR_SOURCE, hash_key=_identity_query(candidate)
            )
            if reference is None:
                return None
            item = _build_item(
                context,
                candidate,
                reference,
                source_type=MODEL_PRIOR_SOURCE_TYPE,
                source_ref=MODEL_PRIOR_SOURCE,
                hash_key=_identity_query(candidate),
                base_assumptions=(_PRIMARY_MODEL_PRIOR_ASSUMPTION,),
                step_name=self.step_name,
                clarify_mode=self.clarify_mode,
                quantity_question="",
                # Degrade never asks: an unresolvable serving falls to the coarse prior,
                # regardless of the operator clarify mode, so the entry is acknowledged.
                allow_unresolvable_fallthrough=True,
                candidate_index=index,
            )
        except (NeedsClarification, StepFailed):
            # A stricter clarify mode's default-serving ask, or a hard-ceiling breach
            # (``RunBudgetExceeded`` is a ``StepFailed``) raised by the budgeted provider
            # mid-call — degrade to the deterministic prior rather than fail the entry.
            return None
        if item is None:
            return None
        # Deterministic plausibility cap still applies to a degraded estimate: an
        # implausible resolved total is not laundered into a rough number.
        verdict = check_resolved_food_total(
            name=candidate.name,
            unit=candidate.unit,
            amount=candidate.amount,
            quantity_text=candidate.quantity_text,
            grams=item.grams,
            calories=item.calories,
        )
        if not verdict.plausible:
            return None
        return item

    def _deterministic(
        self, context: EstimationContext, candidate: CandidateDraft
    ) -> ResolvedFoodItem:
        """A coarse, provider-free rough estimate — the always-available last resort.

        Resolves the logged quantity to a **food-aware** gram mass — deterministic
        serving math first, then the documented common-portion table (FTY-418: "1 slice
        of mozzarella" ≈ 22 g, "2 slices of deli turkey" ≈ 28 g each — never a blanket
        100 g) — and only assumes a coarse default serving when neither knows the food.
        It costs that at a documented coarse energy-density prior with a documented
        mixed-food macro split, so even this rare emergency estimate is never a
        flat-lined ``2 cal/g + null macros + 100 g`` row (FTY-418). Macros are honestly
        rough, marked ``estimated`` per field. Bounded by construction, so it always
        yields a plausible ``resolved`` row and never asks or fails.
        """

        _record_source_ref(context, MODEL_PRIOR_SOURCE)
        portion_assumption: str | None = None
        grams = resolve_grams(
            unit=candidate.unit,
            amount=candidate.amount,
            quantity_text=candidate.quantity_text,
            default_serving_g=None,
        )
        if grams is None:
            # A stated count of an everyday food ("1 slice of mozzarella") resolves to a
            # realistic per-food gram mass from the documented common-portion table
            # rather than a blanket default serving.
            portion = resolve_common_portion_grams(
                name=candidate.name,
                unit=candidate.unit,
                amount=candidate.amount,
                quantity_text=candidate.quantity_text,
            )
            if portion is not None:
                grams = portion.grams
                portion_assumption = portion.assumption
        if grams is None:
            grams = _default_serving_grams(candidate, COARSE_DEFAULT_SERVING_GRAMS)
        if grams is None:
            grams = COARSE_DEFAULT_SERVING_GRAMS
        grams = round(grams, 3)
        scale = grams / 100.0
        calories = round(scale * COARSE_ENERGY_DENSITY_KCAL_PER_100G, 1)
        protein_g = round(scale * COARSE_PROTEIN_PER_100G, 1)
        carbs_g = round(scale * COARSE_CARBS_PER_100G, 1)
        fat_g = round(scale * COARSE_FAT_PER_100G, 1)
        # Fingerprint the coarse canonical facts (no user data).
        content_hash = _content_hash(
            MODEL_PRIOR_SOURCE,
            NutritionFacts(
                calories=COARSE_ENERGY_DENSITY_KCAL_PER_100G,
                protein_g=COARSE_PROTEIN_PER_100G,
                carbs_g=COARSE_CARBS_PER_100G,
                fat_g=COARSE_FAT_PER_100G,
            ),
        )
        # A food-aware portion replaces the coarse default-serving label; a genuine
        # fall-through to the coarse serving keeps the default-serving assumption.
        serving_label = portion_assumption or DEGRADED_DEFAULT_SERVING_ASSUMPTION
        return ResolvedFoodItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            grams=grams,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            product_id=None,
            source_type=MODEL_PRIOR_SOURCE_TYPE,
            source_ref=MODEL_PRIOR_SOURCE,
            content_hash=content_hash,
            fetched_at=datetime.now(UTC),
            calories_per_100g=COARSE_ENERGY_DENSITY_KCAL_PER_100G,
            protein_per_100g=COARSE_PROTEIN_PER_100G,
            carbs_per_100g=COARSE_CARBS_PER_100G,
            fat_per_100g=COARSE_FAT_PER_100G,
            assumptions=(_DETERMINISTIC_PRIOR_ASSUMPTION, serving_label),
            basis=FactBasis.PER_100G.value,
            field_provenance={
                "calories": "estimated",
                "protein_g": "estimated",
                "carbs_g": "estimated",
                "fat_g": "estimated",
            },
        )

    def _record(
        self,
        context: EstimationContext,
        index: int | None,
        *,
        via_primary: bool,
        budget_free: bool,
    ) -> None:
        """Trace the sanitized degrade outcome and its evidence-view record."""

        if budget_free:
            outcome = "degraded_budget_free"
        elif via_primary:
            outcome = "degraded_primary"
        else:
            outcome = "degraded_deterministic"
        context.record_decision(
            self.step_name,
            "outcome",
            candidate_index=index,
            tier=MODEL_PRIOR_SOURCE,
            outcome=outcome,
        )
        add_evidence_record(context, tier=MODEL_PRIOR_SOURCE, outcome=outcome)


def _append_assumption(item: ResolvedFoodItem, assumption: str) -> ResolvedFoodItem:
    """Append the ``degraded:<reason>`` label to ``item`` without duplicating it."""

    if assumption in item.assumptions:
        return item
    return replace(item, assumptions=(*item.assumptions, assumption))
