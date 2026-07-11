"""The food-resolution product-cache / source-lookup layer (FTY-354 extraction).

The database-owning side of the food-resolution step (:mod:`app.estimator.food_step`):
each resolver owns the global ``products`` cache (read + get-or-create/refresh) and one
external source, so the step itself stays a thin orchestration over the resolvers plus
the pure serving math. Constructed by the worker (which holds the session) and injected
into the step.

- :class:`FoodResolver` resolves a generic food name against USDA FoodData Central
  (:class:`~app.estimator.fdc.FoodSource`), keyed by normalized query in the cache.
- :class:`BarcodeResolver` resolves a barcode against Open Food Facts
  (:class:`~app.estimator.off.BarcodeSource`), keyed by normalized barcode.

The cached row holds global source facts only (no user data); the worker references a
flushed row from a user-owned ``evidence_sources`` row on commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimator.fdc import (
    FDC_SOURCE,
    FoodSource,
    ProductFacts,
    RowFoodSource,
    normalize_query,
)
from app.estimator.fdc_ranking import (
    is_fdc_description_compatible,
    is_fdc_description_rank_stable,
)
from app.estimator.off import (
    OFF_SOURCE,
    BarcodeSource,
    normalize_barcode,
)
from app.models.food_sources import Product


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
    facts (no user data) in the session for the worker's commit; new cache rows are
    flushed so the worker can reference them from user-owned ``evidence_sources``.
    """

    def __init__(self, *, session: Session, source: FoodSource) -> None:
        self._session = session
        self._source = source

    @property
    def enabled(self) -> bool:
        """Whether the underlying source is configured and may be queried."""

        return self._source.enabled

    def resolve_product(self, name: str) -> _ResolvedProduct | None:
        """Return the cached/fetched product for ``name``, or ``None`` if no match."""

        return self.resolve_product_rows(name)[0]

    def resolve_product_rows(
        self, name: str
    ) -> tuple[_ResolvedProduct | None, tuple[ProductFacts, ...]]:
        """:meth:`resolve_product`, plus the rows the compatibility gate rejected.

        Same cache-first behavior: a cached row must still pass the FTY-254 gate,
        and a compatible but non-rank-stable row is re-fetched once so the ranked
        lookup can replace it (else the compatible cache row stands). The second
        element carries the bounded rejected rows a *fresh, matchless* source
        lookup surfaced (FTY-326 session consult) — empty on any cache-served or
        matched outcome and for a plain ``lookup``-only source. Propagates
        :class:`FdcTransientError` / :class:`FdcResponseError` for the step to route.
        """

        query_key = normalize_query(name)
        if not query_key:
            return None, ()

        cached = self._session.scalars(
            select(Product).where(Product.source == FDC_SOURCE, Product.query_key == query_key)
        ).one_or_none()
        cached_is_compatible = False
        if cached is not None:
            cached_is_compatible = is_fdc_description_compatible(query_key, cached.description)
            if cached_is_compatible and is_fdc_description_rank_stable(
                query_key, cached.description
            ):
                return _ResolvedProduct(product=cached, fetched_at=cached.updated_at), ()

        if isinstance(self._source, RowFoodSource):
            rows = self._source.lookup_rows(name)
            facts, rejected = rows.match, rows.rejected
        else:
            facts, rejected = self._source.lookup(name), ()
        if facts is None:
            if cached is not None and cached_is_compatible:
                return _ResolvedProduct(product=cached, fetched_at=cached.updated_at), ()
            return None, rejected
        if cached is not None:
            return _ResolvedProduct(
                product=_refresh_product(cached, facts), fetched_at=datetime.now(UTC)
            ), ()
        return _ResolvedProduct(
            product=_cache_product(self._session, facts), fetched_at=datetime.now(UTC)
        ), ()


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
