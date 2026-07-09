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

from app.estimator.count_serving_resolution import (
    can_scale_reference,
    has_explicit_amount,
    scale_count_reference,
)
from app.estimator.evidence_utils import _content_hash, _record_source_ref
from app.estimator.food_serving import NutritionFacts, resolve_grams, scale_facts
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.identity_sanitizer import sanitized_identity
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
    _LOGGED_MODEL_PRIOR_PROMPT,
    _OFFICIAL_PAGE_KIND,
    _REFERENCE_PAGE_KIND,
    MODEL_PRIOR_SOURCE,
    MODEL_PRIOR_SOURCE_TYPE,
    REFERENCE_SEARCH_INTENT,
    REFERENCE_SOURCE,
    REFERENCE_SOURCE_TYPE,
    SearchedReferenceFacts,
    _identity_query,
    _searched_reference_from_facts,
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
    OFFICIAL_SOURCE_SCHEMA_VERSION,
    EstimateDisposition,
    FactBasis,
    NamedFoodEstimate,
)
from app.settings import DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR, EstimatorClarifyMode

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
    model_prior_confidence_floor: float = DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR
    clarify_mode: EstimatorClarifyMode = "estimate_first"
    name: str = "official_source_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        pending = list(context.pending_official_candidates)
        if not pending:
            # No candidate fell through from the food step; nothing to do.
            context.record_step(self.name, "skipped")
            return

        context.schema_version = OFFICIAL_SOURCE_SCHEMA_VERSION

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
        sanitized reason to ``reasons``. Under estimate-first, a serving gap uses a
        rough default/as-logged fallback when possible; stricter modes may still raise
        :class:`NeedsClarification` for the quantity.
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
        reason_count = len(reasons)
        item = self._resolve_from_search(
            context,
            candidate,
            query=_identity_query(candidate),
            fetch=self._fetch_official,
            page_kind=_OFFICIAL_PAGE_KIND,
            source_type=OFFICIAL_SOURCE_TYPE,
            reasons=reasons,
        )
        if item is None and len(reasons) == reason_count:
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
        reason_count = len(reasons)
        item = self._resolve_from_search(
            context,
            candidate,
            query=f"{_identity_query(candidate)} {REFERENCE_SEARCH_INTENT}",
            fetch=self._fetch_reference,
            page_kind=_REFERENCE_PAGE_KIND,
            source_type=REFERENCE_SOURCE_TYPE,
            reasons=reasons,
        )
        if item is None and len(reasons) == reason_count:
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
        reasons: list[str],
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
            allow_count_serving=True,
            accept_result=lambda found: can_scale_reference(candidate, found),
        )
        if found is None:
            return None
        item = self._build_item(
            context,
            candidate,
            found,
            source_type=source_type,
            source_ref=found.source_ref,
            hash_key=found.hash_key,
            base_assumptions=(),
            allow_unresolvable_fallthrough=self.clarify_mode == "estimate_first",
        )
        if item is None:
            reasons.append(f"{source_type} returned unscalable serving math")
        return item

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
        if (
            estimate is None
            or estimate.disposition is not EstimateDisposition.RESOLVED
            or estimate.confidence < self.model_prior_confidence_floor
        ):
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
            allow_unresolvable_fallthrough=self.clarify_mode == "estimate_first",
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
        """Ask for a rough estimate from sanitized identity + structured portion."""

        identity = _sanitized_model_identity(candidate)
        if not identity:
            return None
        prompt = _LOGGED_MODEL_PRIOR_PROMPT.format(
            identity=identity,
            portion=_structured_portion_for_prompt(candidate),
        )
        try:
            return self.provider.structured_completion(prompt, NamedFoodEstimate)
        except (
            StructuredOutputValidationError,
            LLMResponseError,
            LLMConfigurationError,
            LLMTransientError,
        ):
            return None

    def _build_item(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        reference: SearchedReferenceFacts,
        *,
        source_type: str,
        source_ref: str,
        hash_key: str,
        base_assumptions: tuple[str, ...],
        allow_unresolvable_fallthrough: bool = False,
    ) -> ResolvedFoodItem | None:
        """Apply deterministic serving math and build the resolved item + provenance.

        Returns ``None`` when the validated facts cannot be canonicalised to a usable
        basis, so the caller can try another source. Raises
        :class:`NeedsClarification` only when the active policy still allows asking
        after rough default/as-logged fallback has been considered.
        """

        assumptions = base_assumptions + reference.assumptions
        if reference.basis == FactBasis.AS_LOGGED.value:
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
                context.clarification_questions = [ClarificationDraft(text=QUANTITY_QUESTION)]
                raise NeedsClarification("unresolvable_quantity")
            if not _allows_default_serving_estimate(self.clarify_mode, candidate):
                context.clarification_questions = [ClarificationDraft(text=QUANTITY_QUESTION)]
                raise NeedsClarification("unresolvable_quantity")
            assumptions = _with_unique_assumptions(
                assumptions,
                (
                    f"clarify_mode:{self.clarify_mode}",
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


def _has_brand(candidate: CandidateDraft) -> bool:
    """Whether ``candidate`` names a branded product (has a non-blank ``brand``)."""

    return bool(candidate.brand and candidate.brand.strip())


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


def _sanitized_model_identity(candidate: CandidateDraft) -> str:
    """Identity sent to model-prior: bounded food tokens only, never diary text."""

    return sanitized_identity(_identity_query(candidate))


def _structured_portion_for_prompt(candidate: CandidateDraft) -> str:
    """Bounded structured portion summary for model-prior, excluding raw text."""

    if candidate.amount is not None and candidate.amount > 0:
        unit = sanitized_identity(candidate.unit or "") or "count"
        return f"amount={candidate.amount:g}; unit={unit}"
    return "amount=unspecified; use one typical serving only if needed"


def _searched_reference_from_estimate(
    estimate: NamedFoodEstimate, *, source_ref: str, hash_key: str
) -> SearchedReferenceFacts | None:
    """Canonicalise a model-prior estimate into the shared raw-facts carrier."""

    if estimate.facts is None:
        return None
    if estimate.facts.basis is FactBasis.AS_LOGGED:
        facts = NutritionFacts(
            calories=estimate.facts.calories,
            protein_g=estimate.facts.protein_g,
            carbs_g=estimate.facts.carbs_g,
            fat_g=estimate.facts.fat_g,
        )
        return SearchedReferenceFacts(
            facts=facts,
            source_ref=source_ref,
            hash_key=hash_key,
            default_serving_g=None,
            assumptions=tuple(estimate.assumptions),
            basis=FactBasis.AS_LOGGED.value,
        )
    return _searched_reference_from_facts(
        estimate.facts,
        source_ref=source_ref,
        hash_key=hash_key,
        assumptions=tuple(estimate.assumptions),
        allow_count_serving=True,
    )
