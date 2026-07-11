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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import SourceType
from app.estimator.exact_evidence import ExactEvidenceProposal, cost_grams
from app.estimator.food_serving import scale_facts
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource
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
