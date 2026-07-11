"""Barcode exact-evidence proposal service — load, generate, sign, project (FTY-308).

The backend-core orchestration for the barcode ``Make it exact`` propose route: it
loads the target food item scoped to its owner (fail closed on cross-user / unknown),
runs the estimator :class:`~app.estimator.barcode_proposal.BarcodeProposalGenerator`
(exact OFF match → estimator identity fallback → no proposal), signs any produced
proposal into the opaque ``proposal_ref`` with the FTY-307 trust anchor, and projects
the FTY-307 read shape (:func:`~app.services.exact_evidence.serialize_proposal`). It
**never mutates** the item — the item changes only when the user applies the returned
proposal through FTY-307.

The generator's real dependencies are built per request from configuration
(:func:`_build_generator`): the cache-first :class:`~app.estimator.food_resolvers.BarcodeResolver`
over the hardened OFF client, and the
:class:`~app.estimator.identity_fallback.IdentityFallbackResolver` over the configured
LLM provider, search adapter, and searched-result fetch settings — the same clients the
estimation pipeline uses. Tests inject a network-free ``generator`` directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ExactEvidenceKind, ExactEvidenceQuality
from app.estimator.barcode_proposal import BarcodeProposalGenerator
from app.estimator.exact_evidence import encode_proposal_ref
from app.estimator.food_resolvers import BarcodeResolver
from app.estimator.identity_fallback import IdentityFallbackResolver
from app.estimator.off import build_off_client
from app.estimator.re_match import ItemForbidden, ItemNotFound
from app.estimator.reference_fetch import load_reference_fetch_settings
from app.estimator.search import build_search_provider
from app.llm import build_provider, load_llm_settings
from app.models.derived import DerivedFoodItem
from app.models.identity import User
from app.schemas.exact_evidence import ExactEvidenceProposalDTO
from app.services.exact_evidence import (
    NotUpgradeable,
    is_exact_upgrade_eligible,
    serialize_proposal,
)
from app.settings import load_settings


def propose_barcode_evidence(
    session: Session,
    *,
    owner_id: uuid.UUID,
    current_user: User,
    item_id: uuid.UUID,
    barcode: str,
    secret: str,
    generator: BarcodeProposalGenerator | None = None,
) -> ExactEvidenceProposalDTO:
    """Build the barcode proposal DTO for ``owner_id``'s food ``item_id`` + ``barcode``.

    Loads the item scoped to its owner (:class:`ItemForbidden` for a non-owner caller,
    :class:`ItemNotFound` for an unknown / non-food item — both rendered ``404`` by the
    route), refuses an already-source-backed item
    (:class:`~app.services.exact_evidence.NotUpgradeable` → ``422 not_upgradeable``),
    then runs the generator, signs any produced proposal, and returns the read DTO; a
    no-proposal outcome returns a ``quality = none`` DTO with a content-free
    ``failure_reason`` and no signed reference. Never mutates the item.
    """

    if owner_id != current_user.id:
        raise ItemForbidden("cross-user barcode proposal denied")
    item = _load_owned_food_item(session, item_id, owner_id)
    if not is_exact_upgrade_eligible(session, item):
        raise NotUpgradeable("item is already source-backed")

    generator = generator or build_barcode_proposal_generator(session)
    outcome = generator.generate(owner_id=owner_id, item=item, barcode=barcode)
    if outcome.proposal is None:
        return _no_proposal_dto(outcome.failure_reason)

    proposal_ref = encode_proposal_ref(outcome.proposal, secret)
    return serialize_proposal(
        item, outcome.proposal, proposal_ref, failure_reason=outcome.failure_reason
    )


def _load_owned_food_item(
    session: Session, item_id: uuid.UUID, owner_id: uuid.UUID
) -> DerivedFoodItem:
    """Load a food item by id scoped to ``owner_id`` so a cross-user id is not found.

    The query is constrained to the owner, so another user's item — or an exercise /
    unknown id — is indistinguishable from a missing one (no existence oracle).
    """

    item = session.scalars(
        select(DerivedFoodItem).where(
            DerivedFoodItem.id == item_id,
            DerivedFoodItem.user_id == owner_id,
        )
    ).one_or_none()
    if item is None:
        raise ItemNotFound("derived food item not found")
    return item


def _no_proposal_dto(failure_reason: str | None) -> ExactEvidenceProposalDTO:
    """The read shape for a barcode attempt that produced nothing applyable.

    A calm, content-free outcome: ``quality = none``, no preview, no signed reference,
    and the barcode ``failure_reason`` so the client can say what happened without any
    invented number.
    """

    return ExactEvidenceProposalDTO(
        proposal_ref="",
        kind=ExactEvidenceKind.BARCODE,
        quality=ExactEvidenceQuality.NONE,
        failure_reason=failure_reason,
        preview=None,
        can_cost_current_amount=False,
    )


def build_barcode_proposal_generator(session: Session) -> BarcodeProposalGenerator:
    """Build the production generator from configured clients (no network on build).

    The exact source is the cache-first OFF barcode resolver (a cache hit makes no
    external call); the fallback source is the identity resolver over the configured
    LLM provider, search adapter, and searched-result fetch settings. Constructing the
    clients/adapters opens no socket.
    """

    app_settings = load_settings()
    fallback = IdentityFallbackResolver(
        provider=build_provider(load_llm_settings()),
        search_provider=build_search_provider(),
        reference_fetch_settings=load_reference_fetch_settings(),
        model_prior_confidence_floor=app_settings.estimator_model_prior_confidence_floor,
    )
    return BarcodeProposalGenerator(
        exact_source=BarcodeResolver(session=session, source=build_off_client()),
        fallback_source=fallback,
    )
