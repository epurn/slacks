"""Corrections + edit service (FTY-051).

This module owns the deterministic edit semantics behind the corrections-audit
contract:

1. **Object-level authorization.** Every edit runs through :func:`_authorize`
   (the caller must own the targeted user) and loads the item *scoped to that
   user*, so a cross-user id is indistinguishable from a missing one. Both fail
   closed — the router renders them ``404`` — so a non-owner edit neither mutates
   state nor reveals that the item exists.

2. **Snapshot-then-override.** Before a value is changed, its estimator original
   is snapshotted into the matching ``*_estimated`` column **exactly once** (at
   creation by the estimator, or here on the first edit if not already set) and
   never mutated again. The current value is then overwritten (last edit wins).

3. **The servings rescale rule (provenance-preserving).** Editing a food item's
   ``quantity`` rescales its current calories and macros by
   ``ratio = new_quantity / old_quantity`` and appends a correction row for the
   quantity change **and** for each rescaled field, every row tagged
   :attr:`~app.enums.CorrectionSource.AMOUNT_ADJUST`. A portion fix is **not** a
   re-resolution: the item's evidence/source snapshot is untouched and the item
   stays un-edited (``is_edited`` false, FTY-092). A direct edit to a single value
   field is a **value override** — it overrides only that field, appends exactly one
   :attr:`~app.enums.CorrectionSource.USER_EDIT` row, and marks the item edited.

Every change appends an immutable :class:`~app.models.corrections.Correction`.
Old/new values are sensitive personal data and are never written to logs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import CandidateType, CorrectionSource
from app.models.corrections import Correction
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.models.identity import User

#: Either kind of editable derived item.
DerivedItem = DerivedFoodItem | DerivedExerciseItem

#: Canonical rounding for energy/macros/burn — the same 0.1 rule the FTY-043/044
#: serving math uses, so corrected values match estimator-produced ones.
_VALUE_DECIMALS = 1
#: Servings/quantity precision, matching the resolved-grams precision (FTY-044).
_QUANTITY_DECIMALS = 3

#: Sanity upper bounds in canonical units. Non-negativity is enforced at the DTO;
#: these reject obviously-invalid magnitudes with a clear error rather than storing
#: nonsense. Generous: a real meal/exercise never approaches them.
_MAX_ENERGY = 100_000.0
_MAX_MACRO_G = 100_000.0
_MAX_QUANTITY = 100_000.0

#: The field name for a food item's servings/quantity edit (maps to ``amount``);
#: editing it triggers the rescale rule rather than a direct override.
QUANTITY_FIELD = "quantity"

#: Editable value fields per item type → ``(attribute, estimated_attribute,
#: upper_bound)``. These are the fields the rescale rule and direct edits act on.
_FOOD_VALUE_FIELDS: dict[str, tuple[str, str, float]] = {
    "calories": ("calories", "calories_estimated", _MAX_ENERGY),
    "protein_g": ("protein_g", "protein_g_estimated", _MAX_MACRO_G),
    "carbs_g": ("carbs_g", "carbs_g_estimated", _MAX_MACRO_G),
    "fat_g": ("fat_g", "fat_g_estimated", _MAX_MACRO_G),
}
_EXERCISE_VALUE_FIELDS: dict[str, tuple[str, str, float]] = {
    "active_calories": ("active_calories", "active_calories_estimated", _MAX_ENERGY),
}


class DerivedItemForbidden(Exception):
    """Raised when a caller tries to edit a derived item they do not own."""


class DerivedItemNotFound(Exception):
    """Raised when no derived item of the requested type/id exists for the owner."""


class InvalidCorrection(Exception):
    """Raised when an edit is structurally valid but semantically rejected.

    Carries a stable ``code`` and the offending ``field`` so the router can render
    a clear, machine-readable error shape without leaking item contents.
    """

    def __init__(self, code: str, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code}: {field}")


@dataclass(frozen=True)
class EditResult:
    """The outcome of an edit: the updated item and the appended correction rows."""

    item: DerivedItem
    corrections: list[Correction]


def edit_derived_item(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    item_type: CandidateType,
    item_id: uuid.UUID,
    field: str,
    value: float,
) -> EditResult:
    """Apply a single field edit to one of ``owner_id``'s derived items.

    Enforces ownership, snapshots the original, applies the override (or the
    servings rescale), appends the correction row(s), and commits atomically so
    the item update and its audit rows land together.
    """

    _authorize(owner_id, current_user)
    item = _load_owned(session, item_type, item_id, owner_id)

    corrections = _apply_edit(owner_id, item_type, item, field, value)

    session.add_all(corrections)
    session.commit()
    session.refresh(item)
    return EditResult(item=item, corrections=corrections)


def apply_item_edit(
    owner_id: uuid.UUID,
    item_type: CandidateType,
    item: DerivedItem,
    field: str,
    value: float,
) -> list[Correction]:
    """Apply one field edit to an already-owned, session-attached item, no commit.

    Mutates ``item`` in place (value override or servings rescale) and returns the
    correction row(s) the caller must ``add`` and commit inside its own
    transaction. This is the same deterministic, provenance-honest logic the edit
    endpoint uses (:func:`edit_derived_item`), factored out so the label-proposal
    confirm gate (FTY-196) can adjust proposed values and flip the item to
    ``resolved`` in a single transaction. Raises :class:`InvalidCorrection` on an
    unknown field / out-of-range value / invalid quantity, exactly as the endpoint.
    """

    return _apply_edit(owner_id, item_type, item, field, value)


def _apply_edit(
    owner_id: uuid.UUID,
    item_type: CandidateType,
    item: DerivedItem,
    field: str,
    value: float,
) -> list[Correction]:
    """Validate the field for the item type and apply the matching edit rule."""

    if item_type is CandidateType.FOOD and field == QUANTITY_FIELD:
        return _apply_quantity_rescale(owner_id, item, value)

    value_fields = _FOOD_VALUE_FIELDS if item_type is CandidateType.FOOD else _EXERCISE_VALUE_FIELDS
    spec = value_fields.get(field)
    if spec is None:
        raise InvalidCorrection("unknown_field", field)
    return [_apply_direct(owner_id, item_type, item, field, spec, value)]


def _apply_direct(
    owner_id: uuid.UUID,
    item_type: CandidateType,
    item: DerivedItem,
    field: str,
    spec: tuple[str, str, float],
    value: float,
) -> Correction:
    """Override a single value field, snapshotting its original first.

    A direct override is a ``user_edit``: it marks the item edited (FTY-092).
    """

    attribute, estimated_attribute, upper_bound = spec
    _check_upper_bound(field, value, upper_bound)

    old_value = getattr(item, attribute)
    _snapshot_original(item, estimated_attribute, old_value)
    new_value = round(value, _VALUE_DECIMALS)
    setattr(item, attribute, new_value)
    return _make_correction(
        owner_id, item_type, item, field, old_value, new_value, CorrectionSource.USER_EDIT
    )


def _apply_quantity_rescale(
    owner_id: uuid.UUID, item: DerivedItem, value: float
) -> list[Correction]:
    """Rescale a food item's calories/macros by ``new_quantity / old_quantity``.

    A **provenance-preserving** adjustment (FTY-092): writes an ``amount_adjust``
    correction for the quantity change and for each currently-resolved field that is
    rescaled, leaving the item's ``evidence_sources`` snapshot untouched and the item
    un-edited. Fails closed on a zero/invalid old quantity (no ratio is defined) or a
    non-positive new quantity.
    """

    _check_upper_bound(QUANTITY_FIELD, value, _MAX_QUANTITY)
    old_quantity = item.amount
    if old_quantity is None or old_quantity <= 0:
        raise InvalidCorrection("invalid_old_quantity", QUANTITY_FIELD)
    if value <= 0:
        raise InvalidCorrection("invalid_quantity", QUANTITY_FIELD)

    new_quantity = round(value, _QUANTITY_DECIMALS)
    ratio = new_quantity / old_quantity

    corrections = [
        _make_correction(
            owner_id,
            CandidateType.FOOD,
            item,
            QUANTITY_FIELD,
            old_quantity,
            new_quantity,
            CorrectionSource.AMOUNT_ADJUST,
        )
    ]
    item.amount = new_quantity

    for field, (attribute, estimated_attribute, _bound) in _FOOD_VALUE_FIELDS.items():
        current = getattr(item, attribute)
        if current is None:
            # An unresolved field has no value to rescale; skip it (no correction).
            continue
        _snapshot_original(item, estimated_attribute, current)
        rescaled = round(current * ratio, _VALUE_DECIMALS)
        setattr(item, attribute, rescaled)
        corrections.append(
            _make_correction(
                owner_id,
                CandidateType.FOOD,
                item,
                field,
                current,
                rescaled,
                CorrectionSource.AMOUNT_ADJUST,
            )
        )

    return corrections


def _snapshot_original(item: DerivedItem, estimated_attribute: str, current: float | None) -> None:
    """Capture the estimator original exactly once; never overwrite it.

    If the estimated column is already set (at creation or a prior edit) it is left
    untouched. A ``None`` current value means there was no estimate to preserve.
    """

    if getattr(item, estimated_attribute) is None and current is not None:
        setattr(item, estimated_attribute, current)


def _check_upper_bound(field: str, value: float, upper_bound: float) -> None:
    """Reject an out-of-range value (non-negativity is already enforced at the DTO)."""

    if value > upper_bound:
        raise InvalidCorrection("out_of_range", field)


def _make_correction(
    owner_id: uuid.UUID,
    item_type: CandidateType,
    item: DerivedItem,
    field: str,
    old_value: float | None,
    new_value: float,
    source: CorrectionSource,
) -> Correction:
    """Build an immutable correction row for one field change.

    ``source`` distinguishes a value override (``user_edit``) from a
    provenance-preserving portion change (``amount_adjust``) — the signal that
    drives the read-model's ``is_edited`` flag (FTY-092).
    """

    return Correction(
        user_id=owner_id,
        item_type=item_type,
        derived_food_item_id=item.id if item_type is CandidateType.FOOD else None,
        derived_exercise_item_id=item.id if item_type is CandidateType.EXERCISE else None,
        field=field,
        old_value=old_value,
        new_value=new_value,
        source=source,
    )


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s derived items."""

    if owner_id != current_user.id:
        raise DerivedItemForbidden("cross-user derived-item edit denied")


def _load_owned(
    session: Session,
    item_type: CandidateType,
    item_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> DerivedItem:
    """Load a derived item by id, scoped to ``owner_id`` so cross-user ids 404.

    The query is constrained to the owner, so another user's item is
    indistinguishable from a missing one — no existence oracle.
    """

    model: type[DerivedItem] = (
        DerivedFoodItem if item_type is CandidateType.FOOD else DerivedExerciseItem
    )
    item = session.scalars(
        select(model).where(model.id == item_id, model.user_id == owner_id)
    ).one_or_none()
    if item is None:
        raise DerivedItemNotFound("derived item not found")
    return cast("DerivedItem", item)
