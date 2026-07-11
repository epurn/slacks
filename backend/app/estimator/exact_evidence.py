"""Exact-evidence proposal apply foundation (FTY-307).

The generic, source-agnostic half of the ``Make it exact`` lever
(``docs/contracts/evidence-retrieval.md`` — **Exact Evidence Upgrade — FTY-306**;
``docs/contracts/food-resolution.md`` — **Exact Evidence Upgrade Routing**). A
source-specific story generates a **proposal** from a barcode (FTY-308) or a
nutrition label (FTY-309); this module owns everything that is not fact
generation:

- **The trust anchor.** A proposal is not stored in a table. It is an opaque,
  server-verifiable **signed reference** — an HMAC-SHA256 signature over a
  base64url-encoded JSON payload, keyed by the application's existing
  ``SLACKS_AUTH_SECRET`` (the same primitive as the auth bearer token,
  ``app/security/tokens.py``). The signed payload **binds** the owning user, the
  target food item, the proposal kind/quality, the source type/ref, the normalized
  per-100g facts + basis, the default-serving costability metadata, and an
  issued/expiry pair (the replay guard). Tampering with any bound field breaks the
  signature; an expired or wrong-user/wrong-item reference is rejected with no
  mutation. No new table, no migration, no server-side proposal storage — so the
  proposal carries **no** raw image bytes, OCR text, provider output, or fetched
  page, only the extracted/validated facts and refs (``docs/security/
  data-retention.md``).

- **Apply.** :meth:`ExactEvidenceApplyCapability.apply` loads the item scoped to
  its owner (cross-user/unknown → not found), verifies the reference belongs to
  that owner **and** item, preserves the current amount by default (or applies an
  optional user amount adjustment before costing), re-derives the facts
  **server-side** from the verified proposal (the client never supplies nutrition
  facts, and apply issues no fresh evidence egress), recomputes with the FTY-044
  serving math, rewrites the item's ``evidence_sources`` provenance in place,
  re-snapshots ``*_estimated``, and appends one immutable ``re_match`` correction
  row. It is a **specialized re-resolution** to a server-generated proposal, not a
  second correction model: it reuses the shared FTY-093 write helpers
  (:func:`~app.estimator.re_match.apply_resolved_facts`,
  :func:`~app.estimator.re_match.record_re_match_correction`). A ``fallback``
  proposal keeps its honest low-trust provenance (``reference_source`` /
  ``model_prior`` / a comparable-reference marker) — it never masquerades as
  ``product_database`` / ``user_label``.

- **Preview.** ``app.services.exact_evidence.serialize_proposal`` projects the read
  shape a propose route (FTY-308/309) returns: the opaque ``proposal_ref``, the
  kind/quality/failure reason, and a preview costed at the item's current amount (or
  the source facts on the proposal's basis when the current amount cannot be costed),
  plus the ``can_cost_current_amount`` flag apply enforces.

Security posture (rated **high**): the proposal reference is untrusted client
input until its signature, expiry, and owner/item binding are verified; every
apply is owner-scoped and fails closed with no mutation on any rejection; no
nutrition value, source ref, or proposal payload is logged.
"""

from __future__ import annotations

import hmac
import json
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ExactEvidenceKind, ExactEvidenceQuality
from app.estimator.food_serving import NutritionFacts, resolve_grams, scale_facts
from app.estimator.re_match import (
    ItemForbidden,
    ItemNotFound,
    apply_resolved_facts,
    record_re_match_correction,
)
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.identity import User

#: Canonical basis a proposal's facts are expressed against. Barcode
#: (``product_database``), label (``user_label``), and fallback
#: (``reference_source`` / ``model_prior``) sources all canonicalise to per-100g
#: facts, so apply costs them with the FTY-044 per-100g serving math.
PER_100G_BASIS: Final[str] = "per_100g"

#: How long a signed proposal reference stays valid. A proposal is a short-lived
#: trust anchor for the preview→apply flow, not durable user history: an unapplied
#: reference expires (the replay guard) rather than lingering as an apply capability.
PROPOSAL_TTL_SECONDS: Final[int] = 30 * 60

#: Payload schema version, so the signed shape can evolve without silently
#: mis-parsing an old reference.
_PAYLOAD_VERSION: Final[int] = 1

