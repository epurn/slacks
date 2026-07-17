"""The official/reference-source resolution step (FTY-062, FTY-166).

The last-resort food-resolution step before model-prior. It picks up the food
candidates the upstream USDA/OFF food step (FTY-044/060) could not resolve —
branded restaurant/manufacturer products and detail-rich generic foods (FTY-167) —
and costs them from web evidence, deterministically, in explicit tier order:

1. **Official source** (FTY-062, branded candidates only): search the sanitized
   item identity (name + brand, no personal context) through the pluggable search
   adapter (FTY-079), fetch each candidate result URL through the hardened,
   allowlisted official fetcher (FTY-078), and transcribe the facts the page
   states. Since FTY-253 each tier searches a bounded, deterministic set of
   identity-query variants (:func:`~app.estimator.branded_routing.identity_variants`
   — the ``name + brand`` base, product-hint token orders lifted from the quantity
   phrase, and a static retailer alias expansion), and every evidence candidate
   must pass a brand/product-compatibility gate before it may back a branded item.
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
from dataclasses import dataclass, replace

from app.estimator.branded_routing import (
    identity_variants,
    is_evidence_brand_compatible,
    product_hint,
)
from app.estimator.evidence_utils import _record_source_ref
from app.estimator.food_resolvers import OffNameResolver, _ResolvedProduct
from app.estimator.food_serving import NutritionFacts
from app.estimator.interpretation_tools import (
    add_evidence_record,
    current_food_candidate,
    evidence_text_stager,
    reinterpret_food_candidate,
)
from app.estimator.model_prior import _model_prior
from app.estimator.off import (
    OFF_SOURCE,
    OFF_SOURCE_TYPE,
    OffResponseError,
    OffTransientError,
)
from app.estimator.official_fetch import OfficialFetchSettings, fetch_official_source
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
    collect_component_clarification,
)
from app.estimator.reference_fetch import ReferenceFetchSettings, fetch_searched_result
from app.estimator.resolved_item import _build_item
from app.estimator.resolved_plausibility import (
    IMPLAUSIBLE_RESOLVED_TOTAL_OUTCOME,
    check_resolved_food_total,
    refit_assumption,
)
from app.estimator.search import (
    OFFICIAL_SOURCE,
    OFFICIAL_SOURCE_TYPE,
    SearchProvider,
)
from app.estimator.searched_reference import (
    _OFFICIAL_PAGE_KIND,
    _REFERENCE_PAGE_KIND,
    MODEL_PRIOR_SOURCE,
    MODEL_PRIOR_SOURCE_TYPE,
    REFERENCE_SEARCH_INTENT,
    REFERENCE_SOURCE,
    REFERENCE_SOURCE_TYPE,
    SearchedReferenceFacts,
    searched_reference_per_100g,
)
from app.estimator.web_evidence_trace import (
    acceptance_gate,
    decision_recorder,
    trace_candidate_index,
    traced_fetch,
)
from app.llm.base import Provider
from app.schemas.official_source import OFFICIAL_SOURCE_SCHEMA_VERSION, FactBasis
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
    #: The name-keyed Open Food Facts resolver (FTY-369). Optional so a build without
    #: OFF (or a composition test) keeps the pre-FTY-369 official→reference→model-prior
    #: chain; when present, it fills the branded ``product_database`` gap between the
    #: official-source and reference tiers for a barcode-less branded product.
    off_name_resolver: OffNameResolver | None = None
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
            try:
                item = self._resolve(context, candidate)
            except NeedsClarification as exc:
                # FTY-329: a component the web-evidence/model-prior tiers cannot cost is
                # collected as its own item-scoped outcome rather than aborting the
                # whole pipeline, so the entry's costable siblings still resolve.
                collect_component_clarification(context, candidate, exc.reason, step=self.name)
                continue
            context.resolved_food_items.append(item)

        # Every pending candidate is now resolved or collected as an item-scoped
        # clarification; clear so the worker does not also persist them as unresolved
        # leftovers (which would double-represent a component).
        context.pending_official_candidates.clear()
        context.record_step(self.name, "ok")

    def _resolve(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        *,
        allow_requery: bool = True,
    ) -> ResolvedFoodItem:
        """Resolve one candidate: official source, else reference source, else model prior.

        A *branded* candidate is searched against official sources first (a named
        restaurant/manufacturer product has an authoritative page); a *generic*
        detail-rich candidate (FTY-167) has no official brand page, so its first
        evidence tier is the reference source. ``reasons`` accumulates, per tier, a
        short sanitized label for why the tier produced nothing, so a model-prior
        fallback always carries the explicit evidence status that led to it.
        """

        index = trace_candidate_index(context, candidate)
        candidate = current_food_candidate(context, candidate, index)
        ledger_start = _evidence_ledger_size(context)
        reasons: list[str] = []
        item = self._resolve_evidence_tiers(context, candidate, reasons, index)
        if (
            item is None
            and allow_requery
            and _evidence_dead_end_recorded(context, ledger_start=ledger_start)
        ):
            revised = reinterpret_food_candidate(
                context,
                candidate,
                index,
                step_name=self.name,
                trigger_tier=REFERENCE_SOURCE_TYPE,
            )
            if revised is not None:
                return self._resolve(context, revised, allow_requery=False)
        if item is None:
            item = _model_prior(
                context,
                candidate,
                reasons,
                index,
                step_name=self.name,
                provider=self.provider,
                model_prior_confidence_floor=self.model_prior_confidence_floor,
                clarify_mode=self.clarify_mode,
                unknown_food_question=UNKNOWN_FOOD_QUESTION,
                quantity_question=QUANTITY_QUESTION,
            )
        # FTY-368: a candidate that reached this refit because the exact path's
        # resolved total tripped the plausibility gate carries the content-free
        # refit label, so the rough re-estimate is never presented as if the
        # trusted row had scaled cleanly.
        refit_reason = None if index is None else context.plausibility_refit_reasons.get(index)
        if refit_reason is not None:
            label = refit_assumption(refit_reason)
            if label not in item.assumptions:
                item = replace(item, assumptions=(*item.assumptions, label))
        # Surface the resolution's assumptions on the run too (content-free metadata).
        for assumption in item.assumptions:
            if assumption not in context.assumptions:
                context.assumptions.append(assumption)
        return item

    def _resolve_evidence_tiers(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        reasons: list[str],
        index: int | None,
    ) -> ResolvedFoodItem | None:
        """Run the ordered web/product evidence tiers, returning the first hit.

        Tier order follows the evidence-retrieval hierarchy: official source (rank 2,
        branded only) → Open Food Facts by name (rank 3 ``product_database``, FTY-369) →
        reference source (rank 5). ``None`` means every tier produced nothing confident,
        so :meth:`_resolve` re-interprets/re-queries once and then falls to model prior.
        A generic food (no brand) records official source as not-applicable and starts at
        OFF/reference.
        """

        if _has_brand(candidate):
            item = self._try_official_source(context, candidate, reasons, index)
        else:
            reasons.append("generic food (official_source not applicable by session hypothesis)")
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=OFFICIAL_SOURCE_TYPE,
                outcome="not_applicable_by_session",
            )
            add_evidence_record(
                context, tier=OFFICIAL_SOURCE_TYPE, outcome="not_applicable_by_session"
            )
            item = None
        if item is None:
            # FTY-369: the branded product_database tier (rank 3) — OFF by name —
            # consults between official source (rank 2) and reference (rank 5), so a
            # trivially findable branded packaged product lands as product_database
            # evidence instead of falling straight to a bare model prior.
            item = self._try_off_name_search(context, candidate, reasons, index)
        if item is None:
            item = self._try_reference_source(context, candidate, reasons, index)
        return item

    def _try_official_source(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        reasons: list[str],
        index: int | None,
    ) -> ResolvedFoodItem | None:
        """Search + fetch + extract an official page; ``None`` to fall through.

        Returns ``None`` (→ reference source) when official sources are unavailable
        or no candidate page yields confident, schema-valid facts, appending the
        sanitized reason to ``reasons``. Under estimate-first, a serving gap uses a
        rough default/as-logged fallback when possible; stricter modes may still raise
        :class:`NeedsClarification` for the quantity.
        """

        unavailable = self._tier_unavailability(fetch_available=self.fetch_settings.is_available)
        if unavailable is not None:
            reasons.append(f"official_source {unavailable[0]}")
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=OFFICIAL_SOURCE_TYPE,
                outcome=unavailable[1],
            )
            add_evidence_record(context, tier=OFFICIAL_SOURCE_TYPE, outcome=unavailable[1])
            return None

        _record_source_ref(context, OFFICIAL_SOURCE)
        reason_count = len(reasons)
        item = self._resolve_from_search(
            context,
            candidate,
            queries=identity_variants(candidate),
            fetch_raw=self._fetch_official,
            page_kind=_OFFICIAL_PAGE_KIND,
            source_type=OFFICIAL_SOURCE_TYPE,
            reasons=reasons,
            candidate_index=index,
        )
        if item is None and len(reasons) == reason_count:
            reasons.append("official_source returned no confident match")
        return item

    def _try_off_name_search(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        reasons: list[str],
        index: int | None,
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

        resolver = self.off_name_resolver
        gate_brand = _off_gate_brand(candidate)
        if resolver is None or not resolver.enabled:
            reasons.append("product_database disabled")
            self._record_off(context, index, "disabled")
            return None
        if gate_brand is None:
            # A generic food (no brand identity) has no packaged product to match by
            # name; product_database does not apply to it (rank-3 is branded/hinted).
            reasons.append("product_database not applicable (no brand identity)")
            self._record_off(context, index, "not_applicable_by_session")
            return None

        _record_source_ref(context, OFF_SOURCE)

        def _accept(evidence_name: str) -> bool:
            return is_evidence_brand_compatible(
                evidence_name, name=candidate.name, brand=gate_brand
            )

        reason_count = len(reasons)
        for query in identity_variants(candidate):
            try:
                resolved = resolver.resolve_compatible(query, accept=_accept)
            except OffTransientError:
                reasons.append("product_database transient error")
                self._record_off(context, index, "off_transient_error")
                return None
            except OffResponseError:
                reasons.append("product_database response error")
                self._record_off(context, index, "off_response_error")
                return None
            if resolved is None:
                continue
            item = self._build_off_item(context, candidate, resolved, index, reasons)
            if item is not None:
                return item
        if len(reasons) == reason_count:
            reasons.append("product_database returned no confident match")
        self._record_off(context, index, "miss")
        return None

    def _build_off_item(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        resolved: _ResolvedProduct,
        index: int | None,
        reasons: list[str],
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
            step_name=self.name,
            clarify_mode=self.clarify_mode,
            quantity_question=QUANTITY_QUESTION,
            allow_unresolvable_fallthrough=self.clarify_mode == "estimate_first",
            candidate_index=index,
        )
        if item is None:
            unscalable = "product_database returned unscalable serving math"
            if unscalable not in reasons:
                reasons.append(unscalable)
            self._record_off(context, index, "rejected_unresolvable_quantity", product.source_ref)
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
            self._record_off(context, index, IMPLAUSIBLE_RESOLVED_TOTAL_OUTCOME, product.source_ref)
            return None
        _record_source_ref(context, OFF_SOURCE)
        self._record_off(context, index, "accepted", product.source_ref)
        return item

    def _record_off(
        self,
        context: EstimationContext,
        index: int | None,
        outcome: str,
        source_ref: str | None = None,
    ) -> None:
        """Record one sanitized OFF-name-search decision + evidence-view entry."""

        context.record_decision(
            self.name,
            "source",
            candidate_index=index,
            tier=OFF_SOURCE_TYPE,
            source_ref=source_ref,
            outcome=outcome,
        )
        add_evidence_record(context, tier=OFF_SOURCE_TYPE, outcome=outcome, source_ref=source_ref)

    def _try_reference_source(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        reasons: list[str],
        index: int | None,
    ) -> ResolvedFoodItem | None:
        """Search + fetch + extract a public nutrition reference page (FTY-166).

        The evidence tier between official source and model prior: the query is the
        sanitized item identity plus the fixed nutrition intent, the result pages are
        fetched through the searched-result hardened fetcher, and the stated facts are
        transcribed/validated exactly like an official page. Returns ``None``
        (→ model prior) when the tier is unavailable or nothing confident is found,
        appending the sanitized reason to ``reasons``.
        """

        unavailable = self._tier_unavailability(
            fetch_available=self.reference_fetch_settings.is_available
        )
        if unavailable is not None:
            reason = "fetch disabled" if unavailable[1] == "fetch_unconfigured" else unavailable[0]
            reasons.append(f"reference_source {reason}")
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=REFERENCE_SOURCE_TYPE,
                outcome=unavailable[1],
            )
            add_evidence_record(context, tier=REFERENCE_SOURCE_TYPE, outcome=unavailable[1])
            return None

        _record_source_ref(context, REFERENCE_SOURCE)
        reason_count = len(reasons)
        item = self._resolve_from_search(
            context,
            candidate,
            queries=tuple(
                f"{variant} {REFERENCE_SEARCH_INTENT}" for variant in identity_variants(candidate)
            ),
            fetch_raw=self._fetch_reference,
            page_kind=_REFERENCE_PAGE_KIND,
            source_type=REFERENCE_SOURCE_TYPE,
            reasons=reasons,
            candidate_index=index,
        )
        if item is None and len(reasons) == reason_count:
            reasons.append("reference_source returned no confident match")
        return item

    def _tier_unavailability(self, *, fetch_available: bool) -> tuple[str, str] | None:
        """The (reason suffix, trace outcome) for an unavailable web-evidence tier.

        ``None`` when search and fetch are both usable. Shared by both tiers so the
        human-readable reason strings and the sanitized trace outcome labels cannot
        drift apart.
        """

        if not self.search_provider.enabled:
            return "search disabled", "search_disabled"
        if not self.search_provider.available:
            return "search unavailable (no search credentials)", "search_unavailable"
        if not fetch_available:
            return "fetch unconfigured", "fetch_unconfigured"
        return None

    def _resolve_from_search(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        *,
        queries: tuple[str, ...],
        fetch_raw: Callable[[str], str],
        page_kind: str,
        source_type: str,
        reasons: list[str],
        candidate_index: int | None,
    ) -> ResolvedFoodItem | None:
        """Run one evidence tier: search each bounded query, fetch/extract each result.

        The shared search → fetch → extract → recompute chain both web-evidence tiers
        use; only the queries, the fetcher, the prompt framing, and the recorded
        ``source_type`` differ. ``queries`` is the bounded identity-variant set
        (FTY-253): variants are tried in order and each result must pass the
        quantity-costability *and* brand/product-compatibility gates, so an earlier
        generic/incompatible evidence candidate is rejected in favor of a later
        compatible one. Returns the first fully supported result, or ``None`` so the
        caller falls through to the next tier. Every search / fetch / extract / gate
        decision is recorded on the sanitized run trace per query variant (FTY-255).
        """

        candidate = current_food_candidate(context, candidate, candidate_index)
        for variant_index, query in enumerate(queries):
            note = decision_recorder(
                self.name,
                context,
                candidate_index=candidate_index,
                tier=source_type,
                query_variant=variant_index,
            )
            found = searched_reference_per_100g(
                provider=self.provider,
                search_provider=self.search_provider,
                fetch=traced_fetch(fetch_raw, source_type, note),
                query=query,
                page_kind=page_kind,
                source_type=source_type,
                allow_count_serving=True,
                accept_result=acceptance_gate(candidate, note),
                observe=note,
                stage_text=evidence_text_stager(context, tier=source_type),
            )
            if found is None:
                continue
            item = _build_item(
                context,
                candidate,
                found,
                source_type=source_type,
                source_ref=found.source_ref,
                hash_key=found.hash_key,
                base_assumptions=(),
                step_name=self.name,
                clarify_mode=self.clarify_mode,
                quantity_question=QUANTITY_QUESTION,
                allow_unresolvable_fallthrough=self.clarify_mode == "estimate_first",
                candidate_index=candidate_index,
            )
            if item is not None:
                # FTY-368: the resolved-value gate also bounds web-evidence
                # totals — an implausible dish total falls through to the next
                # variant/tier instead of committing, exactly like the exact path.
                verdict = check_resolved_food_total(
                    name=candidate.name,
                    unit=candidate.unit,
                    amount=candidate.amount,
                    quantity_text=candidate.quantity_text,
                    grams=item.grams,
                    calories=item.calories,
                )
                if verdict.plausible:
                    return item
                note(
                    decision="serving",
                    source_ref=found.source_ref,
                    outcome=IMPLAUSIBLE_RESOLVED_TOTAL_OUTCOME,
                )
                if candidate_index is not None and verdict.reason is not None:
                    context.plausibility_refit_reasons[candidate_index] = verdict.reason
                implausible = f"{source_type} returned implausible resolved total"
                if implausible not in reasons:
                    reasons.append(implausible)
                continue
            note(
                decision="serving",
                source_ref=found.source_ref,
                outcome="rejected_unresolvable_quantity",
            )
            unscalable = f"{source_type} returned unscalable serving math"
            if unscalable not in reasons:
                reasons.append(unscalable)
        return None

    def _fetch_official(self, url: str) -> str:
        """Fetch ``url`` through the official hardened fetcher.

        Policy/transport/response failures propagate as the typed hardened-fetch
        errors; the per-variant traced wrapper (:func:`_traced_fetch`) maps each to
        a content-free trace outcome and continues non-fatally — the resolver tries
        the next candidate URL or falls through to the next tier. The fetcher's
        errors are content-free, so nothing about the URL/body is surfaced.
        """

        return self.fetch_fn(url, self.fetch_settings)

    def _fetch_reference(self, url: str) -> str:
        """Fetch ``url`` through the searched-result fetcher.

        Same typed-error contract as :meth:`_fetch_official`; the searched-result
        policy (HTTPS-only, public-IP-only, no redirects, bounded, inert text) is
        enforced inside the injected fetcher.
        """

        return self.reference_fetch_fn(url, self.reference_fetch_settings)


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


_REQUERY_EVIDENCE_OUTCOMES = frozenset(
    {
        "miss",
        "partial",
        "failed",
        "rejected_brand_mismatch",
        "rejected_implausible_resolved_total",
        "rejected_incompatible_serving",
        "rejected_unresolvable_quantity",
        "skipped_long_source_ref",
        "fetch_empty_text",
        "fetch_policy_blocked",
        "fetch_transient_error",
        "fetch_response_error",
        "extract_error",
        "extract_unresolved",
        "extract_low_confidence",
        "extract_rejected_facts",
        "snippet_unavailable",
    }
)


def _evidence_ledger_size(context: EstimationContext) -> int:
    session = context.interpretation_session
    return 0 if session is None else len(session.evidence_ledger)


def _evidence_dead_end_recorded(context: EstimationContext, *, ledger_start: int) -> bool:
    session = context.interpretation_session
    if session is None:
        return False
    for record in session.evidence_ledger[ledger_start:]:
        if record.outcome in _REQUERY_EVIDENCE_OUTCOMES or record.outcome.startswith("fetch_"):
            return True
    return False
