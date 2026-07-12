"""Label exact-evidence proposal service — validate, load, extract, sign, retain (FTY-309).

The backend-core orchestration for the label ``Make it exact`` propose route, the sibling
of :mod:`app.services.barcode_proposal`. It loads the target food item scoped to its owner
(fail closed on cross-user / unknown), runs the estimator
:class:`~app.estimator.label_proposal.LabelProposalGenerator` (legible panel → exact
``user_label`` proposal; unreadable/not-a-label/schema-invalid → estimator identity
fallback; else no proposal), signs any produced proposal into the opaque ``proposal_ref``
with the FTY-307 trust anchor, projects the FTY-307 read shape
(:func:`~app.services.exact_evidence.serialize_proposal`), and applies the FTY-077
discard-by-default retention for the raw image.

It **never mutates** the item — the item changes only when the user applies the returned
proposal through FTY-307. The one persistence it performs is the explicit image save: on
``save=true`` and only when a proposal was produced (never on a ``none`` outcome, and
never on a provider outage — that raised before this point), exactly one user-owned
``log_attachments`` row is written against the **item's owning log event**
(``docs/contracts/label-upload.md`` — Label exact-upgrade). On ``save=false`` the request
persists nothing at all.

Not to be confused with :mod:`app.services.label_proposal`, which is the unrelated FTY-196
label-capture confirmation gate (the uncounted ``proposed`` item on a new log event).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.enums import ExactEvidenceKind
from app.estimator.exact_evidence import encode_proposal_ref
from app.estimator.identity_fallback import IdentityFallbackResolver
from app.estimator.label_proposal import LabelProposalGenerator, VisionLabelExactSource
from app.estimator.re_match import ItemForbidden
from app.estimator.reference_fetch import load_reference_fetch_settings
from app.estimator.search import build_search_provider
from app.llm import build_provider, load_llm_settings
from app.models.derived import DerivedFoodItem
from app.models.identity import User
from app.schemas.exact_evidence import ExactEvidenceProposalDTO
from app.services.attachments import ingest_upload
from app.services.exact_evidence import (
    NotUpgradeable,
    is_exact_upgrade_eligible,
    load_owned_food_item,
    no_proposal_dto,
    serialize_proposal,
)
from app.settings import load_settings

#: Content-free provenance labels a label fallback records, so an applied fallback reads
#: honestly as a *label* miss (not the barcode default) while staying low-trust.
_REFERENCE_ASSUMPTION = "label exact match unavailable; estimated from reference source"
_MODEL_PRIOR_ASSUMPTION = "label exact match unavailable; estimated from model prior"


def propose_label_evidence(
    session: Session,
    *,
    owner_id: uuid.UUID,
    current_user: User,
    item_id: uuid.UUID,
    data: bytes,
    content_type: str,
    save: bool,
    secret: str,
    generator: LabelProposalGenerator | None = None,
) -> ExactEvidenceProposalDTO:
    """Build the label proposal DTO for ``owner_id``'s food ``item_id`` + uploaded image.

    Loads the item scoped to its owner (:class:`ItemForbidden` for a non-owner caller,
    :class:`~app.estimator.re_match.ItemNotFound` for an unknown / cross-user item — both
    rendered ``404`` by the route), refuses an ineligible item — already source-backed
    **or** an owned exercise item (:class:`NotUpgradeable` → ``422 not_upgradeable``), then
    runs the generator, signs any produced proposal, retains the image per ``save``, and
    returns the read DTO; a no-proposal outcome returns a ``quality = none`` DTO with a
    content-free ``failure_reason`` and no signed reference.

    The image bytes are already validated as data (size / type / signature) at the route
    boundary before this runs, so a provider outage surfaces as a :class:`LabelProviderError`
    (route → ``503``) rather than being disguised here. Never mutates the item; the only
    write is the explicit ``save=true`` attachment (never on a ``none`` outcome).
    """

    if owner_id != current_user.id:
        raise ItemForbidden("cross-user label proposal denied")
    item = load_owned_food_item(session, item_id, owner_id)
    if not is_exact_upgrade_eligible(session, item):
        raise NotUpgradeable("item is already source-backed")

    generator = generator or build_label_proposal_generator()
    outcome = generator.generate(owner_id=owner_id, item=item, data=data, content_type=content_type)
    if outcome.proposal is None:
        # A no-proposal outcome retains nothing: discard-by-default already discarded the
        # image, and there is no applyable evidence to save it against.
        return no_proposal_dto(ExactEvidenceKind.LABEL, outcome.failure_reason)

    if save:
        _retain_image(session, owner_id, current_user, item, data, content_type)

    proposal_ref = encode_proposal_ref(outcome.proposal, secret)
    return serialize_proposal(
        item, outcome.proposal, proposal_ref, failure_reason=outcome.failure_reason
    )


def _retain_image(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    item: DerivedFoodItem,
    data: bytes,
    content_type: str,
) -> None:
    """Persist the label image as exactly one user-owned attachment on the item's event.

    The explicit-save half of the FTY-077 retention rule: writes one
    ``log_attachments`` row (:func:`~app.services.attachments.ingest_upload` with
    ``save=True``) owned by ``owner_id`` against the item's **owning log event**, sharing
    the image's SHA-256 content hash. The item itself is untouched. Called only after a
    proposal was produced and only on ``save=true`` (``docs/contracts/label-upload.md`` —
    Label exact-upgrade).
    """

    ingest_upload(
        session,
        owner_id=owner_id,
        current_user=current_user,
        log_event_id=item.log_event_id,
        data=data,
        content_type=content_type,
        save=True,
    )


def build_label_proposal_generator() -> LabelProposalGenerator:
    """Build the production generator from configured clients (no network on build).

    The exact source is the vision-provider label extraction; the fallback source is the
    shared identity resolver over the same LLM provider, the configured search adapter,
    and the searched-result fetch settings, with label-worded provenance assumptions.
    Constructing the clients/adapters opens no socket. Unlike the barcode builder it needs
    no session: the label path writes no global cache row (extraction and the identity
    fallback are session-free), only the optional explicit image attachment.
    """

    provider = build_provider(load_llm_settings())
    app_settings = load_settings()
    fallback = IdentityFallbackResolver(
        provider=provider,
        search_provider=build_search_provider(),
        reference_fetch_settings=load_reference_fetch_settings(),
        model_prior_confidence_floor=app_settings.estimator_model_prior_confidence_floor,
        reference_assumption=_REFERENCE_ASSUMPTION,
        model_prior_assumption=_MODEL_PRIOR_ASSUMPTION,
    )
    return LabelProposalGenerator(
        exact_source=VisionLabelExactSource(provider=provider),
        fallback_source=fallback,
    )
