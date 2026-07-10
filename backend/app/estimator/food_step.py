"""The food-resolution step (FTY-044 generic foods + FTY-060 barcode lookup).

The third real estimation pipeline step. It takes the food candidates the parse
step (FTY-042) extracted and resolves each into canonical calories and macros, with
deterministic serving math, from the highest-preference applicable source:

1. **Open Food Facts** (``product_database``, FTY-060) for a candidate carrying a
   barcode — a packaged-product fact, preferred over a generic estimate.
2. **USDA FoodData Central** (``trusted_nutrition_database``, FTY-044) for a generic
   food, looked up by name.
3. **Reference/model/default rough estimation** (FTY-301) for recognized candidates
   whose exact source match cannot be scaled, whose source lookup misses, or whose
   amount is absent under the default estimate-first policy.

Exercise candidates are left untouched (resolution is FTY-043).

A :class:`FoodResolver` / :class:`BarcodeResolver` each own the side of resolution
that needs the database — the global ``products`` cache — and an external source
(:class:`~app.estimator.fdc.FoodSource` / :class:`~app.estimator.off.BarcodeSource`).
They are constructed by the worker (which holds the session) and injected into the
step; the step itself stays a thin orchestration over the resolvers plus the pure
serving math (:mod:`app.estimator.food_serving`).

Routing follows FTY-042/043 conventions:

- **all candidates resolve** → record :class:`~app.estimator.pipeline.ResolvedFoodItem`
  results on the context; the worker persists them ``resolved`` with calories/macros,
  caches the source facts as ``products``, and writes an ``evidence_sources`` row per
  item, then completes the event.
- **no source applies** → with no enabled source for a generic candidate (e.g. no
  FDC key and no barcode/OFF), it is left ``unresolved`` and the event still completes.
- **branded candidate USDA/OFF cannot resolve** → deferred to the official-source
  step (FTY-062) via ``pending_official_candidates`` instead of clarifying: a named
  restaurant/manufacturer/packaged product falls through to search + hardened fetch,
  then a model-prior estimate. For a branded candidate a generic FDC hit is a
  *candidate*, not an authority (FTY-253): a row naming a different product identity
  fails the brand/product-compatibility gate
  (:func:`~app.estimator.branded_routing.is_evidence_brand_compatible`) and is
  treated as a miss, so brand-aware web/reference/model-prior resolution runs
  instead of completing or clarifying from the wrong product.
- **no confident source match for a generic food** (incl. a barcode OFF cannot
  resolve while OFF is available) / **unresolvable quantity** → under the default
  estimate-first mode, defer to the reference/model/default rough estimator before
  asking. ``strict`` can still keep the older quantity question. A barcode is
  **never** finalized as a barcode match from a guessed value while OFF is available.
- **transient source failure** → raise :class:`~app.estimator.pipeline.StepError`
  (retryable); a **non-retryable source error** → :class:`StepFailed` (fail closed).

The nutrition facts are never taken from the model — only from the trusted source —
and the run records the source reference as evidence, never any raw page/response,
the API key, or raw user text (security baseline + ``docs/security/data-retention.md``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimator.branded_routing import is_evidence_brand_compatible
from app.estimator.common_portions import resolve_common_portion_grams
from app.estimator.decision_trace import amount_kind
from app.estimator.detail_signals import has_food_detail, has_stated_nutrition
from app.estimator.evidence_utils import _record_source_ref
from app.estimator.fdc import (
    FDC_SOURCE,
    FDC_SOURCE_TYPE,
    FdcResponseError,
    FdcTransientError,
    FoodSource,
    ProductFacts,
    normalize_query,
)
from app.estimator.fdc_ranking import (
    is_fdc_description_compatible,
    is_fdc_description_rank_stable,
)
from app.estimator.food_serving import NutritionFacts, resolve_grams, scale_facts
from app.estimator.interpretation_tools import add_evidence_record, current_food_candidate
from app.estimator.off import (
    OFF_SOURCE,
    OFF_SOURCE_TYPE,
    BarcodeSource,
    OffResponseError,
    OffTransientError,
    normalize_barcode,
)
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
    StepError,
    StepFailed,
)
from app.models.food_sources import Product
from app.settings import EstimatorClarifyMode


def _is_official_eligible(candidate: CandidateDraft) -> bool:
    """Whether ``candidate`` names a *branded* product for official-source search.

    A candidate carrying a non-blank ``brand`` is a *named* restaurant / manufacturer
    / packaged product (FTY-062): if USDA/OFF cannot cost it, it falls through to the
    official-source resolver (search + hardened fetch) instead of stopping at
    clarification. A generic food (no brand) is never searched against official
    sources.
    """

    return bool(candidate.brand and candidate.brand.strip())


def _is_resolution_deferrable(candidate: CandidateDraft) -> bool:
    """Whether an *enabled-source* miss for ``candidate`` should defer to model-prior.

    A branded candidate defers so official-source resolution can search for it; a
    generic candidate carrying enough amount detail (a count, range, or measured
    quantity — FTY-167) defers so it reaches a **model-prior** estimate with an
    explicit source status instead of stopping at ``needs_clarification``. In the
    default FTY-301 estimate-first mode, even a recognizable amountless identity
    defers through a separate policy branch; this helper preserves the stricter-mode
    "stated detail" signal.
    """

    return (
        _is_official_eligible(candidate)
        or has_food_detail(candidate.amount, candidate.quantity_text)
        or has_stated_nutrition(
            candidate.stated_calories,
            candidate.stated_protein_g,
            candidate.stated_carbs_g,
            candidate.stated_fat_g,
        )
    )


#: Fixed, sanitized clarification questions used in place of any raw user text, so a
#: ``needs_clarification`` outcome always carries a question for the later answer flow.
UNKNOWN_FOOD_QUESTION = "Which food was that? We couldn't find a nutrition match."
BARCODE_UNKNOWN_QUESTION = (
    "We couldn't find that barcode's product. Which food was it, and how much?"
)
QUANTITY_QUESTION = "How much did you have (for example, in grams, millilitres, or servings)?"


@dataclass(frozen=True)
class _ResolvedProduct:
    """A cached :class:`Product` row plus the time its facts were obtained."""

    product: Product
    fetched_at: datetime


def _cache_product(session: Session, facts: ProductFacts) -> Product:
    """Insert ``facts`` as a global ``products`` row and flush to assign its id.

    Shared by both resolvers: the cached row holds global source facts only (no user
    data). ``barcode`` is set for a barcode source (OFF) and ``None`` for a name-keyed
    generic source (FDC).
    """

    product = Product(
        source=facts.source,
        source_ref=facts.source_ref,
        query_key=facts.query_key,
        barcode=facts.barcode,
        description=facts.description,
        calories_per_100g=facts.facts.calories,
        protein_per_100g=facts.facts.protein_g,
        carbs_per_100g=facts.facts.carbs_g,
        fat_per_100g=facts.facts.fat_g,
        default_serving_g=facts.default_serving_g,
        content_hash=facts.content_hash,
    )
    session.add(product)
    session.flush()
    return product


def _refresh_product(product: Product, facts: ProductFacts) -> Product:
    """Overwrite a stale cached row's facts in place from a fresh source lookup.

    The ``(source, query_key)`` uniqueness allows exactly one cache row per
    query, so replacing a rejected pre-FTY-254 selection means updating that
    row rather than inserting a sibling. Existing ``evidence_sources`` rows keep
    their own immutable fact snapshots, so refreshing the cache never rewrites
    a user's past resolutions.
    """

    product.source_ref = facts.source_ref
    product.description = facts.description
    product.calories_per_100g = facts.facts.calories
    product.protein_per_100g = facts.facts.protein_g
    product.carbs_per_100g = facts.facts.carbs_g
    product.fat_per_100g = facts.facts.fat_g
    product.default_serving_g = facts.default_serving_g
    product.content_hash = facts.content_hash
    return product


class FoodResolver:
    """Resolves a generic food name to a cached :class:`Product`, fetching on a miss.

    Owns the global ``products`` cache (read + get-or-create) and the external
    :class:`FoodSource` (USDA FDC). A *compatible* cache hit avoids any external
    call; a miss — or a stale cached row that fails the FTY-254 description
    compatibility gate — fetches from the source and caches/refreshes the global
    facts (no user data) in the session for the worker's commit. New cache rows are
    flushed so the worker can reference them from the user-owned
    ``evidence_sources`` it writes on success.
    """

    def __init__(self, *, session: Session, source: FoodSource) -> None:
        self._session = session
        self._source = source

    @property
    def enabled(self) -> bool:
        """Whether the underlying source is configured and may be queried."""

        return self._source.enabled

    def resolve_product(self, name: str) -> _ResolvedProduct | None:
        """Return the cached/fetched product for ``name``, or ``None`` if no match.

        Checks the ``products`` cache by normalized name first; on a miss, queries the
        source and caches the result. A cached row must still pass today's FTY-254
        compatibility gate (:func:`is_fdc_description_compatible`), and a compatible
        but non-rank-stable row (unstated demoted form or incomplete query-token
        coverage) is re-fetched once so the ranked lookup can replace it when FDC
        now returns a better match. If the fresh lookup has no replacement, the
        compatible cache row remains usable. Propagates :class:`FdcTransientError` /
        :class:`FdcResponseError` from the source for the step to route.
        """

        query_key = normalize_query(name)
        if not query_key:
            return None

        cached = self._session.scalars(
            select(Product).where(Product.source == FDC_SOURCE, Product.query_key == query_key)
        ).one_or_none()
        cached_is_compatible = False
        if cached is not None:
            cached_is_compatible = is_fdc_description_compatible(query_key, cached.description)
            if cached_is_compatible and is_fdc_description_rank_stable(
                query_key, cached.description
            ):
                return _ResolvedProduct(product=cached, fetched_at=cached.updated_at)

        facts = self._source.lookup(name)
        if facts is None:
            if cached is not None and cached_is_compatible:
                return _ResolvedProduct(product=cached, fetched_at=cached.updated_at)
            return None
        if cached is not None:
            return _ResolvedProduct(
                product=_refresh_product(cached, facts), fetched_at=datetime.now(UTC)
            )
        return _ResolvedProduct(
            product=_cache_product(self._session, facts), fetched_at=datetime.now(UTC)
        )


class BarcodeResolver:
    """Resolves a barcode to a cached :class:`Product`, fetching from OFF on a miss.

    The Open Food Facts counterpart to :class:`FoodResolver`. Owns the global
    ``products`` cache keyed by the normalized ``barcode`` under ``source =
    open_food_facts`` and the external :class:`BarcodeSource`. A cache hit makes **no**
    external call, so a repeat scan is free; a miss fetches by barcode only (no
    personal context) and caches the global facts.
    """

    def __init__(self, *, session: Session, source: BarcodeSource) -> None:
        self._session = session
        self._source = source

    @property
    def enabled(self) -> bool:
        """Whether the underlying OFF source is enabled and may be queried."""

        return self._source.enabled

    def resolve_product(self, barcode: str) -> _ResolvedProduct | None:
        """Return the cached/fetched product for ``barcode``, or ``None`` if no match.

        Checks the ``products`` cache by normalized barcode first; on a miss, queries
        OFF and caches the result. Propagates :class:`OffTransientError` /
        :class:`OffResponseError` from the source for the step to route.
        """

        normalized = normalize_barcode(barcode)
        if normalized is None:
            return None

        cached = self._session.scalars(
            select(Product).where(Product.source == OFF_SOURCE, Product.barcode == normalized)
        ).one_or_none()
        if cached is not None:
            return _ResolvedProduct(product=cached, fetched_at=cached.updated_at)

        facts = self._source.lookup(normalized)
        if facts is None:
            return None
        return _ResolvedProduct(
            product=_cache_product(self._session, facts), fetched_at=datetime.now(UTC)
        )


@dataclass(frozen=True)
class FoodResolveStep:
    """Resolve parsed food candidates into calories/macros from the best source.

    A barcode-bearing candidate prefers the Open Food Facts barcode source (FTY-060,
    ``barcode_resolver``) over generic USDA lookup (FTY-044, ``resolver``); a plain
    generic-food candidate uses USDA. ``barcode_resolver`` is optional so a build
    without OFF (e.g. pre-FTY-060 composition tests) keeps the generic-only behavior.
    """

    resolver: FoodResolver
    barcode_resolver: BarcodeResolver | None = None
    clarify_mode: EstimatorClarifyMode = "estimate_first"
    name: str = "food_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        if not context.food_candidates:
            # Nothing to resolve (e.g. an exercise-only event). No source consulted.
            context.record_step(self.name, "ok")
            return

        for index, candidate in enumerate(context.food_candidates):
            # One sanitized intro entry per candidate: structural booleans/labels
            # only (FTY-255) — never the candidate's name or quantity text.
            context.record_decision(
                self.name,
                "candidate",
                candidate_index=index,
                has_brand=_is_official_eligible(candidate),
                amount_kind=amount_kind(candidate.unit, candidate.amount, candidate.quantity_text),
            )
            self._dispatch(context, candidate, index)

        context.record_step(self.name, "ok")

    def _dispatch(self, context: EstimationContext, candidate: CandidateDraft, index: int) -> None:
        """Resolve one candidate, defer it to official source, or leave it unresolved.

        A barcode candidate prefers Open Food Facts; a generic candidate uses USDA. On
        a **miss** or an unscalable exact match, estimate-first defers recognized
        candidates to the official/reference/model/default rough path; stricter
        modes keep the older ask boundary for amountless items. When no enabled
        source applies and no rough estimator is wired, the candidate is left
        ``unresolved`` and the event still completes.
        """

        candidate = current_food_candidate(context, candidate, index)
        barcode_resolver = self.barcode_resolver

        if candidate.barcode and barcode_resolver is not None and barcode_resolver.enabled:
            item = self._try_barcode(context, candidate, barcode_resolver, index)
            if item is not None:
                context.resolved_food_items.append(item)
                return
            if _should_defer_after_source_gap(candidate, self.clarify_mode):
                self._record_deferral(context, index)
                context.pending_official_candidates.append(candidate)
                return
            # No match, invalid barcode, or no usable energy value: route
            # deterministically. Never finalized from a guess while OFF is available.
            context.record_decision(
                self.name, "outcome", candidate_index=index, outcome="clarified_barcode_unknown"
            )
            context.clarification_questions = [ClarificationDraft(text=BARCODE_UNKNOWN_QUESTION)]
            raise NeedsClarification("barcode_unknown")

        if self.resolver.enabled:
            item = self._try_generic(context, candidate, index)
            if item is not None:
                context.resolved_food_items.append(item)
                return
            # Estimate-first source gaps fall through to rough estimation for any
            # recognized candidate; stricter modes retain the older detail gate.
            if _should_defer_after_source_gap(candidate, self.clarify_mode):
                self._record_deferral(context, index)
                context.pending_official_candidates.append(candidate)
                return
            context.record_decision(
                self.name, "outcome", candidate_index=index, outcome="clarified_unknown_food"
            )
            context.clarification_questions = [ClarificationDraft(text=UNKNOWN_FOOD_QUESTION)]
            raise NeedsClarification("unknown_food")

        # No enabled source applies to this candidate (e.g. no FDC key and no
        # barcode/OFF). Estimate-first still gets a shot at reference/model/default
        # rough resolution when the downstream step is wired; otherwise the worker
        # persists it unresolved and completes.
        context.record_decision(
            self.name,
            "source",
            candidate_index=index,
            tier=FDC_SOURCE,
            outcome="source_unavailable",
        )
        add_evidence_record(context, tier=FDC_SOURCE, outcome="source_unavailable")
        if _should_defer_after_source_gap(candidate, self.clarify_mode):
            self._record_deferral(context, index)
            context.pending_official_candidates.append(candidate)
            return
        context.record_decision(
            self.name, "outcome", candidate_index=index, outcome="unresolved_no_source"
        )
        context.unresolved_food_candidates.append(candidate)

    def _record_deferral(self, context: EstimationContext, index: int) -> None:
        """Trace that the candidate fell through to the official/reference step."""

        context.record_decision(
            self.name, "outcome", candidate_index=index, outcome="deferred_to_web_evidence"
        )

    def _try_barcode(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        barcode_resolver: BarcodeResolver,
        index: int,
    ) -> ResolvedFoodItem | None:
        """Resolve a barcode candidate from Open Food Facts; ``None`` on a miss.

        Raises :class:`StepError` / :class:`StepFailed` on a transient / non-retryable
        OFF error. In stricter modes, :meth:`_build_item` may still raise
        :class:`NeedsClarification` when the product matched but its quantity cannot
        be resolved to grams.
        """

        _record_source_ref(context, OFF_SOURCE)
        try:
            resolved = barcode_resolver.resolve_product(candidate.barcode or "")
        except OffTransientError as exc:
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=OFF_SOURCE,
                outcome="off_transient_error",
            )
            add_evidence_record(context, tier=OFF_SOURCE, outcome="off_transient_error")
            raise StepError("off_transient_error") from exc
        except OffResponseError as exc:
            # OFF answered unusably; fail closed rather than guess a number.
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=OFF_SOURCE,
                outcome="off_response_error",
            )
            add_evidence_record(context, tier=OFF_SOURCE, outcome="off_response_error")
            raise StepFailed("off_response_error") from exc

        if resolved is None:
            context.record_decision(
                self.name, "source", candidate_index=index, tier=OFF_SOURCE, outcome="miss"
            )
            add_evidence_record(context, tier=OFF_SOURCE, outcome="miss")
            return None
        return self._build_item(
            context,
            candidate,
            resolved,
            OFF_SOURCE_TYPE,
            candidate_index=index,
            allow_unresolvable_defer=_should_defer_unresolvable_quantity(
                candidate, self.clarify_mode
            ),
        )

    def _try_generic(
        self, context: EstimationContext, candidate: CandidateDraft, index: int
    ) -> ResolvedFoodItem | None:
        """Resolve a generic-food candidate by name from USDA FDC; ``None`` on a miss.

        The caller guarantees the source is enabled. Raises :class:`StepError` /
        :class:`StepFailed` on a transient / non-retryable FDC error, and
        in stricter modes, :class:`NeedsClarification` (via :meth:`_build_item`) on
        an unresolvable quantity.
        """

        _record_source_ref(context, FDC_SOURCE)
        try:
            resolved = self.resolver.resolve_product(candidate.name)
        except FdcTransientError as exc:
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=FDC_SOURCE,
                outcome="fdc_transient_error",
            )
            add_evidence_record(context, tier=FDC_SOURCE, outcome="fdc_transient_error")
            raise StepError("fdc_transient_error") from exc
        except FdcResponseError as exc:
            # The source answered unusably; fail closed rather than guess a number.
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=FDC_SOURCE,
                outcome="fdc_response_error",
            )
            add_evidence_record(context, tier=FDC_SOURCE, outcome="fdc_response_error")
            raise StepFailed("fdc_response_error") from exc

        if resolved is None:
            context.record_decision(
                self.name, "source", candidate_index=index, tier=FDC_SOURCE, outcome="miss"
            )
            add_evidence_record(context, tier=FDC_SOURCE, outcome="miss")
            return None
        if not is_evidence_brand_compatible(
            resolved.product.description, name=candidate.name, brand=candidate.brand
        ):
            # FTY-253: for a branded packaged product, a generic database hit is a
            # candidate, not an authority. A row naming a different product identity
            # (e.g. "DENNY'S, chicken strips" for brand=Compliments) is a miss, so
            # the branded official/reference/model-prior tiers run instead of
            # completing — or clarifying — from the wrong product. The rejected row's
            # ref and (global, non-user) description are traced so an audit can see
            # exactly which row was turned away (FTY-255).
            context.record_decision(
                self.name,
                "source",
                candidate_index=index,
                tier=FDC_SOURCE,
                source_ref=resolved.product.source_ref,
                source_desc=resolved.product.description,
                outcome="rejected_brand_mismatch",
            )
            add_evidence_record(
                context,
                tier=FDC_SOURCE,
                outcome="rejected_brand_mismatch",
                source_ref=resolved.product.source_ref,
                source_desc=resolved.product.description,
            )
            return None
        return self._build_item(
            context,
            candidate,
            resolved,
            _source_type(resolved.product.source),
            candidate_index=index,
            allow_unresolvable_defer=(
                _is_official_eligible(candidate)
                or _should_defer_unresolvable_quantity(candidate, self.clarify_mode)
            ),
        )

    def _build_item(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        resolved: _ResolvedProduct,
        source_type: str,
        *,
        candidate_index: int,
        allow_unresolvable_defer: bool,
    ) -> ResolvedFoodItem | None:
        """Apply deterministic serving math and build the resolved item + provenance."""

        product = resolved.product
        assumptions: tuple[str, ...] = ()
        grams = resolve_grams(
            unit=candidate.unit,
            amount=candidate.amount,
            quantity_text=candidate.quantity_text,
            default_serving_g=product.default_serving_g,
        )
        if grams is None:
            # FTY-254: a stated count of an everyday food ("one banana", "2 large
            # eggs") with no source serving size resolves via the documented
            # common-portion table instead of losing the trusted-database match.
            # The portion default is recorded as an explicit assumption so the
            # number stays visibly rough at the portion level and editable.
            portion = resolve_common_portion_grams(
                name=candidate.name,
                unit=candidate.unit,
                amount=candidate.amount,
                quantity_text=candidate.quantity_text,
            )
            if portion is not None:
                grams = portion.grams
                assumptions = (portion.assumption,)
        if grams is None:
            if allow_unresolvable_defer:
                context.record_decision(
                    self.name,
                    "source",
                    candidate_index=candidate_index,
                    tier=product.source,
                    source_ref=product.source_ref,
                    source_desc=product.description,
                    outcome="rejected_unresolvable_quantity",
                )
                add_evidence_record(
                    context,
                    tier=product.source,
                    outcome="rejected_unresolvable_quantity",
                    source_ref=product.source_ref,
                    source_desc=product.description,
                )
                return None
            context.record_decision(
                self.name,
                "outcome",
                candidate_index=candidate_index,
                tier=product.source,
                source_ref=product.source_ref,
                outcome="clarified_quantity",
            )
            context.clarification_questions = [ClarificationDraft(text=QUANTITY_QUESTION)]
            raise NeedsClarification("unresolvable_quantity")

        facts = NutritionFacts(
            calories=product.calories_per_100g,
            protein_g=product.protein_per_100g,
            carbs_g=product.carbs_per_100g,
            fat_g=product.fat_per_100g,
        )
        scaled = scale_facts(facts, grams)
        # Record the source that actually backed this resolution (covers a cache hit).
        _record_source_ref(context, product.source)
        context.record_decision(
            self.name,
            "source",
            candidate_index=candidate_index,
            tier=product.source,
            source_ref=product.source_ref,
            outcome="accepted",
        )
        add_evidence_record(
            context,
            tier=product.source,
            outcome="accepted",
            source_ref=product.source_ref,
        )
        product_id: uuid.UUID = product.id

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
            product_id=product_id,
            source_type=source_type,
            source_ref=product.source_ref,
            content_hash=product.content_hash,
            fetched_at=resolved.fetched_at,
            calories_per_100g=product.calories_per_100g,
            protein_per_100g=product.protein_per_100g,
            carbs_per_100g=product.carbs_per_100g,
            fat_per_100g=product.fat_per_100g,
            assumptions=assumptions,
        )


def _source_type(source: str) -> str:
    """Map a source system id to its source-hierarchy classification."""

    if source == FDC_SOURCE:
        return FDC_SOURCE_TYPE
    if source == OFF_SOURCE:
        return OFF_SOURCE_TYPE
    return source


def _should_defer_after_source_gap(
    candidate: CandidateDraft, clarify_mode: EstimatorClarifyMode
) -> bool:
    """Whether a source miss should fall through to rough estimation."""

    if clarify_mode == "estimate_first":
        return True
    return _is_resolution_deferrable(candidate)


def _should_defer_unresolvable_quantity(
    candidate: CandidateDraft, clarify_mode: EstimatorClarifyMode
) -> bool:
    """Whether an exact match that cannot be scaled should try rough estimation."""

    if clarify_mode == "estimate_first":
        return True
    if clarify_mode == "balanced":
        return _is_resolution_deferrable(candidate)
    return False
