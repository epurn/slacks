"""The gated model-prior tier for :mod:`app.estimator.official_step`.

The last-resort evidence tier, tried only after the official-source and
reference-source tiers are unavailable or return nothing confident: it estimates
the named food from the sanitized item identity alone (no page evidence), records
the result with ``source_type = model_prior`` and explicit ``assumptions`` naming
why the earlier tiers were not used — never a silent guess
(``docs/contracts/evidence-retrieval.md`` Fallback Rule) — and hands the estimate
to the shared :func:`~app.estimator.resolved_item._build_item` builder. A model
that cannot estimate the item routes to ``needs_clarification``.
"""

from __future__ import annotations

from app.estimator.evidence_utils import _record_source_ref
from app.estimator.identity_sanitizer import sanitized_identity
from app.estimator.interpretation_tools import add_evidence_record, evidence_status_labels
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
)
from app.estimator.resolved_item import _build_item
from app.estimator.searched_reference import (
    _LOGGED_MODEL_PRIOR_PROMPT,
    MODEL_PRIOR_SOURCE,
    MODEL_PRIOR_SOURCE_TYPE,
    _identity_query,
    searched_reference_from_estimate,
)
from app.llm.base import Provider
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.schemas.official_source import EstimateDisposition, NamedFoodEstimate
from app.settings import EstimatorClarifyMode


def _estimate_model_prior(
    provider: Provider, candidate: CandidateDraft, *, evidence_labels: tuple[str, ...]
) -> tuple[NamedFoodEstimate | None, str | None]:
    """Ask for a rough estimate from sanitized identity + structured portion."""

    identity = _sanitized_model_identity(candidate)
    if not identity:
        return None, "unusable_facts"
    prompt = _LOGGED_MODEL_PRIOR_PROMPT.format(
        identity=identity,
        portion=_structured_portion_for_prompt(candidate),
    )
    prompt += _model_prior_evidence_block(evidence_labels)
    try:
        return provider.structured_completion(prompt, NamedFoodEstimate), None
    except (
        StructuredOutputValidationError,
        LLMResponseError,
        LLMConfigurationError,
        LLMTransientError,
    ):
        return None, "provider_error"


def _model_prior(  # noqa: PLR0913 - shared last-resort tier seam
    context: EstimationContext,
    candidate: CandidateDraft,
    reasons: list[str],
    candidate_index: int | None,
    *,
    step_name: str,
    provider: Provider,
    model_prior_confidence_floor: float,
    clarify_mode: EstimatorClarifyMode,
    unknown_food_question: str,
    quantity_question: str,
) -> ResolvedFoodItem:
    """Estimate the named food from model prior, recorded with an explicit status.

    The gated last resort: the entry carries ``source_type = model_prior`` and an
    ``assumptions`` reason naming, per evidence tier, why official/reference
    evidence was not used, so the source status is surfaced and the entry stays
    user-editable. A model that cannot estimate the item (``unresolved`` / no
    facts) routes to ``needs_clarification`` — still never a silent guess.
    """

    def _record_prior(outcome: str) -> None:
        context.record_decision(
            step_name,
            "source",
            candidate_index=candidate_index,
            tier=MODEL_PRIOR_SOURCE,
            outcome=outcome,
        )
        add_evidence_record(context, tier=MODEL_PRIOR_SOURCE, outcome=outcome)

    def _clarify(reason: str, *, legacy_outcome: str) -> NeedsClarification:
        _record_prior(legacy_outcome)
        _record_prior(reason)
        context.record_decision(
            step_name,
            "outcome",
            candidate_index=candidate_index,
            outcome="clarified_unknown_food",
        )
        context.clarification_questions = [ClarificationDraft(text=unknown_food_question)]
        return NeedsClarification(legacy_outcome)

    _record_source_ref(context, MODEL_PRIOR_SOURCE)
    reason = "; ".join([*reasons, "estimated from model prior"])
    estimate, failure = _estimate_model_prior(
        provider, candidate, evidence_labels=evidence_status_labels(context)
    )
    if failure is not None:
        raise _clarify(failure, legacy_outcome="model_prior_unavailable")
    if estimate is None or estimate.disposition is not EstimateDisposition.RESOLVED:
        raise _clarify("non_resolved_disposition", legacy_outcome="model_prior_unavailable")
    if estimate.confidence < model_prior_confidence_floor:
        raise _clarify("low_confidence", legacy_outcome="model_prior_unavailable")

    reference = searched_reference_from_estimate(
        estimate,
        source_ref=MODEL_PRIOR_SOURCE,
        hash_key=_identity_query(candidate),
    )
    if reference is None:
        raise _clarify("unusable_facts", legacy_outcome="model_prior_unusable")

    item = _build_item(
        context,
        candidate,
        reference,
        source_type=MODEL_PRIOR_SOURCE_TYPE,
        source_ref=MODEL_PRIOR_SOURCE,
        hash_key=_identity_query(candidate),
        base_assumptions=(reason,),
        step_name=step_name,
        clarify_mode=clarify_mode,
        quantity_question=quantity_question,
        allow_unresolvable_fallthrough=clarify_mode == "estimate_first",
        candidate_index=candidate_index,
    )
    if item is None:
        # The estimate was unusable (e.g. per-serving facts with no gram serving
        # size); ask rather than guess the portion.
        raise _clarify("unusable_facts", legacy_outcome="model_prior_unusable")
    _record_prior("accepted")
    return item


def _sanitized_model_identity(candidate: CandidateDraft) -> str:
    """Identity sent to model-prior: bounded food tokens only, never diary text."""

    return sanitized_identity(_identity_query(candidate))


def _structured_portion_for_prompt(candidate: CandidateDraft) -> str:
    """Bounded structured portion summary for model-prior, excluding raw text."""

    if candidate.amount is not None and candidate.amount > 0:
        unit = sanitized_identity(candidate.unit or "") or "count"
        return f"amount={candidate.amount:g}; unit={unit}"
    return "amount=unspecified; use one typical serving only if needed"


def _model_prior_evidence_block(evidence_labels: tuple[str, ...]) -> str:
    """Append sanitized evidence-view lines to the model-prior tool prompt."""

    if not evidence_labels:
        return "\nEvidence status: none recorded."
    lines = "\n".join(f"- {label}" for label in evidence_labels)
    return (
        "\nEvidence gathered before this rough-estimate tool, as bounded sanitized "
        "source/status records (no raw page, snippet, query, or diary text):\n"
        f"{lines}"
    )
