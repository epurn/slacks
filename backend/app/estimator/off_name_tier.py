"""Open Food Facts name-search ``product_database`` tier (FTY-369, extracted FTY-392).

The rank-3 ``product_database`` evidence tier for a barcode-less branded product,
lifted verbatim out of :mod:`app.estimator.official_step` so that step reads as a
pure tier orchestrator. :class:`~app.estimator.official_step.OfficialSourceResolveStep`
calls :func:`_try_off_name_search` between its official-source (rank 2) and
reference (rank 5) tiers, passing the same candidate/context and consuming the same
result. Behaviour, source refs (``open_food_facts:<code>``), hash keys,
decision-trace labels, the brand/product-compatibility gate, and the FTY-368
resolved-value plausibility gate are byte-for-byte identical to the pre-extraction
inline tier.

Security boundary: this module opens **no** network egress of its own. Every OFF
name query egresses only through the injected, name-keyed
:class:`~app.estimator.food_resolvers.OffNameResolver`, which carries the FTY-369
``sanitize_query`` chokepoint, the OFF host allowlist, and the FTY-078/081 SSRF
hardening — identity-only, hard-capped by ``MAX_IDENTITY_VARIANTS``. The moved code
adds no new socket and persists only the extracted facts, the
``open_food_facts:...`` ref, and a content hash — never raw OFF payloads or raw
queries.
"""

from __future__ import annotations

from app.estimator.branded_routing import (
    identity_variants,
    is_evidence_brand_compatible,
    product_hint,
)
from app.estimator.evidence_utils import _record_source_ref
from app.estimator.food_resolvers import OffNameResolver, _ResolvedProduct
from app.estimator.food_serving import NutritionFacts
from app.estimator.interpretation_tools import add_evidence_record
from app.estimator.off import (
    OFF_SOURCE,
    OFF_SOURCE_TYPE,
    OffResponseError,
    OffTransientError,
)
from app.estimator.pipeline import CandidateDraft, EstimationContext, ResolvedFoodItem
from app.estimator.resolved_item import _build_item
from app.estimator.resolved_plausibility import (
    IMPLAUSIBLE_RESOLVED_TOTAL_OUTCOME,
    check_resolved_food_total,
)
from app.estimator.searched_reference import SearchedReferenceFacts
from app.schemas.official_source import FactBasis
from app.settings import EstimatorClarifyMode


def _try_off_name_search(
    context: EstimationContext,
    candidate: CandidateDraft,
    reasons: list[str],
    index: int | None,
    *,
    resolver: OffNameResolver | None,
    step_name: str,
    clarify_mode: EstimatorClarifyMode,
    quantity_question: str,
) -> ResolvedFoodItem | None:
    """Consult Open Food Facts **by name** for a branded product (FTY-369).

    The ``product_database`` tier for a barcode-less branded item: it searches the
    same bounded, sanitized identity-query variants the web tiers use
    (:func:`identity_variants`), and each OFF candidate must pass the same
    brand/product-compatibility gate FDC branded routing applies
    (:func:`is_evidence_brand_compatible`) — a foreign product (different brand or
    item) is rejected and the chain continues. Returns ``None`` (→ reference source)
    when OFF is unavailable, not applicable (no brand/hint identity), misses, or
    errors, appending a sanitized reason. An OFF transport/response error degrades
    to the next tier rather than failing the run — infrastructure trouble never
    rejects an entry.
    """

    gate_brand = _off_gate_brand(candidate)
    if resolver is None or not resolver.enabled:
        reasons.append("product_database disabled")
        _record_off(context, index, "disabled", step_name=step_name)
        return None
    if gate_brand is None:
        # A generic food (no brand identity) has no packaged product to match by
        # name; product_database does not apply to it (rank-3 is branded/hinted).
        reasons.append("product_database not applicable (no brand identity)")
        _record_off(context, index, "not_applicable_by_session", step_name=step_name)
        return None

    _record_source_ref(context, OFF_SOURCE)

    def _accept(evidence_name: str) -> bool:
        return is_evidence_brand_compatible(evidence_name, name=candidate.name, brand=gate_brand)

    reason_count = len(reasons)
    for query in identity_variants(candidate):
        try:
            resolved = resolver.resolve_compatible(query, accept=_accept)
        except OffTransientError:
            reasons.append("product_database transient error")
            _record_off(context, index, "off_transient_error", step_name=step_name)
            return None
        except OffResponseError:
            reasons.append("product_database response error")
            _record_off(context, index, "off_response_error", step_name=step_name)
            return None
        if resolved is None:
            continue
        item = _build_off_item(
            context,
            candidate,
            resolved,
            index,
            reasons,
            step_name=step_name,
            clarify_mode=clarify_mode,
            quantity_question=quantity_question,
        )
        if item is not None:
            return item
    if len(reasons) == reason_count:
        reasons.append("product_database returned no confident match")
    _record_off(context, index, "miss", step_name=step_name)
    return None


