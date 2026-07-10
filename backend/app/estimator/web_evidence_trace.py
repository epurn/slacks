"""Traced seams for the web-evidence resolution chain (FTY-255).

The official/reference-source step (:mod:`app.estimator.official_step`) resolves
candidates through the shared search → fetch → extract chain
(:mod:`app.estimator.searched_reference`). This module owns the small adapters
that thread the sanitized run decision trace through that chain without the
orchestration having to know how entries are built:

- :func:`decision_recorder` — a per-query-variant hook bound to
  :meth:`~app.estimator.pipeline.EstimationContext.record_decision`, so every
  value still passes the :mod:`app.estimator.decision_trace` sanitizers;
- :func:`traced_fetch` — wraps a raising hardened fetcher into the chain's
  non-fatal ``str | None`` seam while recording a content-free outcome label
  (``fetch_403``, ``fetch_policy_blocked``, …) per failure;
- :func:`acceptance_gate` — the FTY-252/253 evidence gates, recording which
  check rejected a result;
- :func:`trace_candidate_index` — the candidate's stable index in the parsed
  food-candidate list, matching the food step's entries.

Nothing here egresses, stores, or logs content: URLs enter the trace only
through the sanitizer, and every label is a fixed vocabulary string.
"""

from __future__ import annotations

from collections.abc import Callable

from app.estimator.branded_routing import is_evidence_brand_compatible
from app.estimator.count_serving_resolution import can_scale_reference
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.interpretation_tools import add_evidence_record
from app.estimator.pipeline import CandidateDraft, EstimationContext
from app.estimator.searched_reference import (
    AcceptSearchedReference,
    ObserveSearchDecision,
    SearchedReferenceFacts,
)

#: Bounds a traced HTTP status label to the legal status range; anything else is
#: reported by error class instead of echoing an arbitrary integer.
_MIN_HTTP_STATUS = 100
_MAX_HTTP_STATUS = 599


def trace_candidate_index(context: EstimationContext, candidate: CandidateDraft) -> int | None:
    """The candidate's position in the parsed food-candidate list, for the trace.

    Matches the ``candidate_index`` the food step recorded for the same candidate.
    Drafts are frozen *value* objects — duplicate parsed candidates compare equal —
    so identity is checked first: the pipeline threads the parse step's own draft
    objects through ``pending_official_candidates``, and an identity match keeps a
    duplicate's decisions attributed to its own position instead of the first
    equal one. Equality is the fallback for hand-built pipelines that pass an
    equal copy; ``None`` when the candidate is not in the parse list at all.
    """

    for position, draft in enumerate(context.food_candidates):
        if draft is candidate:
            return position
    try:
        return context.food_candidates.index(candidate)
    except ValueError:
        return None


def decision_recorder(
    step_name: str,
    context: EstimationContext,
    *,
    candidate_index: int | None,
    tier: str,
    query_variant: int,
) -> ObserveSearchDecision:
    """A per-query-variant sanitized decision hook bound to the run trace."""

    def _note(*, decision: str = "source", **fields: object) -> None:
        context.record_decision(
            step_name,
            decision,
            candidate_index=candidate_index,
            tier=tier,
            query_variant=query_variant,
            **fields,
        )
        add_evidence_record(
            context,
            tier=tier,
            outcome=fields.get("outcome") or fields.get("search_status") or decision,
            source_ref=fields.get("source_ref"),
        )

    return _note


def acceptance_gate(
    candidate: CandidateDraft, note: ObserveSearchDecision
) -> AcceptSearchedReference:
    """The FTY-252/253 evidence gates, recording which check rejected a result.

    Same short-circuit order as before: quantity-costability first, then
    brand/product compatibility. Each rejection is traced with a content-free
    outcome label plus the evidence result's bounded source ref (FTY-255).
    """

    def _accept(found: SearchedReferenceFacts) -> bool:
        if not can_scale_reference(candidate, found):
            note(
                decision="extract",
                source_ref=found.source_ref,
                outcome="rejected_incompatible_serving",
            )
            return False
        if not is_evidence_brand_compatible(
            found.product_name, name=candidate.name, brand=candidate.brand
        ):
            note(
                decision="extract",
                source_ref=found.source_ref,
                outcome="rejected_brand_mismatch",
            )
            return False
        return True

    return _accept


def traced_fetch(
    fetch_raw: Callable[[str], str], source_type: str, note: ObserveSearchDecision
) -> Callable[[str], str | None]:
    """Wrap a raising hardened fetcher into the chain's non-fatal ``str | None`` seam.

    A policy/transport/response failure on one page is not fatal — the resolver
    tries the next candidate URL or falls through to the next tier — but each
    failure is now traced with a content-free outcome label (``fetch_403``,
    ``fetch_policy_blocked``, …) so an audit can see exactly why a page produced
    nothing (FTY-255). The fetcher's errors are content-free; nothing about the
    body is surfaced, and the URL enters the trace only through the sanitizer.
    """

    def _fetch(url: str) -> str | None:
        try:
            return fetch_raw(url)
        except (FetchPolicyError, FetchTransientError, FetchResponseError) as exc:
            note(
                decision="fetch",
                source_ref=f"{source_type}:{url}",
                outcome=_fetch_error_outcome(exc),
            )
            return None

    return _fetch


def _fetch_error_outcome(exc: Exception) -> str:
    """Map a typed hardened-fetch error to a content-free trace outcome label."""

    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and _MIN_HTTP_STATUS <= status <= _MAX_HTTP_STATUS:
        return f"fetch_{status}"
    if isinstance(exc, FetchPolicyError):
        return "fetch_policy_blocked"
    if isinstance(exc, FetchTransientError):
        return "fetch_transient_error"
    return "fetch_response_error"
