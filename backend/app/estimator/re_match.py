"""Item re-match capability: list alternative sources + re-resolve (FTY-093).

The "Change match" lever of the correction sheet: a user whose entry matched the
**wrong food** (Slacks heard "turkey", matched chicken) fixes it without
delete-and-retype. This estimator-boundary capability owns the two cohesive halves
of that one capability:

- **List alternatives** (:meth:`ReMatchCapability.list_alternatives`) — runs the
  existing resolution providers in a *list-candidates* mode that surfaces multiple
  energy-bearing matches for the item's identity (USDA FoodData Central, plus an
  optional caller-supplied query override for the corrected term). Every surfaced
  candidate's facts are extracted/validated **server-side** and cached into the
  global ``products`` cache, addressable by its stable ``source_ref`` — that cache is
  the trust anchor the write half re-derives from.
- **Re-resolve** (:meth:`ReMatchCapability.re_resolve`) — takes the item plus a
  **chosen candidate reference** (never caller-supplied facts) and re-aims the item
  to it: it re-derives the chosen source's facts **server-side from the cache** (so
  the client cannot inject nutrition values and re-resolve issues **no** fresh
  network egress), recomputes calories/macros at the item's *current* portion with
  the FTY-044 serving math, rewrites the item's ``evidence_sources`` provenance to
  the new source, and **re-snapshots** the ``*_estimated`` originals to the newly
  computed values.

A re-match is a **fresh source-backed estimate, not a manual override**: the item is
**not** marked ``user_edited`` and **no** ``user_edit`` correction row is written (the
deliberate divergence from the FTY-051 "captured once" rule, which governs value
overrides). It instead appends an immutable ``re_match`` audit row that records the
re-match and **supersedes** any pre-existing ``user_edit`` — so an edited-then-rematched
item honestly reads ``is_edited == false`` again (the new source carries the truth, not
the stale override). The item keeps its ``id``, ``log_event_id``, name slot, and timeline
position; only its source, numbers, and snapshot change.

Security posture (rated **high**): egress flows only through the existing hardened
source clients during the *listing* step; re-resolve performs no fetch at all. Both
operations load the item scoped to the owning user and fail closed (a cross-user or
unknown item is indistinguishable from a missing one). Only an item-identity query
egresses, through the FTY-079 ``sanitize_query`` chokepoint — never profile, body
metrics, goals, history, or account identifiers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import CandidateType, CorrectionSource, DerivedItemStatus
from app.estimator.fdc import (
    FDC_SOURCE,
    FDC_SOURCE_TYPE,
    FdcResponseError,
    FdcTransientError,
    ProductFacts,
    build_fdc_client,
)
from app.estimator.food_serving import (
    NutritionFacts,
    ScaledNutrition,
    resolve_grams,
    scale_facts,
)
from app.estimator.off import OFF_SOURCE, OFF_SOURCE_TYPE
from app.estimator.search import OFFICIAL_SOURCE, OFFICIAL_SOURCE_TYPE, sanitize_query
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE, MODEL_PRIOR_SOURCE_TYPE
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product
from app.models.identity import User

#: Canonical basis every surfaced candidate is expressed against. The providers
#: canonicalise to per-100g facts during listing, so a candidate's facts preview is
#: always per 100 g; the field is explicit so the client can label the preview.
PER_100G_BASIS: Final[str] = "per_100g"

#: Upper bound on the aggregated candidate list. The provider fan-out is already
#: bounded (``SLACKS_FDC_MAX_RESULTS``); this caps the combined result so the listing
#: stays a short, scannable set even as more candidate providers are added.
MAX_ALTERNATIVES: Final[int] = 10

#: Fixed, sanitized clarification question used when the chosen source cannot cost the
#: item's current quantity **and** the item carries no usable portion mass to fall back
#: on — surfaced in place of any raw user text, mirroring the FTY-044
#: ``unresolvable_quantity`` routing (ask, never fabricate a number).
QUANTITY_QUESTION = "How much did you have (for example, in grams, millilitres, or servings)?"

#: Content-free assumption label recorded on the rewritten evidence row when a re-match
#: costs the item via its **carried portion grams** (FTY-386): the chosen source could
#: not cost the count/quantity itself (no serving size), so the portion mass the item's
#: prior resolution already estimated is carried forward and only the density source
#: changes. A fixed token — never the item name, quantity text, or any nutrition value —
#: so the provenance honestly says the portion mass predates the new source.
PORTION_GRAMS_CARRIED_ASSUMPTION: Final[str] = "portion_grams_carried"

#: Map a source-system id to its evidence source-hierarchy classification. Covers
#: every system a cached candidate could carry so a re-derived ``products`` row is
#: written back to ``evidence_sources`` with the correct ``source_type``.
_SOURCE_TYPES: Final[dict[str, str]] = {
    FDC_SOURCE: FDC_SOURCE_TYPE,
    OFF_SOURCE: OFF_SOURCE_TYPE,
    OFFICIAL_SOURCE: OFFICIAL_SOURCE_TYPE,
    MODEL_PRIOR_SOURCE: MODEL_PRIOR_SOURCE_TYPE,
}


class ItemForbidden(Exception):
    """Raised when a caller targets a re-match operation at an item they do not own."""


class ItemNotFound(Exception):
    """Raised when no food item of the requested id exists for the owner.

    A cross-user id is loaded scoped to the owner, so it is indistinguishable from a
    missing one — both raise this and the router renders ``404`` (no existence oracle).
    """


class AlternativesUnavailable(Exception):
    """Raised when a candidate source fails transiently/unusably while listing.

    A provider's source lookup failed during listing — a timeout / 5xx
    (:class:`~app.estimator.fdc.FdcTransientError`) or an unusable response
    (:class:`~app.estimator.fdc.FdcResponseError`) — so the listing cannot be
    completed. The router surfaces this as a retryable ``503`` rather than a
    **misleading empty list** (which is reserved for genuinely no candidates / no
    enabled source). This mirrors the estimator's transient/response routing
    (``food_step.py``): a source that cannot answer is failed closed, never guessed
    around or silently dropped to "nothing found".
    """


class SourceNotResolvable(Exception):
    """Raised when the chosen candidate reference cannot be re-derived server-side.

    The reference does not correspond to a server-cached candidate (it was never
    surfaced by a listing step, or is otherwise unknown), so re-resolve refuses to act
    and nothing mutates. The trust anchor: the server only re-aims to a source whose
    facts it can produce itself, never to caller-supplied values.
    """

    def __init__(self, source_ref: str) -> None:
        super().__init__("chosen source reference is not re-derivable")
        self.source_ref = source_ref


class ReMatchNeedsClarification(Exception):
    """Raised when the chosen source cannot cost the item's current quantity.

    The new source carries no serving size that resolves the item's count/quantity to
    grams **and** the item carries no usable portion mass (``grams`` is ``None`` or
    non-positive) to fall back on, so the re-match routes to clarification rather than
    fabricate a number (consistent with FTY-044 ``needs_clarification`` routing). Since
    FTY-386 this residual is narrow: a count item whose prior resolution already
    estimated a portion mass is costed via that carried mass instead of clarified.
    Nothing mutates.
    """

    def __init__(self, question: str) -> None:
        super().__init__("re-match cannot cost the current quantity")
        self.question = question


def apply_resolved_facts(item: DerivedFoodItem, scaled: ScaledNutrition) -> None:
    """Write a fresh source-backed estimate onto ``item`` (re-resolution semantics).

    Sets the item ``resolved`` and overwrites its editable current
    calories/macros/grams **and** re-snapshots the ``*_estimated`` originals to the
    same newly-computed values. This is the deliberate divergence from the FTY-051
    captured-once rule (which governs ``user_edit`` overrides): a re-resolution — a
    "Change match" (FTY-093) or an exact-evidence apply (FTY-307) — is a new
    estimate, so the estimated snapshot moves with it. Shared by both levers so the
    write semantics cannot drift between them.
    """

    item.status = DerivedItemStatus.RESOLVED
    item.grams = scaled.grams
    item.calories = scaled.calories
    item.protein_g = scaled.protein_g
    item.carbs_g = scaled.carbs_g
    item.fat_g = scaled.fat_g
    item.calories_estimated = scaled.calories
    item.protein_g_estimated = scaled.protein_g
    item.carbs_g_estimated = scaled.carbs_g
    item.fat_g_estimated = scaled.fat_g


def record_re_match_correction(
    session: Session,
    item: DerivedFoodItem,
    *,
    old_calories: float | None,
    new_calories: float,
) -> Correction:
    """Append the immutable ``re_match`` audit row that reconciles a prior edit.

    A re-resolution is **not** a value override, so this row is tagged
    :attr:`~app.enums.CorrectionSource.RE_MATCH`, never ``user_edit`` — the item is
    still not ``user_edited``. Its purpose is twofold: it records the re-resolution in
    the append-only audit trail (the calories change to the new source), and it
    **supersedes** any prior ``user_edit`` so the FTY-092 ``is_edited`` read returns to
    ``false`` (only an edit *after* this row counts). The marker is keyed on
    ``calories``, the item's headline value; the full new numbers live on the item and
    the rewritten ``evidence_sources`` snapshot. Shared by "Change match" (FTY-093) and
    the exact-evidence apply (FTY-307), which the corrections contract fixes as the same
    audit semantics. Added to ``session`` but not committed — the caller commits the
    item update and this row together.
    """

    correction = Correction(
        user_id=item.user_id,
        item_type=CandidateType.FOOD,
        derived_food_item_id=item.id,
        field="calories",
        old_value=old_calories,
        new_value=new_calories,
        source=CorrectionSource.RE_MATCH,
    )
    session.add(correction)
    return correction


@dataclass(frozen=True)
class SourceCandidate:
    """One alternative source match surfaced for an existing food item.

    A bounded, energy-bearing candidate the client can offer as a "Change match"
    choice: its source classification + stable reference, a display name, the basis its
    facts are expressed against, and the canonical per-100g facts (the compact preview
    plus the values re-resolve recomputes from). ``source`` is the originating
    source-system id used to cache and later re-derive the candidate. Never carries the
    user's portion or any personal context — only the global source facts.
    """

    source: str
    source_type: str
    source_ref: str
    name: str
    basis: str
    facts: NutritionFacts
    default_serving_g: float | None
    content_hash: str


@runtime_checkable
class CandidateProvider(Protocol):
    """A provider that lists alternative source candidates for an identity query.

    The list-candidates seam: each provider runs an existing hardened resolution
    source in *list mode* (surfacing multiple matches rather than the resolver's first
    pick) and maps them to :class:`SourceCandidate`. Adding a provider (e.g. the
    optional official-source search fallback) means registering another implementation
    here — the capability's listing, caching, and re-resolve are provider-agnostic.
    """

    def list_candidates(self, query: str) -> list[SourceCandidate]:
        """Return energy-bearing candidates for the sanitized ``query`` (may be empty)."""
        ...


@runtime_checkable
class FoodListSource(Protocol):
    """A name-keyed food source that lists multiple energy-bearing matches.

    The USDA FDC client (:class:`~app.estimator.fdc.FdcClient`) satisfies this via its
    ``list_matches``; tests inject a network-free fake of the same shape.
    """

    @property
    def enabled(self) -> bool:
        """Whether the source is configured and may be queried."""
        ...

    def list_matches(self, query: str) -> list[ProductFacts]:
        """Return every energy-bearing match for ``query`` (empty when disabled/no match)."""
        ...


@dataclass(frozen=True)
class UsdaCandidateProvider:
    """List alternative USDA FoodData Central matches for a food identity (FTY-093).

    Wraps the FTY-044 USDA client's ``list_matches`` — the same hardened, allowlisted,
    sanitized-name path the resolver already uses — surfacing *every* energy-bearing
    match instead of only the first. A disabled source (no API key) yields no candidates.
    """

    client: FoodListSource

    def list_candidates(self, query: str) -> list[SourceCandidate]:
        return [_candidate_from_facts(facts) for facts in self.client.list_matches(query)]


def _candidate_from_facts(facts: ProductFacts) -> SourceCandidate:
    """Map cached/fetched :class:`ProductFacts` to a :class:`SourceCandidate`."""

    return SourceCandidate(
        source=facts.source,
        source_type=_source_type(facts.source),
        source_ref=facts.source_ref,
        name=facts.description,
        basis=PER_100G_BASIS,
        facts=facts.facts,
        default_serving_g=facts.default_serving_g,
        content_hash=facts.content_hash,
    )


def _source_type(source: str) -> str:
    """Classify a source-system id into the evidence hierarchy (``source`` itself if unknown)."""

    return _SOURCE_TYPES.get(source, source)


@dataclass(frozen=True)
class ReMatchCapability:
    """List-alternatives + re-resolve over an existing food item (FTY-093).

    Owns the object-level-scoped item load, the provider fan-out + server-side
    candidate caching for listing, and the deterministic recompute + provenance rewrite
    for re-resolve. Constructed per request by the thin backend operation, which injects
    the session and the candidate providers; tests inject network-free fakes.
    """

    session: Session
    providers: tuple[CandidateProvider, ...]
    max_alternatives: int = MAX_ALTERNATIVES

    def list_alternatives(
        self,
        *,
        owner_id: uuid.UUID,
        current_user: User,
        item_id: uuid.UUID,
        query_override: str | None = None,
    ) -> list[SourceCandidate]:
        """List bounded alternative source candidates for ``owner_id``'s food item.

        Runs every registered provider over the sanitized identity query — the
        caller-supplied ``query_override`` (the corrected term) when given, else the
        item's own name — collecting energy-bearing candidates up to
        :attr:`max_alternatives`. Each candidate is cached into the global ``products``
        cache (addressable by ``source_ref``) so the write half can re-derive it with no
        fresh fetch. The query passes through the FTY-079 ``sanitize_query`` chokepoint;
        only item identity egresses. A provider that fails transiently or answers
        unusably raises :class:`AlternativesUnavailable` (router → ``503``) rather than
        degrading to a misleading empty list.
        """

        self._authorize(owner_id, current_user)
        item = self._load_owned(item_id, owner_id)

        query = sanitize_query(query_override if query_override is not None else item.name)
        if not query:
            return []

        candidates: list[SourceCandidate] = []
        seen: set[str] = set()
        for provider in self.providers:
            # A source that fails transiently/unusably during listing fails the whole
            # operation to a retryable 503 — never a misleading "no candidates" list.
            try:
                provider_candidates = provider.list_candidates(query)
            except (FdcTransientError, FdcResponseError) as exc:
                raise AlternativesUnavailable("candidate source unavailable") from exc
            for candidate in provider_candidates:
                if candidate.source_ref in seen:
                    continue
                seen.add(candidate.source_ref)
                self._cache_candidate(candidate)
                candidates.append(candidate)
                if len(candidates) >= self.max_alternatives:
                    self.session.commit()
                    return candidates
        self.session.commit()
        return candidates

    def re_resolve(
        self,
        *,
        owner_id: uuid.UUID,
        current_user: User,
        item_id: uuid.UUID,
        source_ref: str,
    ) -> DerivedFoodItem:
        """Re-aim ``owner_id``'s food item to the chosen candidate ``source_ref``.

        Re-derives the chosen source's facts **server-side** from the global cache (a
        reference that does not resolve to a cached candidate is rejected, nothing
        mutates), recomputes calories/macros at the item's *current* portion, rewrites
        the item's ``evidence_sources`` provenance to the new source, and re-snapshots
        the ``*_estimated`` originals to the new computed values. The item is **not**
        marked ``user_edited`` and no ``user_edit`` correction is written; instead a
        ``re_match`` audit row is appended that supersedes any prior ``user_edit`` (so the
        item's ``is_edited`` returns to ``false``). Issues no network egress.

        Costing follows the FTY-093 order, extended by FTY-386: the chosen source costs
        the current quantity itself when it can; otherwise the item's already-resolved
        portion ``grams`` is carried forward (recording the content-free
        :data:`PORTION_GRAMS_CARRIED_ASSUMPTION` label) so a count item against a
        serving-less source still completes; only when neither is possible (``grams`` is
        ``None``/non-positive) does it raise :class:`ReMatchNeedsClarification` — never a
        fabricated number.
        """

        self._authorize(owner_id, current_user)
        item = self._load_owned(item_id, owner_id)

        product = self._lookup_cached(source_ref)
        if product is None:
            raise SourceNotResolvable(source_ref)

        # Costing order (FTY-093 preference, extended by FTY-386):
        # 1. the chosen source costs the current quantity itself (its serving size /
        #    the quantity's own mass or volume) — unchanged first preference;
        # 2. else carry the item's already-resolved portion grams forward (FTY-386):
        #    a count item whose prior resolution estimated "1 sandwich ≈ N g" keeps
        #    that N — only the density source changes, never a fabricated number;
        # 3. else the item has no usable portion mass to fall back on → clarify.
        grams = resolve_grams(
            unit=item.unit,
            amount=item.amount,
            quantity_text=item.quantity_text,
            default_serving_g=product.default_serving_g,
        )
        carried_grams = False
        if grams is None:
            if item.grams is not None and item.grams > 0:
                grams = item.grams
                carried_grams = True
            else:
                raise ReMatchNeedsClarification(QUANTITY_QUESTION)

        facts = NutritionFacts(
            calories=product.calories_per_100g,
            protein_g=product.protein_per_100g,
            carbs_g=product.carbs_per_100g,
            fat_g=product.fat_per_100g,
        )
        scaled = scale_facts(facts, grams)

        prior_calories = item.calories
        apply_resolved_facts(item, scaled)
        self._rewrite_evidence(item, product, carried_grams=carried_grams)
        record_re_match_correction(
            self.session, item, old_calories=prior_calories, new_calories=scaled.calories
        )

        self.session.commit()
        self.session.refresh(item)
        return item

    def _cache_candidate(self, candidate: SourceCandidate) -> Product:
        """Persist a surfaced candidate's facts as a global ``products`` row.

        The row is addressable by ``source_ref`` so re-resolve can re-derive the facts
        without a fresh fetch. Reuses an existing row for the same ``(source,
        source_ref)`` (idempotent listing); a new row is keyed by ``source_ref`` so
        several candidates from one search never collide on the name-based
        ``(source, query_key)`` uniqueness. Holds global source facts only (no user data).
        """

        existing = self.session.scalars(
            select(Product).where(
                Product.source == candidate.source,
                Product.source_ref == candidate.source_ref,
            )
        ).first()
        if existing is not None:
            return existing

        product = Product(
            source=candidate.source,
            source_ref=candidate.source_ref,
            query_key=candidate.source_ref,
            barcode=None,
            description=candidate.name,
            calories_per_100g=candidate.facts.calories,
            protein_per_100g=candidate.facts.protein_g,
            carbs_per_100g=candidate.facts.carbs_g,
            fat_per_100g=candidate.facts.fat_g,
            default_serving_g=candidate.default_serving_g,
            content_hash=candidate.content_hash,
        )
        self.session.add(product)
        self.session.flush()
        return product

    def _lookup_cached(self, source_ref: str) -> Product | None:
        """Return the cached candidate for ``source_ref``, or ``None`` if not re-derivable.

        Looks the chosen reference up in the global ``products`` cache. A hit is a real,
        server-derived source the listing step (or an earlier resolution) validated and
        stored; a miss means the server cannot re-derive the chosen source, so re-resolve
        rejects it. Facts come only from the cache — never from the caller.
        """

        return self.session.scalars(select(Product).where(Product.source_ref == source_ref)).first()

    def _rewrite_evidence(
        self, item: DerivedFoodItem, product: Product, *, carried_grams: bool
    ) -> None:
        """Rewrite the item's ``evidence_sources`` provenance to the chosen source.

        Updates the item's existing evidence row in place (or creates one if absent) so
        the item keeps a single provenance record now pointing at the new source: the
        ``source_type`` / ``source_ref`` / ``content_hash`` / ``fetched_at`` / immutable
        per-100g snapshot / ``product_id`` link. ``assumptions`` records the content-free
        :data:`PORTION_GRAMS_CARRIED_ASSUMPTION` label when the quantity was costed via
        the item's carried portion grams (FTY-386 — the portion mass predates the new
        source), and is otherwise **cleared** — a re-match a database source could cost
        itself carries no assumption, exactly as before. ``basis`` is reset to
        ``per_100g`` — the chosen candidate is always a :class:`Product`, whose density
        facts are always per-100g, so the basis label must agree with the snapshot this
        rewrite writes (FTY-316) rather than carry over a stale ``as_logged``/
        ``per_serving`` basis. ``field_provenance`` is reset to ``None`` — a single
        database source gives every field a homogeneous origin, so a stale per-field
        origin map must not survive onto the new snapshot.
        """

        evidence = self.session.scalars(
            select(EvidenceSource)
            .where(EvidenceSource.derived_food_item_id == item.id)
            .order_by(EvidenceSource.created_at.desc())
        ).first()
        if evidence is None:
            evidence = EvidenceSource(
                user_id=item.user_id,
                log_event_id=item.log_event_id,
                derived_food_item_id=item.id,
            )
            self.session.add(evidence)

        evidence.product_id = product.id
        evidence.source_type = _source_type(product.source)
        evidence.source_ref = product.source_ref
        evidence.content_hash = product.content_hash
        evidence.fetched_at = datetime.now(UTC)
        evidence.basis = PER_100G_BASIS
        evidence.calories_per_100g = product.calories_per_100g
        evidence.protein_per_100g = product.protein_per_100g
        evidence.carbs_per_100g = product.carbs_per_100g
        evidence.fat_per_100g = product.fat_per_100g
        evidence.field_provenance = None
        evidence.assumptions = [PORTION_GRAMS_CARRIED_ASSUMPTION] if carried_grams else None

    @staticmethod
    def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
        """Fail closed unless ``current_user`` owns ``owner_id``'s items."""

        if owner_id != current_user.id:
            raise ItemForbidden("cross-user re-match denied")

    def _load_owned(self, item_id: uuid.UUID, owner_id: uuid.UUID) -> DerivedFoodItem:
        """Load a food item by id scoped to ``owner_id`` so a cross-user id 404s."""

        item = self.session.scalars(
            select(DerivedFoodItem).where(
                DerivedFoodItem.id == item_id,
                DerivedFoodItem.user_id == owner_id,
            )
        ).one_or_none()
        if item is None:
            raise ItemNotFound("derived food item not found")
        return item


def build_re_match_capability(session: Session) -> ReMatchCapability:
    """Build the default re-match capability from environment-loaded providers.

    Wires the USDA candidate provider (FTY-044 client, disabled without an API key,
    yielding no candidates) over ``session``. Building the client makes no network call.
    The thin backend operation calls this per request; tests construct
    :class:`ReMatchCapability` directly with network-free providers.
    """

    provider = UsdaCandidateProvider(build_fdc_client())
    return ReMatchCapability(session=session, providers=(provider,))
