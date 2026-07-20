"""Prior-correction candidate/apply path for the re-match sheet (FTY-411).

Extracted verbatim from :mod:`app.estimator.re_match` (FTY-413) as the cohesive
prior-correction concern: listing the acting user's own confident correction as a
top-ranked "Your correction" choice, and applying a chosen one by re-deriving it
from the corrections trail. It depends on the shared re_match audit/evidence
helpers (:func:`~app.estimator.re_match.record_re_match_correction`,
:func:`~app.estimator.re_match._evidence_row`) and the re_match trust-anchor
exception (:class:`~app.estimator.re_match.SourceNotResolvable`) **by import** —
they stay in ``re_match`` (shared with the USDA source-cache path). ``re_match``
in turn defers its import of this module (inside the delegating methods) so the
two-way ``re_match`` ↔ ``prior_correction_candidates`` edge never forms a
module-load cycle.

The trust anchor is unchanged from FTY-411: the client supplies only a
``prior_correction:<content_hash>`` reference, never facts; the server re-projects
the correction over the item's own portion via the FTY-406 resolver and requires
the recomputed reference to match. Reads and applies are strictly per-user — the
owning user's own rows only — with the authorization + object load performed by
the :class:`~app.estimator.re_match.ReMatchCapability` methods that delegate here.
No network egress, no ``products`` cache write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.orm import Session

from app.enums import DerivedItemStatus
from app.estimator.correction_resolution import (
    AS_LOGGED_BASIS,
    PRIOR_CORRECTION_RESCALED_ASSUMPTION,
    PRIOR_CORRECTION_SOURCE_TYPE,
    PriorCorrectionMatch,
    match_prior_correction,
)
from app.estimator.pipeline import CandidateDraft
from app.estimator.re_match import (
    SourceNotResolvable,
    _evidence_row,
    record_re_match_correction,
)
from app.models.derived import DerivedFoodItem

#: Hard cap on prior-correction candidates surfaced per item (FTY-411). The FTY-406
#: resolver collapses an item's matching priors to a **single** authoritative value
#: (direct match or rescale), so a well-formed surface is 0 or 1; this cap is a
#: defensive bound in the same spirit as :data:`~app.estimator.re_match.MAX_ALTERNATIVES`
#: for the USDA fan-out.
MAX_PRIOR_CORRECTION_CANDIDATES: Final[int] = 1


@dataclass(frozen=True)
class PriorCorrectionCandidate:
    """A prior-correction match surfaced for the re-match sheet (FTY-411).

    The acting user's own confident correction for this item's normalized name, offered
    as a top-ranked "Your correction" choice **alongside** the guessed-source
    :class:`~app.estimator.re_match.SourceCandidate` list. Unlike a source candidate its
    facts are the corrected **as-logged total** for the item's own portion (never a
    per-100g density), a macro the correction never supplied is honestly ``None``
    (unknown, never a fabricated ``0``), and its ``source_ref`` is re-derived from the
    corrections trail on apply — never from the ``products`` cache. ``rescaled`` marks a
    value carried from a different-portion prior via per-gram rescale.
    """

    source_ref: str
    name: str
    basis: str
    calories: float
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    rescaled: bool


def _draft_from_item(item: DerivedFoodItem) -> CandidateDraft:
    """A parse-shaped draft of an existing item, for the prior-correction resolver.

    Carries only the item's identity + portion (name, quantity phrase, unit, amount) so
    the FTY-406 resolver keys the same per-user, name-normalized lookup and portion
    signature it uses at estimate time — no barcode/brand/stated facts, because a
    re-match reads remembered ground truth for the name, not fresh evidence for the entry.
    """

    return CandidateDraft(
        name=item.name,
        quantity_text=item.quantity_text or "",
        unit=item.unit,
        amount=item.amount,
    )


def list_prior_correction_candidates(
    session: Session, item: DerivedFoodItem
) -> list[PriorCorrectionCandidate]:
    """List the owner's confident prior correction for their food ``item`` (FTY-411).

    Reuses the FTY-406 resolver over the item's own portion: when a confident, stable
    prior correction direct-matches or rescales to the item's quantity it is surfaced
    as a single top-ranked candidate carrying the corrected values and a
    ``prior_correction:<content_hash>`` reference the apply path re-derives — never a
    ``products`` cache row. When there is none the list is empty and the item's
    ordinary (USDA) candidates are unaffected, so there is no regression. Strictly
    per-user and name-normalized: only the owning user's own rows are read (the caller's
    :meth:`~app.estimator.re_match.ReMatchCapability.list_prior_correction_candidates`
    fails a cross-user or unknown item closed before delegating here); another user's
    correction is never surfaced. Bounded by :data:`MAX_PRIOR_CORRECTION_CANDIDATES`.
    Reads only — no network egress, no cache write.
    """

    match = match_prior_correction(session, item.user_id, _draft_from_item(item))
    if match is None:
        return []
    candidate = PriorCorrectionCandidate(
        source_ref=match.source_ref,
        name=item.name,
        basis=AS_LOGGED_BASIS,
        calories=match.calories,
        protein_g=match.protein_g,
        carbs_g=match.carbs_g,
        fat_g=match.fat_g,
        rescaled=match.rescaled,
    )
    return [candidate][:MAX_PRIOR_CORRECTION_CANDIDATES]


def apply_prior_correction(
    session: Session, item: DerivedFoodItem, source_ref: str
) -> DerivedFoodItem:
    """Apply a chosen prior-correction candidate, re-derived from the corrections trail.

    The prior-correction half of the apply path (FTY-411): it re-projects the acting
    user's confident correction for the item's own portion via the FTY-406 resolver
    (never the ``products`` cache) and requires the recomputed
    ``prior_correction:<content_hash>`` reference to equal the one the client echoed —
    a stale/unknown reference is rejected (:class:`SourceNotResolvable`) and nothing
    mutates, the same trust anchor the source-cache path uses (the client supplies a
    reference, never facts). On success it reproduces FTY-406's estimate-time result:
    the corrected as-logged values (direct match or per-gram rescale) with
    :attr:`~app.enums.SourceType.PRIOR_CORRECTION` provenance and **no** ``products``
    row, re-snapshots the ``*_estimated`` originals, and appends the ``re_match`` audit
    row that supersedes any prior ``user_edit`` — so the item honestly reads
    ``is_edited == false`` (its truth is the user's own curated value, not a stale
    override). Issues no network egress.
    """

    match = match_prior_correction(session, item.user_id, _draft_from_item(item))
    if match is None or match.source_ref != source_ref:
        raise SourceNotResolvable(source_ref)

    prior_calories = item.calories
    item.status = DerivedItemStatus.RESOLVED
    item.grams = match.grams
    item.calories = match.calories
    item.protein_g = match.protein_g
    item.carbs_g = match.carbs_g
    item.fat_g = match.fat_g
    item.calories_estimated = match.calories
    item.protein_g_estimated = match.protein_g
    item.carbs_g_estimated = match.carbs_g
    item.fat_g_estimated = match.fat_g
    _rewrite_prior_correction_evidence(session, item, match)
    record_re_match_correction(
        session, item, old_calories=prior_calories, new_calories=match.calories
    )

    session.commit()
    session.refresh(item)
    return item


def _rewrite_prior_correction_evidence(
    session: Session, item: DerivedFoodItem, match: PriorCorrectionMatch
) -> None:
    """Rewrite the item's evidence to prior-correction provenance (FTY-411).

    Mirrors FTY-406's persisted prior-correction row so an applied candidate is
    indistinguishable from an estimate-time prior-correction resolution:
    ``source_type = prior_correction``, the ``prior_correction:<content_hash>``
    reference, ``as_logged`` basis (the stored numbers are the corrected **total**,
    not a per-100g density, so the read model never re-scales them), **no**
    ``product_id`` (per-user curated truth, not a shared cache row), the content-free
    ``prior_correction_rescaled`` assumption only when the value was rescaled to a
    different portion, and a homogeneous single-source ``field_provenance`` of
    ``None``. The per-100g columns hold the corrected as-logged totals, exactly as the
    FTY-406 estimate-time step persists them.
    """

    evidence = _evidence_row(session, item)
    evidence.product_id = None
    evidence.source_type = PRIOR_CORRECTION_SOURCE_TYPE
    evidence.source_ref = match.source_ref
    evidence.content_hash = match.content_hash
    evidence.fetched_at = datetime.now(UTC)
    evidence.basis = AS_LOGGED_BASIS
    evidence.calories_per_100g = match.calories
    evidence.protein_per_100g = match.protein_g
    evidence.carbs_per_100g = match.carbs_g
    evidence.fat_per_100g = match.fat_g
    evidence.field_provenance = None
    evidence.assumptions = [PRIOR_CORRECTION_RESCALED_ASSUMPTION] if match.rescaled else None
