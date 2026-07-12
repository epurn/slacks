"""Exact-evidence proposal read projection (FTY-307).

The read-model half of the ``Make it exact`` foundation: :func:`serialize_proposal`
turns a server-held :class:`~app.estimator.exact_evidence.ExactEvidenceProposal` plus
its opaque reference into the :class:`~app.schemas.exact_evidence.ExactEvidenceProposalDTO`
a propose route (barcode FTY-308, label FTY-309) returns. It costs the preview at the
item's **current amount** using the same serving math apply uses
(:func:`~app.estimator.exact_evidence.cost_grams`), so the preview's
``can_cost_current_amount`` flag and apply's costability decision are one code path
and cannot disagree; when the current amount cannot be costed the preview carries the
proposal's source facts on its own basis instead of invented totals.

The preview's ``source`` descriptor is derived through the shared
:func:`~app.services.item_read_model.source_descriptor`, so a fallback proposal
previews its honest low-trust source label — never an exact one — matching what the
applied item will read.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ExactEvidenceKind, ExactEvidenceQuality, SourceType
from app.estimator.exact_evidence import ExactEvidenceProposal, cost_grams
from app.estimator.food_serving import scale_facts
from app.estimator.re_match import ItemNotFound
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.log_events import LogEvent
from app.schemas.exact_evidence import (
    ExactEvidenceProposalDTO,
    ExactEvidenceProposalPreviewDTO,
)
from app.services.item_read_model import source_descriptor

#: The evidence source types that are **always** exact-upgrade-eligible: rough
#: low-trust estimates a barcode/label can replace with exact facts
#: (``docs/contracts/evidence-retrieval.md`` — Exact Evidence Upgrade, Eligibility;
#: ``docs/contracts/daily-summary.md`` — the matching ``make it exact`` nudge signal).
_ALWAYS_ELIGIBLE_SOURCE_TYPES = frozenset(
    {SourceType.MODEL_PRIOR.value, SourceType.REFERENCE_SOURCE.value}
)


class NotUpgradeable(Exception):
    """Raised when a food item is already source-backed and offers no exact upgrade.

    The propose routes (barcode FTY-308, label FTY-309) evaluate exact-upgrade
    eligibility server-side from the item's ``evidence_sources`` row, matching the
    client-side ``make it exact`` nudge signal, and refuse an ineligible target with
    ``422 {"error": "not_upgradeable"}`` (no mutation) — a ``user_label`` /
    ``product_database`` / ``trusted_nutrition_database`` / ``official_source`` item
    keeps the normal correction levers instead.
    """


def is_exact_upgrade_eligible(session: Session, item: DerivedFoodItem) -> bool:
    """Whether ``item`` is a low-trust/incomplete food item eligible for exact upgrade.

    Mirrors the ``make it exact`` nudge signal the read model exposes
    (``docs/contracts/daily-summary.md`` → ``source`` descriptor): eligible for a
    ``model_prior`` or ``reference_source`` item, or a ``user_text`` item whose macros
    are incomplete — a macro fact ``None`` in this read shape, or a non-null
    ``estimate_basis`` marker (a rough gap-filled macro). Already source-backed types
    (``user_label`` / ``product_database`` / ``trusted_nutrition_database`` /
    ``official_source``) are ineligible, and an item with **no** evidence row fails
    closed as ineligible. Derived from the item's own evidence row and macro facts —
    no new persisted flag.
    """

    evidence = session.scalars(
        select(EvidenceSource)
        .where(EvidenceSource.derived_food_item_id == item.id)
        .order_by(EvidenceSource.created_at.desc())
    ).first()
    if evidence is None:
        return False
    if evidence.source_type in _ALWAYS_ELIGIBLE_SOURCE_TYPES:
        return True
    if evidence.source_type != SourceType.USER_TEXT.value:
        return False
    macros_incomplete = item.protein_g is None or item.carbs_g is None or item.fat_g is None
    descriptor = source_descriptor(evidence.source_type, evidence.source_ref, evidence.assumptions)
    has_rough_macro_fill = descriptor is not None and descriptor.estimate_basis is not None
    return macros_incomplete or has_rough_macro_fill


def load_owned_food_item(
    session: Session, item_id: uuid.UUID, owner_id: uuid.UUID
) -> DerivedFoodItem:
    """Load a food item by id scoped to ``owner_id``, classifying an owned exercise id.

    The shared owner-scoped loader for the source-specific propose services (barcode
    FTY-308, label FTY-309). The query is constrained to the owner, so another user's
    item — or an unknown id — is indistinguishable from a missing one
    (:class:`~app.estimator.re_match.ItemNotFound` → ``404``, no existence oracle). An
    **owned** exercise item, however, is a real but ineligible target (an exercise burn
    has no evidence to upgrade), so it is refused with :class:`NotUpgradeable` → ``422
    not_upgradeable`` rather than masqueraded as unknown — matching the exact-upgrade
    eligibility contract. A cross-user exercise id stays a ``404`` (owner-scoped), and an
    owned exercise item whose parent log event is soft-voided stays a ``404`` (no void
    oracle), consistent with the router's voided-parent precheck.
    """

    item = session.scalars(
        select(DerivedFoodItem).where(
            DerivedFoodItem.id == item_id,
            DerivedFoodItem.user_id == owner_id,
        )
    ).one_or_none()
    if item is not None:
        return item
    if _owns_active_exercise_item(session, item_id, owner_id):
        raise NotUpgradeable("exercise items are not exact-upgradeable")
    raise ItemNotFound("derived food item not found")


def _owns_active_exercise_item(session: Session, item_id: uuid.UUID, owner_id: uuid.UUID) -> bool:
    """Whether ``item_id`` is an owner's exercise item with a non-voided parent event.

    Owner-scoped and voided-parent-excluded so this stays fail-closed: a cross-user id
    or a soft-voided-parent item does not report ``True`` (both remain ``404`` with no
    existence/void disclosure). A ``True`` result marks a genuinely ineligible target
    the propose route renders ``422 not_upgradeable``.
    """

    exercise_id = session.execute(
        select(DerivedExerciseItem.id)
        .join(LogEvent, LogEvent.id == DerivedExerciseItem.log_event_id)
        .where(
            DerivedExerciseItem.id == item_id,
            DerivedExerciseItem.user_id == owner_id,
            LogEvent.voided_at.is_(None),
        )
    ).scalar_one_or_none()
    return exercise_id is not None


def no_proposal_dto(
    kind: ExactEvidenceKind, failure_reason: str | None
) -> ExactEvidenceProposalDTO:
    """The read shape for a propose attempt that produced nothing applyable.

    A calm, content-free outcome shared by the source-specific propose services:
    ``quality = none``, no preview, no signed reference, and the source-specific
    ``failure_reason`` so the client can say what happened without any invented number.
    ``kind`` distinguishes the barcode and label variants.
    """

    return ExactEvidenceProposalDTO(
        proposal_ref="",
        kind=kind,
        quality=ExactEvidenceQuality.NONE,
        failure_reason=failure_reason,
        preview=None,
        can_cost_current_amount=False,
    )


def serialize_proposal(
    item: DerivedFoodItem,
    proposal: ExactEvidenceProposal,
    proposal_ref: str,
    *,
    failure_reason: str | None = None,
) -> ExactEvidenceProposalDTO:
    """Project a server-held proposal + its reference into the read DTO.

    Costs the preview at ``item``'s current amount: when costable, the nutrition
    fields are the item's would-be totals; otherwise they are the proposal's per-100g
    source facts (``can_cost_current_amount = False``), so the client asks for an
    amount rather than being shown an invented portion. ``failure_reason`` is the
    closed, content-free label a ``fallback`` proposal carries (``None`` for
    ``exact``).
    """

    facts = proposal.facts
    grams = cost_grams(item, proposal, item.amount)
    can_cost = grams is not None

    descriptor = source_descriptor(proposal.source_type, proposal.source_ref, proposal.assumptions)
    # A propose route only builds a proposal for an in-hierarchy source, so the
    # descriptor is always present; guard defensively rather than raise on a read.
    if descriptor is None:
        preview = None
    elif grams is not None:
        scaled = scale_facts(facts.as_nutrition_facts(), grams)
        preview = ExactEvidenceProposalPreviewDTO(
            source=descriptor,
            basis=facts.basis,
            calories=scaled.calories,
            protein_g=scaled.protein_g,
            carbs_g=scaled.carbs_g,
            fat_g=scaled.fat_g,
            amount=item.amount,
            serving_label=facts.serving_label,
        )
    else:
        preview = ExactEvidenceProposalPreviewDTO(
            source=descriptor,
            basis=facts.basis,
            calories=facts.calories,
            protein_g=facts.protein_g,
            carbs_g=facts.carbs_g,
            fat_g=facts.fat_g,
            amount=item.amount,
            serving_label=facts.serving_label,
        )

    return ExactEvidenceProposalDTO(
        proposal_ref=proposal_ref,
        kind=proposal.kind,
        quality=proposal.quality,
        failure_reason=failure_reason,
        preview=preview,
        can_cost_current_amount=can_cost,
    )
