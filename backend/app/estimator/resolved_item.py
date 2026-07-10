"""The resolved-item builder shared by every :mod:`app.estimator.official_step`
evidence tier (official source, reference source, model prior).

Given validated :class:`~app.estimator.searched_reference.SearchedReferenceFacts`
and the candidate that was resolved, this module applies the deterministic FTY-044
serving math — as-logged total, count-serving scaling, or gram-based scaling, with
a rough default-serving fallback under estimate-first policy — and assembles the
:class:`~app.estimator.pipeline.ResolvedFoodItem` plus its content-fingerprinted
provenance. It is pure composition: no network egress, no model call.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.estimator.count_serving_resolution import has_explicit_amount, scale_count_reference
from app.estimator.evidence_utils import _content_hash
from app.estimator.food_serving import resolve_grams, scale_facts
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
)
from app.estimator.searched_reference import SearchedReferenceFacts
from app.schemas.official_source import FactBasis
from app.settings import EstimatorClarifyMode


def _build_item(  # noqa: PLR0913 - shared tier-agnostic builder seam
    context: EstimationContext,
    candidate: CandidateDraft,
    reference: SearchedReferenceFacts,
    *,
    source_type: str,
    source_ref: str,
    hash_key: str,
    base_assumptions: tuple[str, ...],
    step_name: str,
    clarify_mode: EstimatorClarifyMode,
    quantity_question: str,
    allow_unresolvable_fallthrough: bool = False,
    candidate_index: int | None = None,
) -> ResolvedFoodItem | None:
    """Apply deterministic serving math and build the resolved item + provenance.

    Shared by the official-source, reference-source, and model-prior tiers in
    :mod:`app.estimator.official_step`: each passes the facts it resolved plus the
    ``source_type``/``source_ref``/``hash_key`` that name where the facts came from.
    Returns ``None`` when the validated facts cannot be canonicalised to a usable
    basis, so the caller can try another source. Raises
    :class:`~app.estimator.pipeline.NeedsClarification` only when the active policy
    still allows asking after rough default/as-logged fallback has been considered.
    """

    def _record_serving(outcome: str) -> None:
        context.record_decision(
            step_name,
            "serving",
            candidate_index=candidate_index,
            tier=source_type,
            source_ref=source_ref,
            outcome=outcome,
        )

    assumptions = base_assumptions + reference.assumptions
    if reference.basis == FactBasis.AS_LOGGED.value:
        _record_serving("as_logged_total")
        content_hash = _content_hash(hash_key, reference.facts)
        return ResolvedFoodItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            grams=None,
            calories=round(reference.facts.calories, 1),
            protein_g=round(reference.facts.protein_g, 1),
            carbs_g=round(reference.facts.carbs_g, 1),
            fat_g=round(reference.facts.fat_g, 1),
            product_id=None,
            source_type=source_type,
            source_ref=source_ref,
            content_hash=content_hash,
            fetched_at=datetime.now(UTC),
            calories_per_100g=round(reference.facts.calories, 4),
            protein_per_100g=round(reference.facts.protein_g, 4),
            carbs_per_100g=round(reference.facts.carbs_g, 4),
            fat_per_100g=round(reference.facts.fat_g, 4),
            assumptions=_with_unique_assumptions(assumptions, ("as_logged_model_prior",)),
            basis=FactBasis.AS_LOGGED.value,
        )

    count_scaled = scale_count_reference(
        candidate=candidate,
        reference=reference,
        source_type=source_type,
        assumptions=assumptions,
    )
    if count_scaled is not None:
        _record_serving("count_serving_scaled")
        scaled = count_scaled.scaled
        snapshot = count_scaled.snapshot
        assumptions = count_scaled.assumptions
        content_hash = _content_hash(hash_key, reference.facts)
        return ResolvedFoodItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            grams=scaled.grams,
            calories=scaled.calories,
            protein_g=scaled.protein_g,
            carbs_g=scaled.carbs_g,
            fat_g=scaled.fat_g,
            product_id=None,
            source_type=source_type,
            source_ref=source_ref,
            content_hash=content_hash,
            fetched_at=datetime.now(UTC),
            calories_per_100g=round(snapshot.calories, 4),
            protein_per_100g=round(snapshot.protein_g, 4),
            carbs_per_100g=round(snapshot.carbs_g, 4),
            fat_per_100g=round(snapshot.fat_g, 4),
            assumptions=assumptions,
            basis=count_scaled.basis,
        )

    if reference.count_serving is not None and has_explicit_amount(candidate):
        _record_serving("rejected_incompatible_serving")
        return None

    grams = resolve_grams(
        unit=candidate.unit,
        amount=candidate.amount,
        quantity_text=candidate.quantity_text,
        default_serving_g=(
            None if reference.count_serving is not None else reference.default_serving_g
        ),
    )
    if grams is None:
        grams = _default_serving_grams(candidate, reference.default_serving_g)
        if grams is None:
            if allow_unresolvable_fallthrough:
                return None
            _record_clarified_quantity(context, step_name, candidate_index)
            context.clarification_questions = [ClarificationDraft(text=quantity_question)]
            raise NeedsClarification("unresolvable_quantity")
        if not _allows_default_serving_estimate(clarify_mode, candidate):
            _record_clarified_quantity(context, step_name, candidate_index)
            context.clarification_questions = [ClarificationDraft(text=quantity_question)]
            raise NeedsClarification("unresolvable_quantity")
        _record_serving("default_serving_estimated")
        assumptions = _with_unique_assumptions(
            assumptions,
            (
                f"clarify_mode:{clarify_mode}",
                "estimated_default_serving",
            ),
        )

    per_100g = reference.per_100g_facts
    if per_100g is None:
        # A per-serving count reference with no gram serving size has no per-100g
        # basis, so measured grams cannot scale it; fall through to the next tier
        # rather than scale raw per-serving facts as a density.
        return None
    scaled = scale_facts(per_100g, grams)
    content_hash = _content_hash(hash_key, per_100g)

    return ResolvedFoodItem(
        name=candidate.name,
        quantity_text=candidate.quantity_text,
        unit=candidate.unit,
        amount=candidate.amount,
        grams=scaled.grams,
        calories=scaled.calories,
        protein_g=scaled.protein_g,
        carbs_g=scaled.carbs_g,
        fat_g=scaled.fat_g,
        product_id=None,
        source_type=source_type,
        source_ref=source_ref,
        content_hash=content_hash,
        fetched_at=datetime.now(UTC),
        calories_per_100g=round(per_100g.calories, 4),
        protein_per_100g=round(per_100g.protein_g, 4),
        carbs_per_100g=round(per_100g.carbs_g, 4),
        fat_per_100g=round(per_100g.fat_g, 4),
        assumptions=assumptions,
    )


def _record_clarified_quantity(
    context: EstimationContext, step_name: str, candidate_index: int | None
) -> None:
    """Trace that the candidate's terminal route is a quantity clarification."""

    context.record_decision(
        step_name, "outcome", candidate_index=candidate_index, outcome="clarified_quantity"
    )


def _allows_default_serving_estimate(
    clarify_mode: EstimatorClarifyMode, candidate: CandidateDraft
) -> bool:
    """Whether serving-math gaps can use a rough default serving before asking."""

    if clarify_mode == "estimate_first":
        return True
    if clarify_mode == "balanced":
        return candidate.amount is not None and candidate.amount > 0
    return False


def _default_serving_grams(
    candidate: CandidateDraft, default_serving_g: float | None
) -> float | None:
    """Fallback consumed grams from a source/model default serving.

    Used only for rough estimate-first paths after deterministic serving math fails:
    a positive structured count scales the default serving, while an amountless
    recognized identity assumes one default serving. The assumption is recorded on the
    evidence row by the caller.
    """

    if default_serving_g is None or default_serving_g <= 0:
        return None
    servings = candidate.amount if candidate.amount is not None and candidate.amount > 0 else 1.0
    return round(servings * default_serving_g, 3)


def _with_unique_assumptions(
    assumptions: tuple[str, ...], extras: tuple[str, ...]
) -> tuple[str, ...]:
    """Append content-free assumptions without duplicating existing labels."""

    result = list(assumptions)
    for extra in extras:
        if extra not in result:
            result.append(extra)
    return tuple(result)