#: Domain-separation label folded into every proposal signature. The proposal
#: reference reuses ``SLACKS_AUTH_SECRET`` (the same key as the auth bearer token,
#: ``app/security/tokens.py``); binding this fixed context into the signed message
#: means a proposal signature and an auth-token signature can never be confused even
#: if their payloads ever coincided — a cross-context reference fails verification.
_SIGN_DOMAIN: Final[str] = "fty307.exact_evidence.v1"


class InvalidProposalRef(Exception):
    """Raised when a proposal reference is malformed, tampered, or expired.

    The reference is untrusted client input: a bad structure, a signature that does
    not verify (any bound field was altered), or an elapsed expiry all raise this so
    apply fails closed with no mutation. Carries no reference content.
    """


class ProposalNotResolvable(Exception):
    """Raised when a verified proposal does not belong to this user + item.

    A structurally-valid, correctly-signed reference that is bound to a different
    owner or a different item than the apply target is refused with no mutation — a
    proposal is scoped to the exact user+item it was built for and cannot be
    replayed against another. Also raised (from :class:`InvalidProposalRef`) for a
    tampered/expired reference, so the router renders one ``proposal_not_resolvable``
    error without an existence oracle.
    """


class AmountNotCostable(Exception):
    """Raised when the proposal cannot cost the current/adjusted amount.

    The proposal's source has no serving relation that resolves the item's
    count/quantity to grams and the user supplied no adjusted amount, so apply fails
    closed (router → ``422 amount_required``) rather than guess a portion. Nothing
    mutates.
    """


@dataclass(frozen=True)
class ProposalFacts:
    """The normalized per-100g facts + costability metadata a proposal carries.

    Server-generated and signed into the proposal reference; the client never
    supplies these. ``calories`` and macros are canonical per-100g values (kcal /
    grams) the FTY-044 serving math scales; ``default_serving_g`` lets a count
    quantity resolve to grams, and ``serving_label`` is a display-only label for the
    preview. ``basis`` is always :data:`PER_100G_BASIS` in v1.
    """

    basis: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    default_serving_g: float | None
    serving_label: str | None

    def as_nutrition_facts(self) -> NutritionFacts:
        """The per-100g fact sheet the serving math scales."""

        return NutritionFacts(
            calories=self.calories,
            protein_g=self.protein_g,
            carbs_g=self.carbs_g,
            fat_g=self.fat_g,
        )


@dataclass(frozen=True)
class ExactEvidenceProposal:
    """A server-held exact-evidence proposal — the trust anchor apply re-derives from.

    Built server-side from user-supplied product evidence (barcode/label) by
    FTY-308/309; bound into an opaque signed reference by :func:`encode_proposal_ref`
    and recovered by :func:`decode_proposal_ref`. Every field is server-generated:
    the owning user and target item it is scoped to, the evidence kind/quality, the
    honest source type/ref the applied item will carry, the immutable fact snapshot,
    any documented ``assumptions`` / ``field_provenance`` (a fallback's rough basis),
    and the issued/expiry replay guard.
    """

    owner_id: uuid.UUID
    item_id: uuid.UUID
    kind: ExactEvidenceKind
    quality: ExactEvidenceQuality
    source_type: str
    source_ref: str
    content_hash: str
    facts: ProposalFacts
    assumptions: list[str] | None
    field_provenance: dict[str, str] | None
    issued_at: int
    expires_at: int


def build_proposal(  # noqa: PLR0913 - the proposal's bound-field construction seam
    *,
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    kind: ExactEvidenceKind,
    quality: ExactEvidenceQuality,
    source_type: str,
    source_ref: str,
    content_hash: str,
    facts: ProposalFacts,
    assumptions: list[str] | None = None,
    field_provenance: dict[str, str] | None = None,
    now: datetime | None = None,
    ttl_seconds: int = PROPOSAL_TTL_SECONDS,
) -> ExactEvidenceProposal:
    """Assemble a proposal with an issued/expiry replay guard.

    The single construction seam a propose route (FTY-308/309) calls after
    generating and validating the facts server-side, so the issued/expiry stamping
    is consistent. ``now`` is injectable for deterministic tests.
    """

    issued = now or datetime.now(UTC)
    issued_ts = int(issued.timestamp())
    return ExactEvidenceProposal(
        owner_id=owner_id,
        item_id=item_id,
        kind=kind,
        quality=quality,
        source_type=source_type,
        source_ref=source_ref,
        content_hash=content_hash,
        facts=facts,
        assumptions=assumptions,
        field_provenance=field_provenance,
        issued_at=issued_ts,
        expires_at=issued_ts + ttl_seconds,
    )