def _build_off_item(
    context: EstimationContext,
    candidate: CandidateDraft,
    resolved: _ResolvedProduct,
    index: int | None,
    reasons: list[str],
    *,
    step_name: str,
    clarify_mode: EstimatorClarifyMode,
    quantity_question: str,
) -> ResolvedFoodItem | None:
    """Cost a cached OFF name hit with the shared serving math + plausibility gate.

    The cached product's canonical per-100g facts flow through the same
    :func:`_build_item` serving math the web tiers use (``product_database``
    provenance, ``source_ref = open_food_facts:<code>``); the resolved total then
    clears the FTY-368 resolved-value plausibility gate exactly as the exact and
    web-evidence paths do. Returns ``None`` (→ next variant/tier) on an unscalable
    quantity or an implausible total.
    """

    product = resolved.product
    per_100g = NutritionFacts(
        calories=product.calories_per_100g,
        protein_g=product.protein_per_100g,
        carbs_g=product.carbs_per_100g,
        fat_g=product.fat_per_100g,
    )
    reference = SearchedReferenceFacts(
        facts=per_100g,
        source_ref=product.source_ref,
        hash_key=product.source_ref,
        default_serving_g=product.default_serving_g,
        assumptions=(),
        basis=FactBasis.PER_100G.value,
        per_100g_facts=per_100g,
        product_name=product.description,
    )
    item = _build_item(
        context,
        candidate,
        reference,
        source_type=OFF_SOURCE_TYPE,
        source_ref=product.source_ref,
        hash_key=product.source_ref,
        base_assumptions=(),
        step_name=step_name,
        clarify_mode=clarify_mode,
        quantity_question=quantity_question,
        allow_unresolvable_fallthrough=clarify_mode == "estimate_first",
        candidate_index=index,
    )
    if item is None:
        unscalable = "product_database returned unscalable serving math"
        if unscalable not in reasons:
            reasons.append(unscalable)
        _record_off(
            context,
            index,
            "rejected_unresolvable_quantity",
            product.source_ref,
            step_name=step_name,
        )
        return None
    verdict = check_resolved_food_total(
        name=candidate.name,
        unit=candidate.unit,
        amount=candidate.amount,
        quantity_text=candidate.quantity_text,
        grams=item.grams,
        calories=item.calories,
    )
    if not verdict.plausible:
        if index is not None and verdict.reason is not None:
            context.plausibility_refit_reasons[index] = verdict.reason
        implausible = "product_database returned implausible resolved total"
        if implausible not in reasons:
            reasons.append(implausible)
        _record_off(
            context,
            index,
            IMPLAUSIBLE_RESOLVED_TOTAL_OUTCOME,
            product.source_ref,
            step_name=step_name,
        )
        return None
    _record_source_ref(context, OFF_SOURCE)
    _record_off(context, index, "accepted", product.source_ref, step_name=step_name)
    return item


def _record_off(
    context: EstimationContext,
    index: int | None,
    outcome: str,
    source_ref: str | None = None,
    *,
    step_name: str,
) -> None:
    """Record one sanitized OFF-name-search decision + evidence-view entry."""

    context.record_decision(
        step_name,
        "source",
        candidate_index=index,
        tier=OFF_SOURCE_TYPE,
        source_ref=source_ref,
        outcome=outcome,
    )
    add_evidence_record(context, tier=OFF_SOURCE_TYPE, outcome=outcome, source_ref=source_ref)


def _has_brand(candidate: CandidateDraft) -> bool:
    """Whether ``candidate`` names a branded product (has a non-blank ``brand``)."""

    return bool(candidate.brand and candidate.brand.strip())


def _off_gate_brand(candidate: CandidateDraft) -> str | None:
    """The brand identity OFF name search gates its candidates against (FTY-369).

    A packaged ``product_database`` match must be gated to a **branded/hinted**
    identity so a foreign product is rejected: the parsed ``brand`` when present, else
    the stranded product hint the parser left in the quantity phrase
    (:func:`product_hint`). ``None`` for a plain generic food (no brand, no hint), which
    has no packaged product to match by name — the tier does not apply to it.
    """

    if _has_brand(candidate):
        return candidate.brand
    return product_hint(candidate.quantity_text) or None
