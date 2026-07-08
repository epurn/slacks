"""The official/reference-source resolution step (FTY-062, FTY-166).

The last-resort food-resolution step before model-prior. It picks up the food
candidates the upstream USDA/OFF food step (FTY-044/060) could not resolve —
branded restaurant/manufacturer products and detail-rich generic foods (FTY-167) —
and costs them from web evidence, deterministically, in explicit tier order:

1. **Official source** (FTY-062, branded candidates only): search the sanitized
   item identity (name + brand, no personal context) through the pluggable search
   adapter (FTY-079), fetch each candidate result URL through the hardened,
   allowlisted official fetcher (FTY-078), and transcribe the facts the page
   states.
2. **Reference source** (FTY-166, branded *and* detail-rich generic candidates):
   when official sources miss (or do not apply — a generic food has no brand
   page), search the sanitized item identity **plus a fixed nutrition intent**
   for public nutrition reference evidence, fetch the bounded result page through
   the searched-result hardened fetcher
   (:mod:`app.estimator.reference_fetch` — HTTPS-only, public-IP-only, no
   redirects, bounded, active content stripped), and transcribe the facts the
   page states.
3. **Model prior** (gated last resort): only after official/reference evidence
   is unavailable or returns no confident match, estimate from the item identity
   alone, recorded with ``source_type = model_prior`` and explicit ``assumptions``
   naming why each evidence tier was not used — never a silent guess
   (``docs/contracts/evidence-retrieval.md`` Fallback Rule).

In every tier the page text is *untrusted data*: the LLM only transcribes the
facts the page states into the strict
:class:`~app.schemas.official_source.NamedFoodEstimate` schema, the reply is
trusted only after it validates, and the FTY-044 deterministic serving math — the
model never supplies the stored numbers — recomputes canonical calories/macros.

On a confident match the candidate becomes a ``resolved`` ``derived_food_items``
row plus a user-owned ``evidence_sources`` row whose ``source_ref`` is
``official_source:<url>`` or ``reference_source:<url>`` (the URL only — never the
raw page).

Security boundary: this step issues **no** network egress of its own. All search
goes through the FTY-079 adapter and all fetches through the injected hardened
fetchers (FTY-078 official / FTY-166 searched-result); both are injected seams, so
the SSRF/egress and query-sanitization guarantees live upstream and this
orchestration cannot bypass them. Fetched/searched/extracted/LLM content is
untrusted until it validates against the schema and is recomputed by the
calculators; raw pages are never stored.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.estimator.evidence_utils import _content_hash, _record_source_ref
from app.estimator.food_serving import resolve_grams, scale_facts
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.official_fetch import OfficialFetchSettings, fetch_official_source
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
)
from app.estimator.reference_fetch import ReferenceFetchSettings, fetch_searched_result
from app.estimator.search import (
    OFFICIAL_SOURCE,
    OFFICIAL_SOURCE_TYPE,
    SearchProvider,
)
from app.estimator.searched_reference import (
    _MODEL_PRIOR_PROMPT,
    _OFFICIAL_PAGE_KIND,
    _REFERENCE_PAGE_KIND,
    MODEL_PRIOR_SOURCE,
    MODEL_PRIOR_SOURCE_TYPE,
    REFERENCE_SEARCH_INTENT,
    REFERENCE_SOURCE,
    REFERENCE_SOURCE_TYPE,
    SearchedReferenceFacts,
    _identity_query,
    _to_per_100g,
    searched_reference_per_100g,
)
from app.llm.base import Provider
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.schemas.official_source import (
    EstimateDisposition,
    NamedFoodEstimate,
)

__all__ = [
    "MODEL_PRIOR_SOURCE",
    "MODEL_PRIOR_SOURCE_TYPE",
    "REFERENCE_SOURCE",
    "REFERENCE_SOURCE_TYPE",
    "OfficialSourceResolveStep",
]

#: Fixed, sanitized clarification questions used in place of any raw text, so a
#: ``needs_clarification`` outcome always carries a question for the answer flow.
QUANTITY_QUESTION = "How much did you have (for example, in grams, millilitres, or servings)?"
UNKNOWN_FOOD_QUESTION = "Which food was that? We couldn't find a nutrition match."

#: The injectable hardened-fetch seams: each takes a result URL + its egress settings
#: and returns sanitized inert text (FTY-078 official / FTY-166 searched-result).
#: Defaults are the real fetchers; tests inject network-free fakes, proving this step
#: never egresses directly.
FetchOfficial = Callable[[str, OfficialFetchSettings], str]
FetchReference = Callable[[str, ReferenceFetchSettings], str]


@dataclass(frozen=True)
class OfficialSourceResolveStep:
    """Resolve USDA/OFF-unresolved food candidates from web evidence, tier by tier.

    Consumes :attr:`EstimationContext.pending_official_candidates` (the branded and
    detail-rich generic misses the food step deferred), resolving each via official
    search + fetch (branded only), then reference-source search + fetch, then — when
    no evidence tier is available or finds anything confident — a model-prior
    estimate carrying an explicit source status. All egress flows through the
    injected ``search_provider`` (FTY-079) and the injected fetchers (``fetch_fn``,
    FTY-078; ``reference_fetch_fn``, FTY-166); the step itself opens no socket.
    """

    provider: Provider
    search_provider: SearchProvider
    fetch_settings: OfficialFetchSettings
    reference_fetch_settings: ReferenceFetchSettings
    fetch_fn: FetchOfficial = fetch_official_source
    reference_fetch_fn: FetchReference = fetch_searched_result
    name: str = "official_source_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        pending = list(context.pending_official_candidates)
        if not pending:
            # No candidate fell through from the food step; nothing to do.
            context.record_step(self.name, "skipped")
            return

        for candidate in pending:
            context.resolved_food_items.append(self._resolve(context, candidate))

        # These candidates are now resolved; clear so the worker does not also persist
        # them as unresolved leftovers.
        context.pending_official_candidates.clear()
        context.record_step(self.name, "ok")

    def _resolve(self, context: EstimationContext, candidate: CandidateDraft) -> ResolvedFoodItem:
        """Resolve one candidate: official source, else reference source, else model prior.

        A *branded* candidate is searched against official sources first (a named
        restaurant/manufacturer product has an authoritative page); a *generic*
        detail-rich candidate (FTY-167) has no official brand page, so its first
        evidence tier is the reference source. ``reasons`` accumulates, per tier, a
        short sanitized label for why the tier produced nothing, so a model-prior
        fallback always carries the explicit evidence status that led to it.
        """

        reasons: list[str] = []
        item = None
        if _has_brand(candidate):
            item = self._try_official_source(context, candidate, reasons)
        else:
            reasons.append("generic food (no official page to search)")
        if item is None:
            item = self._try_reference_source(context, candidate, reasons)
        if item is None:
            item = self._model_prior(context, candidate, reasons)
        # Surface the resolution's assumptions on the run too (content-free metadata).
        for assumption in item.assumptions:
            if assumption not in context.assumptions:
                context.assumptions.append(assumption)
        return item

    def _try_official_source(
        self, context: EstimationContext, candidate: CandidateDraft, reasons: list[str]
    ) -> ResolvedFoodItem | None:
        """Search + fetch + extract an official page; ``None`` to fall through.

        Returns ``None`` (→ reference source) when official sources are unavailable
        or no candidate page yields confident, schema-valid facts, appending the
        sanitized reason to ``reasons``. Raises :class:`NeedsClarification` only when
        usable facts were found but the consumed quantity cannot be resolved to grams
        (asking beats guessing the portion).
        """

        if not self.search_provider.enabled:
            reasons.append("official_source search disabled")
            return None
        if not self.search_provider.available:
            reasons.append("official_source search unavailable (no search credentials)")
            return None
        if not self.fetch_settings.is_available:
            reasons.append("official_source fetch unconfigured")
            return None

        _record_source_ref(context, OFFICIAL_SOURCE)
        item = self._resolve_from_search(
            context,
            candidate,
            query=_identity_query(candidate),
            fetch=self._fetch_official,
            page_kind=_OFFICIAL_PAGE_KIND,
            source_type=OFFICIAL_SOURCE_TYPE,
        )
        if item is None:
            reasons.append("official_source returned no confident match")
        return item

    def _try_reference_source(
        self, context: EstimationContext, candidate: CandidateDraft, reasons: list[str]
    ) -> ResolvedFoodItem | None:
        """Search + fetch + extract a public nutrition reference page (FTY-166).

        The evidence tier between official source and model prior: the query is the
        sanitized item identity plus the fixed nutrition intent, the result pages are
        fetched through the searched-result hardened fetcher, and the stated facts are
        transcribed/validated exactly like an official page. Returns ``None``
        (→ model prior) when the tier is unavailable or nothing confident is found,
        appending the sanitized reason to ``reasons``.
        """

        if not self.search_provider.enabled:
            reasons.append("reference_source search disabled")
            return None
        if not self.search_provider.available:
            reasons.append("reference_source search unavailable (no search credentials)")
            return None
        if not self.reference_fetch_settings.is_available:
            reasons.append("reference_source fetch disabled")
            return None

        _record_source_ref(context, REFERENCE_SOURCE)
        item = self._resolve_from_search(
            context,
            candidate,
            query=f"{_identity_query(candidate)} {REFERENCE_SEARCH_INTENT}",
            fetch=self._fetch_reference,
            page_kind=_REFERENCE_PAGE_KIND,
            source_type=REFERENCE_SOURCE_TYPE,
        )
        if item is None:
            reasons.append("reference_source returned no confident match")
        return item

    def _resolve_from_search(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        *,
        query: str,
        fetch: Callable[[str], str | None],
        page_kind: str,
        source_type: str,
    ) -> ResolvedFoodItem | None:
        """Run one evidence tier: search ``query``, then fetch/extract each result.

        The shared search → fetch → extract → recompute chain both web-evidence tiers
        use; only the query, the fetcher, the prompt framing, and the recorded
        ``source_type`` differ. Returns the first result page that yields confident,
        schema-valid, plausible facts, or ``None`` so the caller falls through.
        """

        found = searched_reference_per_100g(
            provider=self.provider,
            search_provider=self.search_provider,
            fetch=fetch,
            query=query,
            page_kind=page_kind,
            source_type=source_type,
        )
        if found is None:
            return None
        return self._build_item(
            context,
            candidate,
            found,
            source_type=source_type,
            source_ref=found.source_ref,
            hash_key=found.hash_key,
            base_assumptions=(),
        )

    def _model_prior(
        self, context: EstimationContext, candidate: CandidateDraft, reasons: list[str]
    ) -> ResolvedFoodItem:
        """Estimate the named food from model prior, recorded with an explicit status.

        The gated last resort: the entry carries ``source_type = model_prior`` and an
        ``assumptions`` reason naming, per evidence tier, why official/reference
        evidence was not used, so the source status is surfaced and the entry stays
        user-editable. A model that cannot estimate the item (``unresolved`` / no
        facts) routes to ``needs_clarification`` — still never a silent guess.
        """

        _record_source_ref(context, MODEL_PRIOR_SOURCE)
        reason = "; ".join([*reasons, "estimated from model prior"])
        estimate = self._estimate_model_prior(candidate)
        if estimate is None or estimate.disposition is not EstimateDisposition.RESOLVED:
            context.clarification_questions = [ClarificationDraft(text=UNKNOWN_FOOD_QUESTION)]
            raise NeedsClarification("model_prior_unavailable")

        reference = _searched_reference_from_estimate(
            estimate,
            source_ref=MODEL_PRIOR_SOURCE,
            hash_key=_identity_query(candidate),
        )
        if reference is None:
            context.clarification_questions = [ClarificationDraft(text=UNKNOWN_FOOD_QUESTION)]
            raise NeedsClarification("model_prior_unusable")

        item = self._build_item(
            context,
            candidate,
            reference,
            source_type=MODEL_PRIOR_SOURCE_TYPE,
            source_ref=MODEL_PRIOR_SOURCE,
            hash_key=_identity_query(candidate),
            base_assumptions=(reason,),
        )
        if item is None:
            # The estimate was unusable (e.g. per-serving facts with no gram serving
            # size); ask rather than guess the portion.
            context.clarification_questions = [ClarificationDraft(text=UNKNOWN_FOOD_QUESTION)]
            raise NeedsClarification("model_prior_unusable")
        return item

    def _fetch_official(self, url: str) -> str | None:
        """Fetch ``url`` through the official hardened fetcher; ``None`` on failure.

        A policy/transport/response failure on one page is not fatal — the resolver
        tries the next candidate URL or falls through to the next tier. The fetcher's
        errors are content-free, so nothing about the URL/body is surfaced.
        """

        try:
            return self.fetch_fn(url, self.fetch_settings)
        except (FetchPolicyError, FetchTransientError, FetchResponseError):
            return None

    def _fetch_reference(self, url: str) -> str | None:
        """Fetch ``url`` through the searched-result fetcher; ``None`` on failure.

        Same non-fatal mapping as :meth:`_fetch_official`; the searched-result policy
        (HTTPS-only, public-IP-only, no redirects, bounded, inert text) is enforced
        inside the injected fetcher.
        """

        try:
            return self.reference_fetch_fn(url, self.reference_fetch_settings)
        except (FetchPolicyError, FetchTransientError, FetchResponseError):
            return None

    def _estimate_model_prior(self, candidate: CandidateDraft) -> NamedFoodEstimate | None:
        """Ask the model for a best-effort estimate from the item identity only."""

        prompt = _MODEL_PRIOR_PROMPT.format(identity=_identity_query(candidate))
        try:
            return self.provider.structured_completion(prompt, NamedFoodEstimate)
        except (
            StructuredOutputValidationError,
            LLMResponseError,
            LLMConfigurationError,
            LLMTransientError,
        ):
            return None

    @staticmethod
    def _build_item(
        context: EstimationContext,
        candidate: CandidateDraft,
        reference: SearchedReferenceFacts,
        *,
        source_type: str,
        source_ref: str,
        hash_key: str,
        base_assumptions: tuple[str, ...],
    ) -> ResolvedFoodItem | None:
        """Apply deterministic serving math and build the resolved item + provenance.

        Returns ``None`` when the validated facts cannot be canonicalised to per-100g
        (per-serving facts with no gram serving size), so the caller can try another
        source. Raises :class:`NeedsClarification` when the facts are usable but the
        consumed quantity does not resolve to grams.
        """

        grams = resolve_grams(
            unit=candidate.unit,
            amount=candidate.amount,
            quantity_text=candidate.quantity_text,
            default_serving_g=reference.default_serving_g,
        )
        if grams is None:
            context.clarification_questions = [ClarificationDraft(text=QUANTITY_QUESTION)]
            raise NeedsClarification("unresolvable_quantity")

        per_100g = reference.facts
        scaled = scale_facts(per_100g, grams)
        content_hash = _content_hash(hash_key, per_100g)
        assumptions = base_assumptions + reference.assumptions

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


def _has_brand(candidate: CandidateDraft) -> bool:
    """Whether ``candidate`` names a branded product (has a non-blank ``brand``)."""

    return bool(candidate.brand and candidate.brand.strip())


def _searched_reference_from_estimate(
    estimate: NamedFoodEstimate, *, source_ref: str, hash_key: str
) -> SearchedReferenceFacts | None:
    """Canonicalise a model-prior estimate into the shared raw-facts carrier."""

    if estimate.facts is None:
        return None
    canonical = _to_per_100g(estimate.facts)
    if canonical is None:
        return None
    per_100g, default_serving_g = canonical
    return SearchedReferenceFacts(
        facts=per_100g,
        source_ref=source_ref,
        hash_key=hash_key,
        default_serving_g=default_serving_g,
        assumptions=tuple(estimate.assumptions),
    )
