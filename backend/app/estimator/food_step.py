"""The generic-food resolution step (FTY-044).

The third real estimation pipeline step. It takes the food candidates the parse
step (FTY-042) extracted and resolves each into canonical calories and macros,
sourced from a trusted nutrition database (USDA FDC) with deterministic serving
math. Exercise candidates are left untouched (resolution is FTY-043).

A :class:`FoodResolver` owns the side of resolution that needs the database — the
global ``products`` cache — and the external :class:`~app.estimator.fdc.FoodSource`.
It is constructed by the worker (which holds the session) and injected into the
step; the step itself stays a thin orchestration over the resolver plus the pure
serving math (:mod:`app.estimator.food_serving`).

Routing follows FTY-042/043 conventions:

- **all candidates resolve** → record :class:`~app.estimator.pipeline.ResolvedFoodItem`
  results on the context; the worker persists them ``resolved`` with calories/macros,
  caches the source facts as ``products``, and writes an ``evidence_sources`` row per
  item, then completes the event.
- **source unconfigured** → no-op: with no FDC key the source is disabled, so food
  candidates stay ``unresolved`` (the offline bundled-dataset fallback is a documented
  deferral). The event still completes.
- **no confident source match** / **unresolvable quantity** → raise
  :class:`~app.estimator.pipeline.NeedsClarification`; the food is recognisable but
  cannot be costed confidently, so the user is asked rather than guessed (terminal).
- **transient source failure** → raise :class:`~app.estimator.pipeline.StepError`
  (retryable); a **non-retryable source error** → :class:`StepFailed` (fail closed).

The nutrition facts are never taken from the model — only from the trusted source —
and the run records the source reference as evidence, never any raw page, the API
key, or raw user text (security baseline + ``docs/security/data-retention.md``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimator.fdc import (
    FDC_SOURCE,
    FDC_SOURCE_TYPE,
    FdcResponseError,
    FdcTransientError,
    FoodSource,
    ProductFacts,
    normalize_query,
)
from app.estimator.food_serving import NutritionFacts, resolve_grams, scale_facts
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
    StepError,
    StepFailed,
)
from app.models.food_sources import Product

#: Fixed, sanitized clarification questions used in place of any raw user text, so a
#: ``needs_clarification`` outcome always carries a question for the later answer flow.
UNKNOWN_FOOD_QUESTION = "Which food was that? We couldn't find a nutrition match."
QUANTITY_QUESTION = "How much did you have (for example, in grams, millilitres, or servings)?"


@dataclass(frozen=True)
class _ResolvedProduct:
    """A cached :class:`Product` row plus the time its facts were obtained."""

    product: Product
    fetched_at: datetime


class FoodResolver:
    """Resolves a food name to a cached :class:`Product`, fetching on a cache miss.

    Owns the global ``products`` cache (read + get-or-create) and the external
    :class:`FoodSource`. A cache hit avoids any external call; a miss fetches from the
    source and caches the global facts (no user data) in the session for the worker's
    commit. New cache rows are flushed so the worker can reference them from the
    user-owned ``evidence_sources`` it writes on success.
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
        source and caches the result. Propagates :class:`FdcTransientError` /
        :class:`FdcResponseError` from the source for the step to route.
        """

        query_key = normalize_query(name)
        if not query_key:
            return None

        cached = self._session.scalars(
            select(Product).where(Product.source == FDC_SOURCE, Product.query_key == query_key)
        ).one_or_none()
        if cached is not None:
            return _ResolvedProduct(product=cached, fetched_at=cached.updated_at)

        facts = self._source.lookup(name)
        if facts is None:
            return None
        return _ResolvedProduct(product=self._cache(facts), fetched_at=datetime.now(UTC))

    def _cache(self, facts: ProductFacts) -> Product:
        """Insert ``facts`` as a global ``products`` row and flush to assign its id."""

        product = Product(
            source=facts.source,
            source_ref=facts.source_ref,
            query_key=facts.query_key,
            description=facts.description,
            calories_per_100g=facts.facts.calories,
            protein_per_100g=facts.facts.protein_g,
            carbs_per_100g=facts.facts.carbs_g,
            fat_per_100g=facts.facts.fat_g,
            default_serving_g=facts.default_serving_g,
            content_hash=facts.content_hash,
        )
        self._session.add(product)
        self._session.flush()
        return product


@dataclass(frozen=True)
class FoodResolveStep:
    """Resolve the parsed food candidates into calories/macros from a trusted source."""

    resolver: FoodResolver
    name: str = "food_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        if not context.food_candidates:
            # Nothing to resolve (e.g. an exercise-only event). No source consulted.
            context.record_step(self.name, "ok")
            return

        if not self.resolver.enabled:
            # No FDC key configured: leave food candidates unresolved rather than
            # guess. A documented deferral (offline bundled dataset).
            context.record_step(self.name, "skipped")
            return

        self._record_evidence_meta(context)

        for candidate in context.food_candidates:
            context.resolved_food_items.append(self._resolve(context, candidate))

        context.record_step(self.name, "ok")

    def _resolve(self, context: EstimationContext, candidate: CandidateDraft) -> ResolvedFoodItem:
        """Resolve one candidate, mapping source/quantity failures to pipeline signals."""

        try:
            resolved = self.resolver.resolve_product(candidate.name)
        except FdcTransientError as exc:
            raise StepError("fdc_transient_error") from exc
        except FdcResponseError as exc:
            # The source answered unusably; fail closed rather than guess a number.
            raise StepFailed("fdc_response_error") from exc

        if resolved is None:
            context.clarification_questions = [UNKNOWN_FOOD_QUESTION]
            raise NeedsClarification("unknown_food")

        product = resolved.product
        grams = resolve_grams(
            unit=candidate.unit,
            amount=candidate.amount,
            quantity_text=candidate.quantity_text,
            default_serving_g=product.default_serving_g,
        )
        if grams is None:
            context.clarification_questions = [QUANTITY_QUESTION]
            raise NeedsClarification("unresolvable_quantity")

        facts = NutritionFacts(
            calories=product.calories_per_100g,
            protein_g=product.protein_per_100g,
            carbs_g=product.carbs_per_100g,
            fat_g=product.fat_per_100g,
        )
        scaled = scale_facts(facts, grams)
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
            source_type=_source_type(product.source),
            source_ref=product.source_ref,
            content_hash=product.content_hash,
            fetched_at=resolved.fetched_at,
            calories_per_100g=product.calories_per_100g,
            protein_per_100g=product.protein_per_100g,
            carbs_per_100g=product.carbs_per_100g,
            fat_per_100g=product.fat_per_100g,
        )

    @staticmethod
    def _record_evidence_meta(context: EstimationContext) -> None:
        """Record the source system as run evidence (content-free metadata only)."""

        if FDC_SOURCE not in context.source_refs:
            context.source_refs.append(FDC_SOURCE)


def _source_type(source: str) -> str:
    """Map a source system id to its source-hierarchy classification."""

    if source == FDC_SOURCE:
        return FDC_SOURCE_TYPE
    return source
