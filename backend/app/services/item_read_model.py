"""Per-item provenance read-model: source descriptor + ``is_edited`` (FTY-092).

The Today timeline renders an always-on **source icon** and a **"✎ edited"** marker
per item. Both signals are **derived at read time** from already-stored data — there
is no new persisted provenance column and no de-normalized read table:

- :func:`build_item_source` maps an item's ``evidence_sources`` row to the
  :class:`~app.schemas.corrections.ItemSourceDTO` descriptor (``source_type``,
  display ``label``, ``ref``). A finalized food item always has an evidence record
  (model-prior included, per the Fallback Rule); if one is absent — or the item is
  an exercise item, whose burn comes from MET tables rather than an evidence row —
  the descriptor is ``None`` defensively rather than failing the read.

- :func:`item_is_edited` is ``True`` iff the item carries a ``user_edit``
  **value-override** correction that has not been **superseded by a later re-match**
  (FTY-093). A never-edited item and an item that has only been **amount-adjusted** are
  both ``False`` — this is the distinction that lets a portion fix recompute the numbers
  while keeping the item's source icon. A re-match re-aims the item to a fresh source, so
  it clears the edited marker honestly (the new source, not the old override, is the
  truth).

:func:`serialize_food_item` / :func:`serialize_exercise_item` are the shared
serializers every read path uses, so the descriptor and flag are computed once and
inherited consistently rather than re-derived per endpoint.

Source refs, labels, and item values are sensitive personal data and are never
logged here — only ids cross into logs (per ``docs/security/security-baseline.md``).
"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.enums import CandidateType, CorrectionSource, SourceType
from app.models.corrections import Correction
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.schemas.corrections import (
    DerivedExerciseItemDTO,
    DerivedFoodItemDTO,
    ItemSourceDTO,
)

#: Display-ready labels for the source types whose label is fixed. The
#: ``official_source`` / ``reference_source`` host is computed per-item from the URL
#: (see :func:`_source_label`); ``model_prior`` reads "Rough estimate" so the client
#: can render the "≈ rough estimate · make it exact" nudge.
_SOURCE_LABELS: dict[SourceType, str] = {
    SourceType.TRUSTED_NUTRITION_DATABASE: "USDA",
    SourceType.PRODUCT_DATABASE: "Open Food Facts",
    SourceType.USER_LABEL: "Label scan",
    SourceType.MODEL_PRIOR: "Rough estimate",
}

#: Fallback labels for a URL-backed source whose URL host cannot be parsed.
_URL_SOURCE_FALLBACK_LABELS: dict[SourceType, str] = {
    SourceType.OFFICIAL_SOURCE: "Official source",
    SourceType.REFERENCE_SOURCE: "Reference source",
}


def serialize_food_item(session: Session, item: DerivedFoodItem) -> DerivedFoodItemDTO:
    """Build the food-item read DTO, enriched with ``source`` + ``is_edited``."""

    dto = DerivedFoodItemDTO.model_validate(item)
    return dto.model_copy(
        update={
            "source": build_item_source(session, item),
            "is_edited": item_is_edited(session, CandidateType.FOOD, item.id),
        }
    )


def serialize_exercise_item(session: Session, item: DerivedExerciseItem) -> DerivedExerciseItemDTO:
    """Build the exercise-item read DTO, enriched with ``source`` + ``is_edited``.

    Exercise burn has no ``evidence_sources`` row, so ``source`` is ``None``;
    ``is_edited`` follows the same value-override rule as food.
    """

    dto = DerivedExerciseItemDTO.model_validate(item)
    return dto.model_copy(
        update={
            "source": None,
            "is_edited": item_is_edited(session, CandidateType.EXERCISE, item.id),
        }
    )


def build_item_source(session: Session, item: DerivedFoodItem) -> ItemSourceDTO | None:
    """Map a food item's evidence record to its source descriptor, or ``None``.

    Reads only the item's own (user-owned) ``evidence_sources`` row — the
    global-vs-user split is respected, so no cross-user provenance is reachable. A
    missing record, or an unrecognized ``source_type``, yields ``None`` defensively
    rather than failing the read.
    """

    evidence = session.scalars(
        select(EvidenceSource)
        .where(EvidenceSource.derived_food_item_id == item.id)
        .order_by(EvidenceSource.created_at.desc())
    ).first()
    if evidence is None:
        return None

    try:
        source_type = SourceType(evidence.source_type)
    except ValueError:
        # An evidence row with a source_type outside the known hierarchy: surface no
        # descriptor rather than guessing or raising on a read path.
        return None

    return ItemSourceDTO(
        source_type=source_type,
        label=_source_label(source_type, evidence.source_ref),
        ref=evidence.source_ref,
    )


def item_is_edited(session: Session, item_type: CandidateType, item_id: uuid.UUID) -> bool:
    """Return ``True`` iff the item carries a ``user_edit`` not superseded by a re-match.

    Derived from the append-only audit trail, so it never drifts and needs no
    backfill. ``amount_adjust`` corrections never make an item edited. A re-match
    (FTY-093) re-aims the item to a fresh source and appends a ``re_match`` row that
    **supersedes** any prior value override — so a ``user_edit`` only counts when it is
    the latest word, i.e. made *after* the most recent re-match. With no ``re_match``
    row (the common case) this is exactly the FTY-092 rule: edited iff any ``user_edit``
    exists.
    """

    if item_type is CandidateType.FOOD:
        item_match = Correction.derived_food_item_id == item_id
    else:
        item_match = Correction.derived_exercise_item_id == item_id

    last_re_match = session.scalar(
        select(func.max(Correction.created_at)).where(
            item_match,
            Correction.source == CorrectionSource.RE_MATCH,
        )
    )

    user_edit = exists().where(
        item_match,
        Correction.source == CorrectionSource.USER_EDIT,
        *((Correction.created_at > last_re_match,) if last_re_match is not None else ()),
    )
    return bool(session.scalar(select(user_edit)))


def _source_label(source_type: SourceType, source_ref: str) -> str:
    """Map a ``source_type`` / ``source_ref`` to a display-ready label."""

    if source_type in _URL_SOURCE_FALLBACK_LABELS:
        return _url_source_host(source_type, source_ref)
    return _SOURCE_LABELS[source_type]


def _url_source_host(source_type: SourceType, source_ref: str) -> str:
    """Extract the host from an ``<source_type>:<url>`` ref for display.

    Shared by the ``official_source`` and ``reference_source`` tiers, whose ref
    carries the page URL only (no headers/body/query secrets). Falls back to a
    generic per-tier label when the host cannot be parsed.
    """

    prefix = f"{source_type.value}:"
    url = source_ref[len(prefix) :] if source_ref.startswith(prefix) else source_ref
    host = urlparse(url).hostname
    return host or _URL_SOURCE_FALLBACK_LABELS[source_type]
