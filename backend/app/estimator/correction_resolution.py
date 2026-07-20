"""Prior-correction resolution tier (FTY-406).

The user's own corrections are ground truth, but until now they were **write-only
telemetry** — the ``corrections`` audit trail recorded every hand-edit and never
read them back at estimate time. So a food the user had already corrected was
re-guessed from scratch on the next log: the operator's "black coffee" first-passed
a deterministic 148.8 kcal source match every single time, was auto-``re_match``ed to
4.8, then hand-edited to 3 — over and over — because nothing consulted the 343 rows
of curated truth already sitting in the table.

This module closes that loop. It is a **resolution source**: before the guessed
source tiers (USDA generic / OFF-by-name / official / reference / model-prior) run,
a candidate whose normalized name matches a food the user has previously **hand
corrected** (a ``user_edit`` on ``calories``) resolves from that prior correction —
the corrected value with :class:`~app.enums.SourceType.PRIOR_CORRECTION` provenance —
short-circuiting the wrong first guess.

Precedence (``food-resolution.md`` → **Prior-Correction Resolution (FTY-406)**):
it outranks every *guessed* source but sits **below** the current entry's own
explicit evidence — a stated calorie total (``user_text``), a scanned label
(``user_label``), or a barcode — because those describe *this* log, while a prior
correction is remembered ground truth for the *name*. The step therefore runs after
the rank-1 user-provided steps and skips a candidate that carries a barcode.

Authority and fall-through (never worse than today):

- **Per-user, name-normalized.** Only the acting user's own corrections are read
  (:func:`~app.normalization.normalize_text`, the saved-food matching rule), so there
  is no cross-user leakage — another user's "black coffee" is never consulted.
- **Authoritative only on a stable prior value.** When the user has corrected the
  same normalized name to *conflicting* values, the priors are ambiguous and the
  candidate falls through to normal resolution. A single stable corrected value (or
  several that agree) is authoritative.
- **Quantity: direct match or a rescale, else fall through.** A candidate whose
  portion matches the prior correction's resolves to the corrected total directly;
  a *different* quantity is **rescaled** from a mass-bearing prior (per-gram × the
  new grams) rather than mismatched; when neither a direct match nor a safe rescale
  applies, the candidate falls through to normal resolution — so an item with no
  usable prior correction resolves exactly as it does today.

Security/privacy: correction lookups are strictly per-user and read only the
already-persisted corrected numbers; no raw diary text is read or persisted (the
evidence row stores the projected facts + a content hash, mirroring ``user_text``).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import CorrectionSource, SourceType
from app.estimator.evidence_utils import _record_source_ref
from app.estimator.food_serving import resolve_grams
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    ResolvedFoodItem,
)
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.log_events import LogEvent
from app.normalization import normalize_text

#: Source-system id / classification for a value replayed from a prior user
#: correction. Both are the same literal (there is one system, one tier); kept as two
#: names so call sites read intent (``source`` on the run ``source_refs``,
#: ``source_type`` on the evidence row) exactly like the other tiers.
PRIOR_CORRECTION_SOURCE = SourceType.PRIOR_CORRECTION.value
PRIOR_CORRECTION_SOURCE_TYPE = SourceType.PRIOR_CORRECTION.value

#: The fact basis for a replayed correction: it is the corrected **total** for the
#: logged item (like a ``user_text`` as-logged total), never a per-100g density, so
#: the serving math must not re-scale the snapshot. A rescaled projection has already
#: been scaled here in Python; the stored total is still an as-logged total.
AS_LOGGED_BASIS = "as_logged"

#: Content-free assumption recorded when the prior correction was for a *different*
#: quantity and the value was rescaled per-gram to the current portion (never the raw
#: name, quantity text, or any nutrition value — just the fixed label).
PRIOR_CORRECTION_RESCALED_ASSUMPTION = "prior_correction_rescaled"

#: Rounding for the compared/stored calorie total — the same 0.1 rule the serving
#: math and the corrections service use, so a stability comparison never trips on
#: floating dust.
_VALUE_DECIMALS = 1
#: Rounding for the compared per-gram density used by the rescale-stability check.
_PER_GRAM_DECIMALS = 6


def _portion_key(unit: str | None, amount: float | None, quantity_text: str) -> tuple[str, ...]:
    """A comparable signature of a candidate's stated portion.

    Two portions are the *same* iff this key is equal: a normalized unit, the numeric
    amount, and the normalized quantity phrase. An item with no unit, no amount, and
    no quantity phrase collapses to a single ``unportioned`` sentinel so a bare "black
    coffee" logged twice compares equal (and resolves directly from the prior value).
    """

    normalized_unit = (unit or "").strip().casefold()
    normalized_text = normalize_text(quantity_text or "")
    if not normalized_unit and amount is None and not normalized_text:
        return ("unportioned",)
    return (normalized_unit, "" if amount is None else f"{amount}", normalized_text)


@dataclass(frozen=True)
class _CorrectionProjection:
    """The value a prior correction contributes for one candidate, ready to persist."""

    calories: float
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    grams: float | None
    rescaled: bool


def _round_value(value: float) -> float:
    return round(value, _VALUE_DECIMALS)


def _calories(item: DerivedFoodItem) -> float:
    """The item's corrected calories as a concrete ``float``.

    Every item reaching the projection has passed the ``item.calories is None`` skip in
    :meth:`PriorCorrectionResolver._matching_corrected_items`, so the nullable column is
    known non-``None`` here; the cast narrows it for the type checker.
    """

    return cast("float", item.calories)


def _scale(value: float | None, ratio: float) -> float | None:
    """Scale a macro/total by ``ratio``; ``None`` (unknown) stays unknown."""

    return None if value is None else _round_value(value * ratio)


@dataclass(frozen=True)
class PriorCorrectionResolver:
    """Resolve a candidate from the acting user's own prior corrections (FTY-406).

    Owns the per-user, name-normalized lookup over the ``corrections`` audit trail and
    the direct-match / rescale / fall-through projection. Constructed by the worker
    with the request session; the step calls :meth:`resolve` per candidate.
    """

    session: Session

    def resolve(
        self, user_id: uuid.UUID, candidate: CandidateDraft
    ) -> _CorrectionProjection | None:
        """Return the value a confident prior correction contributes, else ``None``.

        ``None`` means "fall through to normal resolution" — no matching prior, an
        ambiguous/conflicting set of priors, or a quantity that can be neither matched
        nor safely rescaled — so a candidate with no usable prior correction resolves
        exactly as it does today (no regression).
        """

        query_key = normalize_text(candidate.name)
        if not query_key:
            return None

        items = self._matching_corrected_items(user_id, query_key)
        if not items:
            return None
        return self._project(items, candidate)

    def _matching_corrected_items(
        self, user_id: uuid.UUID, query_key: str
    ) -> list[DerivedFoodItem]:
        """The user's hand-corrected food items whose normalized name == ``query_key``.

        Only the acting user's rows (``DerivedFoodItem.user_id``) are read — the
        per-user isolation boundary — and only items carrying a ``user_edit``
        correction on ``calories`` (the user's deliberate value override, not a
        re-match or an amount rescale) whose parent log event is **not voided**. The
        rows are ordered most-recently-corrected first and de-duplicated (an item with
        several corrections joins several times), then filtered by normalized name in
        Python because the normalization (diacritic/case fold) is not expressible in
        portable SQL.
        """

        rows = self.session.scalars(
            select(DerivedFoodItem)
            .join(Correction, Correction.derived_food_item_id == DerivedFoodItem.id)
            .join(LogEvent, LogEvent.id == DerivedFoodItem.log_event_id)
            .where(
                DerivedFoodItem.user_id == user_id,
                Correction.source == CorrectionSource.USER_EDIT,
                Correction.field == "calories",
                LogEvent.voided_at.is_(None),
            )
            .order_by(Correction.created_at.desc())
        ).all()

        items: list[DerivedFoodItem] = []
        seen: set[uuid.UUID] = set()
        for item in rows:
            if item.id in seen:
                continue
            seen.add(item.id)
            if item.calories is None:
                continue
            if normalize_text(item.name) == query_key:
                items.append(item)
        return items

    def _project(
        self, items: list[DerivedFoodItem], candidate: CandidateDraft
    ) -> _CorrectionProjection | None:
        """Pick the authoritative prior value for ``candidate`` (direct or rescaled).

        Prefers a **direct** portion match (the corrected total applies verbatim); when
        the candidate's quantity differs, **rescales** from a mass-bearing prior. Either
        branch is authoritative only when its priors agree (stable value / stable
        per-gram density); a conflict is ambiguous and falls through.
        """

        candidate_key = _portion_key(candidate.unit, candidate.amount, candidate.quantity_text)

        direct = [
            item
            for item in items
            if _portion_key(item.unit, item.amount, item.quantity_text) == candidate_key
        ]
        if direct:
            if not _totals_stable(direct):
                return None
            authoritative = direct[0]
            return _CorrectionProjection(
                calories=_round_value(_calories(authoritative)),
                protein_g=authoritative.protein_g,
                carbs_g=authoritative.carbs_g,
                fat_g=authoritative.fat_g,
                grams=authoritative.grams,
                rescaled=False,
            )

        return self._rescale(items, candidate)

    def _rescale(
        self, items: list[DerivedFoodItem], candidate: CandidateDraft
    ) -> _CorrectionProjection | None:
        """Rescale a mass-bearing prior correction to the candidate's current portion.

        Uses the corrected per-gram density of the most recent mass-bearing prior,
        scaled to the grams the candidate's own quantity resolves to (the prior's
        portion mass seeds the count/default-serving math). Authoritative only when the
        mass-bearing priors share a stable per-gram density; otherwise — or when the
        candidate's quantity does not resolve to grams — it falls through.
        """

        massed = [item for item in items if item.grams is not None and item.grams > 0]
        if not massed or not _per_gram_stable(massed):
            return None

        authoritative = massed[0]
        prior_grams = authoritative.grams
        if prior_grams is None or prior_grams <= 0:  # guaranteed by ``massed``; narrows the type
            return None
        new_grams = resolve_grams(
            unit=candidate.unit,
            amount=candidate.amount,
            quantity_text=candidate.quantity_text,
            default_serving_g=prior_grams,
        )
        if new_grams is None or new_grams <= 0:
            return None

        ratio = new_grams / prior_grams
        return _CorrectionProjection(
            calories=_round_value(_calories(authoritative) * ratio),
            protein_g=_scale(authoritative.protein_g, ratio),
            carbs_g=_scale(authoritative.carbs_g, ratio),
            fat_g=_scale(authoritative.fat_g, ratio),
            grams=round(new_grams, 3),
            rescaled=True,
        )


def _totals_stable(items: list[DerivedFoodItem]) -> bool:
    """Whether every same-portion prior agrees on the corrected total (else ambiguous)."""

    first = _round_value(_calories(items[0]))
    return all(_round_value(_calories(item)) == first for item in items)


def _per_gram_stable(items: list[DerivedFoodItem]) -> bool:
    """Whether every mass-bearing prior agrees on the corrected per-gram density.

    Called only with ``massed`` items (positive ``grams``); a non-positive/absent
    ``grams`` is skipped defensively so the density is always well-defined.
    """

    densities: list[float] = []
    for item in items:
        grams = item.grams
        if grams is None or grams <= 0:
            continue
        densities.append(round(_calories(item) / grams, _PER_GRAM_DECIMALS))
    if not densities:
        return False
    return all(density == densities[0] for density in densities)


def _content_hash(projection: _CorrectionProjection) -> str:
    """A reproducible fingerprint of the projected facts (no raw name or diary text)."""

    def fmt(value: float | None) -> str:
        return "null" if value is None else f"{value}"

    canonical = (
        f"{PRIOR_CORRECTION_SOURCE}|{AS_LOGGED_BASIS}|{projection.calories}|"
        f"{fmt(projection.protein_g)}|{fmt(projection.carbs_g)}|{fmt(projection.fat_g)}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PriorCorrectionMatch:
    """The value + reference a confident prior correction contributes to a candidate.

    Produced by :func:`match_prior_correction` for the re-match candidate surface
    (FTY-411): the corrected total for the queried portion (direct-matched or rescaled),
    the ``prior_correction:<content_hash>`` reference the apply path echoes back and
    re-derives from, and the ``rescaled`` flag driving the honest rescaled provenance.
    Carries only the acting user's own projected numbers — never another user's rows and
    never raw diary text. Macros stay ``None`` when the correction never supplied them
    (unknown ≠ a fabricated ``0``).
    """

    source_ref: str
    content_hash: str
    calories: float
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    grams: float | None
    rescaled: bool


def prior_correction_source_ref(content_hash: str) -> str:
    """The stable ``prior_correction:<content_hash>`` reference for a projected value."""

    return f"{PRIOR_CORRECTION_SOURCE}:{content_hash}"


def match_prior_correction(
    session: Session, user_id: uuid.UUID, candidate: CandidateDraft
) -> PriorCorrectionMatch | None:
    """Project ``user_id``'s confident prior correction for ``candidate``, else ``None``.

    The read half of the re-match candidate surface (FTY-411): it reuses the exact
    FTY-406 :class:`PriorCorrectionResolver` — the same per-user, name-normalized lookup,
    stable-value/ambiguity gate, and direct-match-vs-rescale serving math — so a surfaced
    or applied candidate reproduces estimate-time resolution rather than a parallel
    re-implementation. ``None`` means "no confident prior correction" (no matching name,
    ambiguous priors, or an un-rescalable quantity), so the surface offers nothing and
    the item's ordinary candidates are unaffected (no regression). Only ``user_id``'s own
    rows are read — no cross-user leakage.
    """

    projection = PriorCorrectionResolver(session).resolve(user_id, candidate)
    if projection is None:
        return None
    content_hash = _content_hash(projection)
    return PriorCorrectionMatch(
        source_ref=prior_correction_source_ref(content_hash),
        content_hash=content_hash,
        calories=projection.calories,
        protein_g=projection.protein_g,
        carbs_g=projection.carbs_g,
        fat_g=projection.fat_g,
        grams=projection.grams,
        rescaled=projection.rescaled,
    )


@dataclass(frozen=True)
class PriorCorrectionResolveStep:
    """Resolve candidates from the acting user's prior corrections before source lookup.

    Runs after the rank-1 user-provided steps (``user_text`` / image-label facts) and
    before the USDA/OFF food step. It **claims** each generic candidate a confident
    prior correction resolves — removing it from ``context.food_candidates`` so the food
    step only resolves the rest — and skips a candidate carrying a barcode (a scanned
    product is the current entry's own explicit evidence and resolves via OFF).
    """

    resolver: PriorCorrectionResolver
    name: str = "prior_correction_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        if not context.food_candidates:
            context.record_step(self.name, "skipped")
            return

        remaining: list[CandidateDraft] = []
        claimed: list[tuple[CandidateDraft, _CorrectionProjection]] = []
        for candidate in context.food_candidates:
            projection = (
                None if candidate.barcode else self.resolver.resolve(context.user_id, candidate)
            )
            if projection is None:
                remaining.append(candidate)
            else:
                claimed.append((candidate, projection))

        if not claimed:
            context.record_step(self.name, "skipped")
            return

        context.food_candidates = remaining
        for candidate, projection in claimed:
            _record_source_ref(context, PRIOR_CORRECTION_SOURCE)
            context.resolved_food_items.append(self._build(context, candidate, projection))

        context.record_step(self.name, "ok")

    def _build(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        projection: _CorrectionProjection,
    ) -> ResolvedFoodItem:
        """Build the resolved item + prior-correction provenance for one claim."""

        assumptions: tuple[str, ...] = ()
        if projection.rescaled:
            assumptions = (PRIOR_CORRECTION_RESCALED_ASSUMPTION,)
            for assumption in assumptions:
                if assumption not in context.assumptions:
                    context.assumptions.append(assumption)

        content_hash = _content_hash(projection)
        return ResolvedFoodItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            grams=projection.grams,
            calories=projection.calories,
            protein_g=projection.protein_g,
            carbs_g=projection.carbs_g,
            fat_g=projection.fat_g,
            product_id=None,
            source_type=PRIOR_CORRECTION_SOURCE_TYPE,
            source_ref=f"{PRIOR_CORRECTION_SOURCE}:{content_hash}",
            content_hash=content_hash,
            fetched_at=datetime.now(UTC),
            calories_per_100g=projection.calories,
            protein_per_100g=projection.protein_g,
            carbs_per_100g=projection.carbs_g,
            fat_per_100g=projection.fat_g,
            assumptions=assumptions,
            basis=AS_LOGGED_BASIS,
        )
