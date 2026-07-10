"""Adapters that let evidence tiers consult the interpretation session (FTY-326).

The session owns the model's revisable hypothesis, while deterministic resolver
steps own source gates, math, budgets, and persistence.  This module is the
small bridge between those worlds: tiers can record sanitized evidence labels on
the session ledger, read the current food hypothesis as ordinary
``CandidateDraft`` values, and spend the session's one bounded evidence-driven
re-interpretation pass before falling to model-prior.
"""

from __future__ import annotations

from app.enums import CandidateType
from app.estimator.interpretation import EvidenceRecord
from app.estimator.pipeline import CandidateDraft, EstimationContext, StepError, StepFailed
from app.schemas.parse import ParsedCandidate

INTERPRETATION_TIER = "interpretation_session"


def add_evidence_record(  # noqa: PLR0913 - mirrors the bounded evidence-view field set.
    context: EstimationContext,
    *,
    tier: str,
    outcome: object,
    source_ref: object | None = None,
    decision: object | None = None,
    query_variant: object | None = None,
    search_status: object | None = None,
    result_count: object | None = None,
    source_desc: object | None = None,
    surface: object | None = None,
) -> None:
    """Append a bounded, sanitized evidence record to the session ledger.

    The ``EvidenceRecord`` renders through the decision-trace sanitizers at the
    provider-egress seam, so callers may pass the same bounded labels/source refs
    they already send to ``record_decision``.  ``source_desc`` is for a bounded
    source-stated identity descriptor (for example, a global database description
    or schema-extracted product name) when the session needs the evidence surface
    that a compatibility/serving decision saw. Raw page/snippet/query/user text
    must still never be passed here.
    """

    session = context.interpretation_session
    if session is None or outcome is None:
        return
    session.add_evidence(
        EvidenceRecord(
            tier=str(tier),
            outcome=str(outcome),
            source_ref=None if source_ref is None else str(source_ref),
            decision=None if decision is None else str(decision),
            query_variant=_coerce_evidence_count(query_variant),
            search_status=None if search_status is None else str(search_status),
            result_count=_coerce_evidence_count(result_count),
            source_desc=None if source_desc is None else str(source_desc),
            surface=None if surface is None else str(surface),
        )
    )


def current_food_candidate(
    context: EstimationContext,
    candidate: CandidateDraft,
    candidate_index: int | None,
) -> CandidateDraft:
    """Return the session's current food draft for ``candidate_index`` if present."""

    drafts = _session_food_drafts(context)
    for draft in drafts:
        if draft == candidate:
            return draft
    for draft in drafts:
        if _same_food_identity(draft, candidate):
            return draft
    # Food candidates may have been claimed/removed by an earlier tier such as
    # user_text, so index is safe only while the session/context food lists still
    # have the same shape.
    if (
        len(drafts) == len(context.food_candidates)
        and candidate_index is not None
        and 0 <= candidate_index < len(drafts)
    ):
        return drafts[candidate_index]
    return candidate


def evidence_status_labels(context: EstimationContext) -> tuple[str, ...]:
    """Sanitized evidence-ledger labels for provider prompts."""

    session = context.interpretation_session
    if session is None:
        return ()
    return tuple(record.as_label() for record in session.evidence_ledger)


def reinterpret_food_candidate(
    context: EstimationContext,
    candidate: CandidateDraft,
    candidate_index: int | None,
    *,
    step_name: str,
    trigger_tier: str,
) -> CandidateDraft | None:
    """Spend the session's bounded re-interpretation pass and return a revised draft.

    Evidence-tier re-interpretation is advisory to the resolver: if the session has
    no budget, the provider fails, or the model keeps the same food hypothesis, the
    caller continues to model-prior with the current candidate.  When a revised food
    candidate is returned, this helper updates ``context.food_candidates`` at the
    same food index so downstream trace attribution and persistence use the revised
    hypothesis.
    """

    session = context.interpretation_session
    if session is None:
        return None

    try:
        result = session.reinterpret(context)
    except (StepError, StepFailed) as exc:
        outcome = f"requery_{_step_signal_reason(exc)}"
        _record_requery_decision(
            context,
            step_name=step_name,
            candidate_index=candidate_index,
            outcome=outcome,
            trigger_tier=trigger_tier,
        )
        return None

    if result is None:
        _record_requery_decision(
            context,
            step_name=step_name,
            candidate_index=candidate_index,
            outcome="requery_truncated",
            trigger_tier=trigger_tier,
        )
        return None

    revised = current_food_candidate(context, candidate, candidate_index)
    if revised == candidate:
        _record_requery_decision(
            context,
            step_name=step_name,
            candidate_index=candidate_index,
            outcome="requery_identity_unchanged",
            trigger_tier=trigger_tier,
        )
        return None

    if candidate_index is not None and 0 <= candidate_index < len(context.food_candidates):
        context.food_candidates[candidate_index] = revised

    _record_requery_decision(
        context,
        step_name=step_name,
        candidate_index=candidate_index,
        outcome="requery_revised_identity",
        trigger_tier=trigger_tier,
    )
    return revised


def _record_requery_decision(
    context: EstimationContext,
    *,
    step_name: str,
    candidate_index: int | None,
    outcome: str,
    trigger_tier: str,
) -> None:
    context.record_decision(
        step_name,
        "source",
        candidate_index=candidate_index,
        tier=INTERPRETATION_TIER,
        outcome=outcome,
    )
    add_evidence_record(
        context,
        tier=INTERPRETATION_TIER,
        outcome=outcome,
        source_ref=trigger_tier,
    )


def _session_food_drafts(context: EstimationContext) -> tuple[CandidateDraft, ...]:
    session = context.interpretation_session
    if session is None:
        return ()
    try:
        items = session.result.items
    except RuntimeError:
        return ()
    return tuple(_to_draft(item) for item in items if item.type is CandidateType.FOOD)


def _to_draft(item: ParsedCandidate) -> CandidateDraft:
    return CandidateDraft(
        name=item.name,
        quantity_text=item.quantity_text,
        unit=item.unit,
        amount=item.amount,
        barcode=item.barcode,
        brand=item.brand,
        stated_calories=item.stated_calories,
        stated_protein_g=item.stated_protein_g,
        stated_carbs_g=item.stated_carbs_g,
        stated_fat_g=item.stated_fat_g,
    )


def _same_food_identity(left: CandidateDraft, right: CandidateDraft) -> bool:
    return _normalise(left.name) == _normalise(right.name)


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def _step_signal_reason(exc: StepError | StepFailed) -> str:
    if isinstance(exc, StepFailed):
        return exc.reason
    return exc.message


def _coerce_evidence_count(value: object | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None