def encode_proposal_ref(proposal: ExactEvidenceProposal, secret: str) -> str:
    """Serialize + HMAC-sign ``proposal`` into an opaque ``<payload>.<sig>`` reference.

    The payload is compact canonical JSON, base64url-encoded (no padding), signed
    with HMAC-SHA256 over the encoded payload using ``secret``. The secret is never
    embedded in the reference. This is the only key ``apply`` accepts — the client
    receives it, never a writable fact set.
    """

    payload_b64 = _b64encode(
        json.dumps(_to_payload(proposal), separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{payload_b64}.{_sign(payload_b64, secret)}"


def decode_proposal_ref(
    proposal_ref: str, secret: str, *, now: datetime | None = None
) -> ExactEvidenceProposal:
    """Verify a proposal reference and recover the proposal it binds.

    Verifies the signature in constant time (a forged/tampered reference cannot be
    distinguished by timing) and enforces expiry before returning the proposal.
    Raises :class:`InvalidProposalRef` for anything malformed, tampered, or expired,
    so the caller fails closed. Owner/item binding is checked by the apply capability
    against the request target, not here.
    """

    try:
        payload_b64, signature = proposal_ref.split(".")
    except (ValueError, AttributeError) as exc:
        raise InvalidProposalRef("malformed proposal reference") from exc

    # Both segments are still untrusted client bytes here: a non-ASCII payload
    # segment breaks ``_sign``'s ASCII encoding, and a non-ASCII signature segment
    # breaks ``compare_digest`` (str comparison is ASCII-only). Both must fail closed
    # as a malformed reference, not escape as an unmapped ``UnicodeError``/``TypeError``.
    try:
        signature_ok = hmac.compare_digest(signature, _sign(payload_b64, secret))
    except (UnicodeError, TypeError) as exc:
        raise InvalidProposalRef("malformed proposal reference") from exc
    if not signature_ok:
        raise InvalidProposalRef("bad signature")

    try:
        payload = json.loads(_b64decode(payload_b64))
        proposal = _from_payload(payload)
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidProposalRef("malformed proposal payload") from exc

    current = now or datetime.now(UTC)
    if int(current.timestamp()) >= proposal.expires_at:
        raise InvalidProposalRef("expired proposal reference")
    return proposal


@dataclass(frozen=True)
class ExactEvidenceApplyCapability:
    """Apply a verified exact-evidence proposal to an existing food item (FTY-307).

    Owns the object-level-scoped item load, the proposal-reference verification +
    owner/item binding, the amount-preservation / optional-adjustment costability
    rule, and the deterministic in-place source replacement (reusing the shared
    FTY-093 re-resolution write helpers). Constructed per request by the thin
    backend route, which injects the session and the signing secret; tests construct
    it directly.
    """

    session: Session
    secret: str

    def apply(
        self,
        *,
        owner_id: uuid.UUID,
        current_user: User,
        item_id: uuid.UUID,
        proposal_ref: str,
        amount: float | None = None,
        now: datetime | None = None,
    ) -> DerivedFoodItem:
        """Apply ``proposal_ref`` to ``owner_id``'s food item, in place.

        Fails closed with no mutation on: a non-owner caller or unknown item
        (:class:`~app.estimator.re_match.ItemForbidden` /
        :class:`~app.estimator.re_match.ItemNotFound` → ``404``); a tampered,
        expired, wrong-user, or wrong-item reference
        (:class:`ProposalNotResolvable` → ``422``); an uncostable current/adjusted
        amount (:class:`AmountNotCostable` → ``422``). On success it preserves the
        current amount (or applies ``amount`` before costing), rewrites the item's
        evidence provenance to the proposal's source, re-snapshots ``*_estimated``,
        appends one ``re_match`` correction row, and returns the updated item. The
        item is **not** marked ``user_edited``.
        """

        self._authorize(owner_id, current_user)
        item = self._load_owned(item_id, owner_id)

        try:
            proposal = decode_proposal_ref(proposal_ref, self.secret, now=now)
        except InvalidProposalRef as exc:
            raise ProposalNotResolvable("proposal reference does not resolve") from exc
        if proposal.owner_id != owner_id or proposal.item_id != item_id:
            raise ProposalNotResolvable("proposal is not held for this user and item")

        # Cost BEFORE any mutation so an uncostable amount leaves the item untouched.
        effective_amount = amount if amount is not None else item.amount
        grams = cost_grams(item, proposal, effective_amount)
        if grams is None:
            raise AmountNotCostable("proposal cannot cost the requested amount")
        scaled = scale_facts(proposal.facts.as_nutrition_facts(), grams)

        prior_calories = item.calories
        if amount is not None:
            # The optional adjustment is folded into this one re-resolution — applied
            # before the recompute, never recorded as a separate amount_adjust row.
            item.amount = round(amount, 3)
        apply_resolved_facts(item, scaled)
        self._rewrite_evidence(item, proposal)
        record_re_match_correction(
            self.session, item, old_calories=prior_calories, new_calories=scaled.calories
        )

        self.session.commit()
        self.session.refresh(item)
        return item

    def _rewrite_evidence(self, item: DerivedFoodItem, proposal: ExactEvidenceProposal) -> None:
        """Rewrite the item's ``evidence_sources`` provenance to the proposal's source.

        Updates the item's existing evidence row in place (or creates one if absent)
        so it points at the applied source: the proposal's ``source_type`` /
        ``source_ref`` / ``content_hash`` / a fresh ``fetched_at`` / the immutable
        per-100g snapshot / ``basis`` / ``assumptions`` / ``field_provenance``.
        ``product_id`` is ``None`` — the facts are re-derived from the signed proposal
        itself, not a global cache row (barcode-cache linking is FTY-308's). A
        ``fallback`` proposal writes its honest low-trust ``source_type`` and rough
        ``assumptions`` here, so the applied item stays visibly rough and never reads
        as an exact source.
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

        evidence.product_id = None
        evidence.source_type = proposal.source_type
        evidence.source_ref = proposal.source_ref
        evidence.content_hash = proposal.content_hash
        evidence.fetched_at = datetime.now(UTC)
        evidence.basis = proposal.facts.basis
        evidence.calories_per_100g = proposal.facts.calories
        evidence.protein_per_100g = proposal.facts.protein_g
        evidence.carbs_per_100g = proposal.facts.carbs_g
        evidence.fat_per_100g = proposal.facts.fat_g
        evidence.field_provenance = proposal.field_provenance
        evidence.assumptions = list(proposal.assumptions) if proposal.assumptions else None

    @staticmethod
    def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
        """Fail closed unless ``current_user`` owns ``owner_id``'s items."""

        if owner_id != current_user.id:
            raise ItemForbidden("cross-user exact-evidence apply denied")

    def _load_owned(self, item_id: uuid.UUID, owner_id: uuid.UUID) -> DerivedFoodItem:
        """Load a food item by id scoped to ``owner_id`` so a cross-user id is not found."""

        item = self.session.scalars(
            select(DerivedFoodItem).where(
                DerivedFoodItem.id == item_id,
                DerivedFoodItem.user_id == owner_id,
            )
        ).one_or_none()
        if item is None:
            raise ItemNotFound("derived food item not found")
        return item


def cost_grams(
    item: DerivedFoodItem, proposal: ExactEvidenceProposal, amount: float | None
) -> float | None:
    """Resolve ``amount`` (in the item's own unit context) to grams, or ``None``.

    Reuses the FTY-044 serving math with the proposal's default serving size, so a
    count quantity costs only when the source supplies a serving relation. A ``None``
    return means the amount cannot be costed. Shared by apply (to enforce
    ``amount_required`` fail-closed before any mutation) and the preview serializer
    (to derive ``can_cost_current_amount`` at the item's current amount), so the
    preview flag and the apply decision are computed by one code path.
    """

    return resolve_grams(
        unit=item.unit,
        amount=amount,
        quantity_text=item.quantity_text,
        default_serving_g=proposal.facts.default_serving_g,
    )


def build_exact_evidence_apply_capability(
    session: Session, secret: str
) -> ExactEvidenceApplyCapability:
    """Build the apply capability over ``session`` with the proposal-signing ``secret``.

    The thin backend route calls this per request with the application's
    ``SLACKS_AUTH_SECRET``; tests construct :class:`ExactEvidenceApplyCapability`
    directly with a fixed secret.
    """

    return ExactEvidenceApplyCapability(session=session, secret=secret)


def _to_payload(proposal: ExactEvidenceProposal) -> dict[str, Any]:
    """Serialize a proposal to the canonical JSON payload the signature covers."""

    return {
        "v": _PAYLOAD_VERSION,
        "owner": str(proposal.owner_id),
        "item": str(proposal.item_id),
        "kind": proposal.kind.value,
        "quality": proposal.quality.value,
        "source_type": proposal.source_type,
        "source_ref": proposal.source_ref,
        "content_hash": proposal.content_hash,
        "basis": proposal.facts.basis,
        "facts": {
            "calories": proposal.facts.calories,
            "protein_g": proposal.facts.protein_g,
            "carbs_g": proposal.facts.carbs_g,
            "fat_g": proposal.facts.fat_g,
        },
        "default_serving_g": proposal.facts.default_serving_g,
        "serving_label": proposal.facts.serving_label,
        "assumptions": proposal.assumptions,
        "field_provenance": proposal.field_provenance,
        "iat": proposal.issued_at,
        "exp": proposal.expires_at,
    }


def _from_payload(payload: Any) -> ExactEvidenceProposal:
    """Reconstruct a proposal from a decoded JSON payload (untrusted until verified).

    Raises ``KeyError`` / ``ValueError`` / ``TypeError`` on any missing or
    ill-typed field so :func:`decode_proposal_ref` can fail closed. The signature
    is verified before this runs, so a well-formed payload here is authentic — but
    the reconstruction still validates structure defensively.
    """

    if not isinstance(payload, dict) or payload.get("v") != _PAYLOAD_VERSION:
        raise ValueError("unexpected proposal payload version")
    facts_raw = payload["facts"]
    facts = ProposalFacts(
        basis=str(payload["basis"]),
        calories=float(facts_raw["calories"]),
        protein_g=float(facts_raw["protein_g"]),
        carbs_g=float(facts_raw["carbs_g"]),
        fat_g=float(facts_raw["fat_g"]),
        default_serving_g=_opt_float(payload["default_serving_g"]),
        serving_label=_opt_str(payload["serving_label"]),
    )
    return ExactEvidenceProposal(
        owner_id=uuid.UUID(str(payload["owner"])),
        item_id=uuid.UUID(str(payload["item"])),
        kind=ExactEvidenceKind(payload["kind"]),
        quality=ExactEvidenceQuality(payload["quality"]),
        source_type=str(payload["source_type"]),
        source_ref=str(payload["source_ref"]),
        content_hash=str(payload["content_hash"]),
        facts=facts,
        assumptions=_opt_str_list(payload["assumptions"]),
        field_provenance=_opt_str_map(payload["field_provenance"]),
        issued_at=int(payload["iat"]),
        expires_at=int(payload["exp"]),
    )


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError("assumptions must be a list")
    return [str(item) for item in value]


def _opt_str_map(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("field_provenance must be an object")
    return {str(key): str(val) for key, val in value.items()}


def _sign(payload_b64: str, secret: str) -> str:
    """HMAC-SHA256 sign the domain-scoped encoded payload; return a base64url signature.

    The signed message is ``<domain>.<payload_b64>`` so the signature is bound to the
    exact-evidence context and cannot collide with another use of the same secret.
    """

    message = f"{_SIGN_DOMAIN}.{payload_b64}".encode("ascii")
    digest = hmac.new(secret.encode("utf-8"), message, sha256).digest()
    return _b64encode(digest)


def _b64encode(raw: bytes) -> str:
    """URL-safe base64 without padding (compact, URL/header friendly)."""

    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(encoded: str) -> bytes:
    """Inverse of :func:`_b64encode`, restoring stripped padding."""

    padding = "=" * (-len(encoded) % 4)
    return urlsafe_b64decode(encoded + padding)
