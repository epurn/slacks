"""Label-parse confirmation gate: read + confirm a proposed label item (FTY-196).

A legible nutrition-label parse persists as an **uncounted proposal** (a
``derived_food_items`` row held :attr:`~app.enums.DerivedItemStatus.PROPOSED`); it
does not count toward the day's totals until the user confirms it, because "OCR is
fallible — Fatty never silently trusts a fallible parse"
(``docs/design-philosophy.md``). This module owns the two owner-scoped actions the
mobile confirm sheet (FTY-197) drives:

- :func:`get_label_proposal` — read the proposed values for a label event so the
  sheet can render them. Returns the proposed food item, or ``None`` when the event
  has none (never confirmed, already confirmed, or a non-legible disposition).

- :func:`confirm_label_proposal` — commit the proposal in **one transaction**:
  optionally apply the user's adjusted values (reusing the deterministic,
  provenance-honest correction logic in :mod:`app.services.corrections`), then flip
  the item ``proposed → resolved`` so it counts. A **double confirm** is idempotent:
  a second call finds the item already ``resolved`` and returns it unchanged, so a
  proposal is never counted twice.

Both paths are **fail-closed and owner-scoped**: ownership + existence are enforced
by delegating to :func:`app.services.log_events.get_event`, so a cross-user or
nonexistent ``event_id`` is indistinguishable as a ``404`` (no existence oracle),
mirroring ``log-events.md`` / ``daily-summary.md``. Nutrition values are sensitive
personal data returned only to the owner and never logged.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import CandidateType, DerivedItemStatus
from app.estimator.label_step import USER_LABEL_SOURCE_TYPE
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.identity import User
from app.services import corrections as corrections_service
from app.services.corrections import QUANTITY_FIELD
from app.services.log_events import get_event

#: The confirm-request fields that are **value overrides** (a changed
#: calorie/macro is a ``user_edit``, marking the item edited per
#: ``corrections.md``), mapped to the correction field name they edit. ``amount``
#: is handled separately as the provenance-preserving servings rescale.
_VALUE_OVERRIDE_FIELDS: tuple[str, ...] = ("calories", "protein_g", "carbs_g", "fat_g")


class LabelProposalNotFound(Exception):
    """Raised when an owned event has no label proposal to confirm (fail closed).

    The event exists and is owned (ownership is proven first), but it carries no
    label-derived food item — e.g. it resolved to ``needs_clarification`` /
    ``failed``, or is not a label event. The router renders this as ``404`` so the
    confirm action neither mutates state nor claims a proposal exists.
    """


def get_label_proposal(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    event_id: uuid.UUID,
) -> DerivedFoodItem | None:
    """Return the uncounted proposed label item for ``event_id``, or ``None``.

    Ownership + existence are enforced by :func:`get_event` (a cross-user or
    nonexistent event raises, the router renders ``404``); the read itself then
    surfaces the event's ``proposed`` label item. ``None`` when the event has no
    proposal — no status oracle distinguishes "already confirmed" from "never had
    one".
    """

    get_event(session, owner_id, current_user, event_id)
    return _load_label_item(session, event_id, owner_id, status=DerivedItemStatus.PROPOSED)


def confirm_label_proposal(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    event_id: uuid.UUID,
    *,
    calories: float | None = None,
    protein_g: float | None = None,
    carbs_g: float | None = None,
    fat_g: float | None = None,
    amount: float | None = None,
) -> DerivedFoodItem:
    """Commit ``event_id``'s label proposal (``proposed → resolved``), one transaction.

    Enforces ownership via :func:`get_event`, then:

    - **Already confirmed (idempotent).** If the label item is already ``resolved``,
      return it unchanged — a double confirm never counts the proposal twice and
      never re-applies adjustments.
    - **Confirm.** Otherwise apply any supplied adjusted values as corrections (a
      changed calorie/macro is a ``user_edit`` value override; a supplied ``amount``
      is a provenance-preserving ``amount_adjust`` rescale — see
      :mod:`app.services.corrections`), flip the item ``proposed → resolved``, and
      commit the item update and its audit rows together.

    Raises :class:`LabelProposalNotFound` when the owned event has no label item
    (rendered ``404``), and :class:`~app.services.corrections.InvalidCorrection` for
    an out-of-range / invalid adjusted value (rendered ``422``).
    """

    get_event(session, owner_id, current_user, event_id)

    item = _load_label_item(session, event_id, owner_id)
    if item is None:
        raise LabelProposalNotFound("label proposal not found")

    # Idempotent double confirm: an already-committed proposal is returned as-is so
    # it is never counted twice and adjusted values are not re-applied on top.
    if DerivedItemStatus(item.status) is DerivedItemStatus.RESOLVED:
        return item

    corrections = _build_adjustment_corrections(
        owner_id,
        item,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        amount=amount,
    )

    # Flip proposed → resolved so the item counts, committing the status change and
    # any correction rows in the same transaction.
    item.status = DerivedItemStatus.RESOLVED
    session.add(item)
    session.add_all(corrections)
    session.commit()
    session.refresh(item)
    return item


def _build_adjustment_corrections(
    owner_id: uuid.UUID,
    item: DerivedFoodItem,
    *,
    calories: float | None,
    protein_g: float | None,
    carbs_g: float | None,
    fat_g: float | None,
    amount: float | None,
) -> list[Correction]:
    """Apply the confirm request's adjusted values to ``item``, returning corrections.

    Mutates ``item`` in place and returns the (uncommitted) correction rows. A
    supplied ``amount`` is applied first as the servings rescale (so an explicit
    calorie/macro override then takes precedence over the rescaled value); each
    supplied value field is applied as a ``user_edit`` override. Reuses the
    deterministic correction logic in :mod:`app.services.corrections`, so bounds
    checks and provenance/edited semantics match the edit endpoint exactly.
    """

    corrections: list[Correction] = []
    if amount is not None:
        corrections += corrections_service.apply_item_edit(
            owner_id, CandidateType.FOOD, item, QUANTITY_FIELD, amount
        )
    for field, value in zip(
        _VALUE_OVERRIDE_FIELDS, (calories, protein_g, carbs_g, fat_g), strict=True
    ):
        if value is not None:
            corrections += corrections_service.apply_item_edit(
                owner_id, CandidateType.FOOD, item, field, value
            )
    return corrections


def _load_label_item(
    session: Session,
    event_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    status: DerivedItemStatus | None = None,
) -> DerivedFoodItem | None:
    """Load the event's label-derived food item, scoped to ``owner_id``.

    A label item is identified by its ``user_label`` evidence row — the only
    food-item source that goes through the proposal gate — so the read never
    mistakes a text-parsed food item for a proposal. The match uses
    ``USER_LABEL_SOURCE_TYPE``, the same constant the persistence path
    (:func:`app.estimator.persist._persist_resolved_labels`) writes, so the two
    cannot drift. Optionally filtered to a given ``status`` (``proposed`` for the
    read). A label upload produces exactly one such item; the first is returned
    defensively if more ever exist.
    """

    query = (
        select(DerivedFoodItem)
        .join(EvidenceSource, EvidenceSource.derived_food_item_id == DerivedFoodItem.id)
        .where(
            DerivedFoodItem.log_event_id == event_id,
            DerivedFoodItem.user_id == owner_id,
            EvidenceSource.source_type == USER_LABEL_SOURCE_TYPE,
        )
        .order_by(DerivedFoodItem.created_at.asc(), DerivedFoodItem.id.asc())
    )
    if status is not None:
        query = query.where(DerivedFoodItem.status == status)
    return session.scalars(query).first()
