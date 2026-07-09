"""Count-serving scaling helpers for named-food evidence (FTY-252).

Official/reference/model-prior facts may state nutrition per counted serving,
such as ``3 strips`` or ``5 crackers``. This module keeps the compatibility and
scaling policy small and deterministic so the official-source step can stay focused
on tier orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.estimator.food_serving import (
    CountServing,
    NutritionFacts,
    ScaledCountNutrition,
    ScaledNutrition,
    count_serving_multiplier,
    resolve_grams,
    scale_count_serving_facts,
    scale_facts,
)
from app.estimator.pipeline import CandidateDraft
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE, SearchedReferenceFacts
from app.schemas.official_source import FactBasis


@dataclass(frozen=True)
class ScaledCountReference:
    """A count-serving result plus the fact snapshot that should be persisted."""

    scaled: ScaledCountNutrition | ScaledNutrition
    snapshot: NutritionFacts
    basis: str
    assumptions: tuple[str, ...]


def has_explicit_amount(candidate: CandidateDraft) -> bool:
    """Whether the user supplied a positive structured amount."""

    return candidate.amount is not None and candidate.amount > 0


def can_scale_reference(candidate: CandidateDraft, reference: SearchedReferenceFacts) -> bool:
    """Filter count-serving results that cannot scale this candidate.

    Returning ``False`` lets the searched-result loop try the next evidence result
    before the caller falls through to the next tier. Non-count references keep the
    existing behavior: they are accepted and later serving math decides whether they
    are usable under the active clarify policy.
    """

    if reference.count_serving is None:
        return True
    has_compatible_count = (
        count_serving_multiplier(
            source_serving=reference.count_serving,
            consumed_unit=candidate.unit,
            consumed_amount=candidate.amount,
        )
        is not None
    )
    if has_compatible_count and (
        reference.basis == FactBasis.PER_SERVING.value or reference.serving_g is not None
    ):
        return True
    if _measured_grams(candidate) is not None and reference.per_100g_facts is not None:
        return True
    return not has_explicit_amount(candidate)


def scale_count_reference(
    *,
    candidate: CandidateDraft,
    reference: SearchedReferenceFacts,
    source_type: str,
    assumptions: tuple[str, ...],
) -> ScaledCountReference | None:
    """Scale a count-serving reference when the consumed count is compatible."""

    count_serving = reference.count_serving
    if count_serving is None:
        return None

    measured_grams = _measured_grams(candidate)
    if reference.basis == FactBasis.PER_SERVING.value:
        scaled = scale_count_serving_facts(
            reference.facts,
            source_serving=count_serving,
            consumed_unit=candidate.unit,
            consumed_amount=candidate.amount,
            serving_g=reference.serving_g,
        )
        if scaled is not None:
            return ScaledCountReference(
                scaled=scaled,
                snapshot=reference.facts,
                basis=FactBasis.PER_SERVING.value,
                assumptions=_model_prior_count_assumptions(source_type, assumptions, count_serving),
            )
        if measured_grams is not None and reference.per_100g_facts is not None:
            return ScaledCountReference(
                scaled=scale_facts(reference.per_100g_facts, measured_grams),
                snapshot=reference.per_100g_facts,
                basis=FactBasis.PER_100G.value,
                assumptions=assumptions,
            )
        return None

    grams = measured_grams
    used_count = False
    if grams is None:
        grams = _grams_from_count_reference(candidate, reference)
        used_count = grams is not None
    if grams is None or reference.per_100g_facts is None:
        return None

    scaled_assumptions = (
        _model_prior_count_assumptions(source_type, assumptions, count_serving)
        if used_count
        else assumptions
    )
    return ScaledCountReference(
        scaled=scale_facts(reference.per_100g_facts, grams),
        snapshot=reference.per_100g_facts,
        basis=FactBasis.PER_100G.value,
        assumptions=scaled_assumptions,
    )


def _measured_grams(candidate: CandidateDraft) -> float | None:
    """Resolve only measured mass/volume grams, never a count default serving."""

    return resolve_grams(
        unit=candidate.unit,
        amount=candidate.amount,
        quantity_text=candidate.quantity_text,
        default_serving_g=None,
    )


def _grams_from_count_reference(
    candidate: CandidateDraft, reference: SearchedReferenceFacts
) -> float | None:
    """Resolve grams from a per-100g reference's count-serving size relation."""

    if reference.count_serving is None or reference.serving_g is None:
        return None
    multiplier = count_serving_multiplier(
        source_serving=reference.count_serving,
        consumed_unit=candidate.unit,
        consumed_amount=candidate.amount,
    )
    if multiplier is None:
        return None
    return round(reference.serving_g * multiplier, 3)


def _model_prior_count_assumptions(
    source_type: str, assumptions: tuple[str, ...], count_serving: CountServing
) -> tuple[str, ...]:
    """Record structured count-serving assumptions only for model-prior estimates."""

    if source_type != MODEL_PRIOR_SOURCE_TYPE:
        return assumptions
    result = list(assumptions)
    extra = f"model_prior_count_serving:{count_serving.amount:g} {count_serving.unit}"
    if extra not in result:
        result.append(extra)
    return tuple(result)
