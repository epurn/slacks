"""Barcode exact-evidence proposal generation for an existing item (FTY-308).

The **barcode** source-specific generator for the ``Make it exact`` lever
(``docs/contracts/evidence-retrieval.md`` — **Exact Evidence Upgrade — FTY-306**;
``docs/contracts/food-resolution.md`` — **Exact Evidence Upgrade Routing**). FTY-307
owns the generic apply half (the signed ``proposal_ref`` trust anchor + in-place
source replacement); this module owns turning a typed/scanned UPC/EAN barcode and an
existing low-trust food item into a **proposal** the user previews and applies:

- A confident Open Food Facts match (resolved through the *existing* hardened,
  cache-first :class:`~app.estimator.food_resolvers.BarcodeResolver` — no second
  barcode nutrition mapper) yields an **exact** ``product_database`` proposal.
- When OFF has no usable exact match (no product, disabled/unavailable source, or
  facts the existing plausibility gate rejects), the item's own identity is handed to
  the injected estimator :class:`IdentityFallbackSource`; if it can produce a
  low-trust estimate the result is a clearly-labelled **fallback** proposal carrying
  its honest ``reference_source`` / ``model_prior`` provenance and a content-free
  ``failure_reason`` naming the barcode problem — never masquerading as exact.
- When neither an exact match nor a fallback can be produced, the outcome carries no
  proposal (a calm, content-free reason) — the caller returns a no-proposal response.

This module is pure generation: it loads no item, opens no socket of its own, and
**never mutates** the target item. The item changes only when the user applies the
returned proposal through FTY-307. Egress is barcode-only (OFF) or sanitized
item-identity-only (the fallback) — no profile, history, raw log text, target, body
metrics, or account context leaves the server (``docs/security/security-baseline.md``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from app.enums import ExactEvidenceKind, ExactEvidenceQuality, SourceType
from app.estimator.exact_evidence import (
    PER_100G_BASIS,
    PROPOSAL_TTL_SECONDS,
    ExactEvidenceProposal,
    ProposalFacts,
    build_proposal,
)
from app.estimator.food_resolvers import _ResolvedProduct
from app.estimator.food_serving import NutritionFacts
from app.estimator.identity_sanitizer import sanitized_identity
from app.estimator.off import OffMissReason, normalize_barcode
from app.models.derived import DerivedFoodItem

#: Closed, content-free ``failure_reason`` labels a barcode fallback / no-proposal
#: outcome carries, naming *why* the exact barcode match was not usable
#: (``docs/contracts/evidence-retrieval.md`` — Exact Evidence Upgrade; the barcode
#: vocabulary is fixed here per FTY-306/FTY-308). They never carry a raw OFF payload, a
#: URL with secrets, or any nutrition value — only the bounded reason class.
#:
#: - ``barcode_invalid`` — the string is not a plausible GTIN after normalization
#:   (untrusted user input, not a source failure);
#: - ``barcode_no_match`` — OFF (cache or live, by barcode only) has no product for the
#:   barcode (a genuine miss);
#: - ``no_usable_facts`` — OFF returned a product, but its facts are unusable/implausible
#:   (no energy on a usable basis, or the existing plausibility gate rejected them);
#: - ``source_unavailable`` — OFF is disabled/unavailable by self-host config.
#:
#: A *transient/terminal* OFF **error** (timeout/5xx/4xx/policy) is **not** a
#: ``failure_reason`` here: it propagates from the resolver so the route surfaces a
#: retryable ``503`` rather than disguising a source outage as an honest miss/fallback
#: (``docs/contracts/food-resolution.md`` — Exact Evidence Upgrade Routing, Errors).
FAILURE_INVALID: Final = "barcode_invalid"
FAILURE_NO_MATCH: Final = "barcode_no_match"
FAILURE_NO_USABLE_FACTS: Final = "no_usable_facts"
FAILURE_SOURCE_UNAVAILABLE: Final = "source_unavailable"

#: Map an OFF miss reason to its closed FTY-308 ``failure_reason`` label.
_MISS_REASON_FAILURE: Final[dict[OffMissReason, str]] = {
    OffMissReason.NO_MATCH: FAILURE_NO_MATCH,
    OffMissReason.NO_USABLE_FACTS: FAILURE_NO_USABLE_FACTS,
}


@dataclass(frozen=True)
class FallbackFacts:
    """A low-trust estimate the item's identity produced when OFF had no exact match.

    Server-generated per-100g facts plus the *honest* low-trust provenance the applied
    item will carry — never ``product_database`` / ``user_label``. ``assumptions`` are
    content-free labels (no raw text / provider payload / URL). Returned by an
    :class:`IdentityFallbackSource`.
    """

    facts: NutritionFacts
    source_type: str
    source_ref: str
    content_hash: str
    default_serving_g: float | None = None
    serving_label: str | None = None
    assumptions: tuple[str, ...] = ()
    field_provenance: dict[str, str] | None = None


@runtime_checkable
class BarcodeExactSource(Protocol):
    """The cache-first OFF barcode source the generator queries for an exact match.

    Structurally the existing :class:`~app.estimator.food_resolvers.BarcodeResolver`
    (a cache hit makes no external call; a miss queries OFF by barcode only). Modelled
    as a Protocol so tests inject a network-free fake with the same shape.
    """

    @property
    def enabled(self) -> bool:
        """Whether the underlying OFF source is enabled and may be queried."""
        ...

    def resolve_product_outcome(
        self, barcode: str
    ) -> tuple[_ResolvedProduct | None, OffMissReason | None]:
        """Return ``(product, None)`` for a match, or ``(None, reason)`` for a miss.

        The miss ``reason`` distinguishes a genuine miss
        (:attr:`~app.estimator.off.OffMissReason.NO_MATCH`) from a found-but-unusable
        product (:attr:`~app.estimator.off.OffMissReason.NO_USABLE_FACTS`). Raises
        :class:`~app.estimator.off.OffTransientError` /
        :class:`~app.estimator.off.OffResponseError` on a source failure.
        """
        ...


@runtime_checkable
class IdentityFallbackSource(Protocol):
    """The estimator fallback that estimates from the item's sanitized identity.

    Receives item identity only (never profile, history, or raw log text) and returns
    an honestly low-trust :class:`FallbackFacts`, or ``None`` when no estimator source
    can produce one. The real implementation is
    :class:`~app.estimator.identity_fallback.IdentityFallbackResolver`.
    """

    def resolve(self, identity: str) -> FallbackFacts | None:
        """Estimate ``identity`` from the estimator fallback tiers, or ``None``."""
        ...


@dataclass(frozen=True)
class BarcodeProposalOutcome:
    """The result of a barcode proposal attempt.

    ``proposal`` is the server-held exact/fallback proposal the caller signs into an
    opaque reference and previews (``None`` for a no-proposal outcome).
    ``failure_reason`` is the content-free barcode-problem label a fallback / no-proposal
    carries (``None`` for an exact match).
    """

    proposal: ExactEvidenceProposal | None
    failure_reason: str | None


@dataclass(frozen=True)
class BarcodeProposalGenerator:
    """Generate an exact-or-fallback barcode proposal for an existing food item.

    Owns only the source-selection policy: try the exact OFF match first (through the
    injected cache-first :class:`BarcodeExactSource`), then the estimator
    :class:`IdentityFallbackSource` from the item's identity, else no proposal. It
    never loads or mutates the item — the caller owns owner-scoped loading, signing the
    returned proposal, and the read projection.
    """

    exact_source: BarcodeExactSource
    fallback_source: IdentityFallbackSource
    ttl_seconds: int = PROPOSAL_TTL_SECONDS

    def generate(
        self,
        *,
        owner_id: uuid.UUID,
        item: DerivedFoodItem,
        barcode: str,
        now: datetime | None = None,
    ) -> BarcodeProposalOutcome:
        """Build the proposal for ``item`` + ``barcode``; never mutate ``item``.

        Returns an **exact** proposal on a confident OFF match, a **fallback** proposal
        (with a barcode ``failure_reason``) when the item's identity resolves to a
        low-trust estimate instead, or a **no-proposal** outcome (proposal ``None``,
        content-free reason) when neither is available.
        """

        resolved, failure_reason = self._resolve_exact(barcode)
        if resolved is not None:
            return BarcodeProposalOutcome(
                proposal=self._exact_proposal(owner_id, item, resolved, now), failure_reason=None
            )

        fallback = self._resolve_fallback(item)
        if fallback is not None:
            return BarcodeProposalOutcome(
                proposal=self._fallback_proposal(owner_id, item, fallback, now),
                failure_reason=failure_reason,
            )
        return BarcodeProposalOutcome(proposal=None, failure_reason=failure_reason)

    def _resolve_exact(self, barcode: str) -> tuple[_ResolvedProduct | None, str]:
        """Try the cache-first OFF match; ``(product, "")`` or ``(None, reason)``.

        An invalid GTIN (``barcode_invalid``), a disabled source
        (``source_unavailable``), a genuine miss (``barcode_no_match``), or a
        found-but-unusable product (``no_usable_facts``) all yield no product plus a
        content-free reason, so the caller falls through to the fallback rather than
        dead-ending. OFF facts the existing plausibility gate rejects surface as
        ``no_usable_facts`` (the resolver reports the miss reason), preserving that gate.
        A transient/terminal OFF **error** is **not** caught here: it propagates from
        :meth:`BarcodeExactSource.resolve_product_outcome` so the route renders a
        retryable ``503`` rather than a disguised miss/fallback.
        """

        if normalize_barcode(barcode) is None:
            return None, FAILURE_INVALID
        if not self.exact_source.enabled:
            return None, FAILURE_SOURCE_UNAVAILABLE
        resolved, miss_reason = self.exact_source.resolve_product_outcome(barcode)
        if resolved is None:
            return None, _MISS_REASON_FAILURE.get(
                miss_reason or OffMissReason.NO_MATCH, FAILURE_NO_MATCH
            )
        return resolved, ""

    def _resolve_fallback(self, item: DerivedFoodItem) -> FallbackFacts | None:
        """Estimate from the item's sanitized identity, or ``None`` when unavailable.

        Fails closed on an empty sanitized identity (no usable food token → nothing to
        estimate from) before invoking the estimator fallback, so a nameless item never
        drives a broad, identity-free lookup.
        """

        identity = sanitized_identity(item.name)
        if not identity:
            return None
        return self.fallback_source.resolve(identity)

    def _exact_proposal(
        self,
        owner_id: uuid.UUID,
        item: DerivedFoodItem,
        resolved: _ResolvedProduct,
        now: datetime | None,
    ) -> ExactEvidenceProposal:
        """Build the ``exact`` ``product_database`` proposal from the OFF product row."""

        product = resolved.product
        facts = ProposalFacts(
            basis=PER_100G_BASIS,
            calories=product.calories_per_100g,
            protein_g=product.protein_per_100g,
            carbs_g=product.carbs_per_100g,
            fat_g=product.fat_per_100g,
            default_serving_g=product.default_serving_g,
            serving_label=None,
        )
        return build_proposal(
            owner_id=owner_id,
            item_id=item.id,
            kind=ExactEvidenceKind.BARCODE,
            quality=ExactEvidenceQuality.EXACT,
            source_type=SourceType.PRODUCT_DATABASE.value,
            source_ref=product.source_ref,
            content_hash=product.content_hash,
            facts=facts,
            now=now,
            ttl_seconds=self.ttl_seconds,
        )

    def _fallback_proposal(
        self,
        owner_id: uuid.UUID,
        item: DerivedFoodItem,
        fallback: FallbackFacts,
        now: datetime | None,
    ) -> ExactEvidenceProposal:
        """Build the ``fallback`` proposal, preserving the estimate's honest provenance."""

        facts = ProposalFacts(
            basis=PER_100G_BASIS,
            calories=fallback.facts.calories,
            protein_g=fallback.facts.protein_g,
            carbs_g=fallback.facts.carbs_g,
            fat_g=fallback.facts.fat_g,
            default_serving_g=fallback.default_serving_g,
            serving_label=fallback.serving_label,
        )
        return build_proposal(
            owner_id=owner_id,
            item_id=item.id,
            kind=ExactEvidenceKind.BARCODE,
            quality=ExactEvidenceQuality.FALLBACK,
            source_type=fallback.source_type,
            source_ref=fallback.source_ref,
            content_hash=fallback.content_hash,
            facts=facts,
            assumptions=list(fallback.assumptions) or None,
            field_provenance=fallback.field_provenance,
            now=now,
            ttl_seconds=self.ttl_seconds,
        )
