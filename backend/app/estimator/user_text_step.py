"""User-stated nutrition resolution step (FTY-279 contract; FTY-280 implementation).

The rank-1 ``user_text`` evidence tier: when the user *states* an explicit calorie
total for a recognizable item in the log text ("Sobeys buffalo chicken lime wrap
(580 cals idk the breakdown)"), the parser extracts it into the candidate's
``stated_*`` fields (``parse-candidates.md`` v6) and this step resolves the item
**directly** from that user-provided evidence — counting the calories immediately,
``as_logged`` (never re-scaled) — instead of sending the entry back for a serving
clarification (``food-resolution.md`` → User-Stated Resolution; the no-second-
follow-up rule).

It runs **before** the USDA/OFF food step and *claims* every candidate carrying a
usable stated calorie total, removing it from ``context.food_candidates`` so the
food step only resolves the rest. ``user_text`` outranks USDA/OFF/official/
model-prior for the field(s) the user gave.

For each claimed candidate the step:

1. **Validates** the stated facts as untrusted evidence (``evidence-retrieval.md``):
   finite, non-negative, under the **as-logged abuse cap** (not the per-100g
   plausibility bound — there is no mass), and internally consistent (an Atwater
   cross-check on any co-stated macros). A negative / non-finite / absurd or
   self-contradictory claim **fails closed** to ``needs_clarification`` — never a
   committed impossible total.
2. **Records** a ``resolved`` item whose ``calories`` is the stated total, with a
   ``user_text`` evidence row (``source_ref = user_text:<content_hash>``, ``basis =
   as_logged``, ``field_provenance`` marking ``calories`` ``user_stated``). No global
   ``products`` cache row is written.
3. **Fills missing macros honestly** (:class:`UserTextMacroEstimator`, optional):
   a macro the user did not state is estimated from the item identity in the fixed
   order **single-source reference lookup → comparable-reference aggregate (FTY-281)
   → model-prior cold-pass**, recorded ``field_provenance = estimated`` with the source
   in ``assumptions``, or left **unknown/``None``** — **never** a silent ``0``. The
   macro-estimation engine lives in :mod:`app.estimator.user_text_macro_estimator`
   (extracted FTY-319); this step constructs and calls it. A stated macro is preserved
   exactly (``user_stated``).

A stated calorie figure is the **energy of one logged unit** of the item — a
per-unit *anchor* ("300 calorie sub bun" → 300 kcal for one bun) — so a count /
fraction quantity modifier scales it (FTY-419): "half a 300 calorie sub bun"
(``amount = 0.5``) is trusted for its calories at ``300 × 0.5 = 150`` kcal, and any
stated macro scales the same way. The anchor **hard-overrides** an independent
estimate for the field(s) the user gave; only the *missing* macros are estimated,
now consistent with the scaled energy. A bare stated total with no count quantity
("wrap (580 cals)", ``amount`` absent or 1) and a stated total against a *measured*
mass/volume portion ("100 g chips, 500 cals") are as-logged totals, not per-unit
anchors, so they are counted unscaled.

Security: the raw diary phrase is never persisted — the evidence row stores only the
extracted, validated facts, a hash over them, and the timestamp. The LLM extracts
the stated numbers (upstream, schema-validated); no instruction embedded in the text
is executed, and trusted backend code owns every persisted number.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from app.estimator.evidence_utils import _record_source_ref
from app.estimator.food_serving import _MASS_UNIT_GRAMS, _VOLUME_UNIT_GRAMS
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
)
from app.estimator.user_text_macro_estimator import (
    UserTextMacroEstimator,
    _EstimatedMacros,
)

#: Source-system id / classification for a user-stated nutrition fact (rank 1, the
#: user-provided tier — ``evidence-retrieval.md``). Distinct from ``user_label`` so a
#: client tells a number the user *typed into a log* from one *scanned off a label*.
USER_TEXT_SOURCE = "user_text"
USER_TEXT_SOURCE_TYPE = "user_text"

#: The fact basis for a user-stated total: it is the value for the exact logged item,
#: not a per-reference-quantity fact, and is never re-scaled by the serving math.
AS_LOGGED_BASIS = "as_logged"

#: Per-field provenance values recorded in ``evidence_sources.field_provenance``.
PROVENANCE_USER_STATED = "user_stated"
PROVENANCE_ESTIMATED = "estimated"
PROVENANCE_UNKNOWN = "unknown"

#: Abuse cap on an as-logged calorie total (a single logged item). Mirrors the label
#: path's ``MAX_ENERGY_KCAL`` per-entry ceiling — **not** the per-100g plausibility
#: bound, which needs a mass the user did not give. A stated total above this is
#: absurd for one item and fails closed.
MAX_AS_LOGGED_KCAL = 10_000.0

#: Atwater energy per gram (protein/carb 4, fat 9). Used only for an internal-
#: consistency lower bound: co-stated macros imply *at least* this much energy, so an
#: implied energy grossly exceeding the stated calorie total is self-contradictory.
_KCAL_PER_G_PROTEIN = 4.0
_KCAL_PER_G_CARB = 4.0
_KCAL_PER_G_FAT = 9.0

#: How far the macro-implied Atwater energy may exceed the stated calorie total before
#: the claim is treated as self-contradictory. Generous (macros are approximate and
#: rounding/fibre/alcohol move the sum) so only a *gross* contradiction fails closed:
#: a small ratio slack plus an absolute kcal slack.
_ATWATER_MAX_RATIO = 1.3
_ATWATER_ABS_SLACK_KCAL = 25.0

#: Fixed, sanitized clarification question for a self-contradictory / implausible
#: stated fact — carries no raw diary text.
CONTRADICTORY_FACTS_QUESTION = (
    "Those numbers don't add up for that item. What did you have, and how much?"
)

#: Ordering of the three macros for the estimate/provenance helpers.
_MACRO_NAMES = ("protein_g", "carbs_g", "fat_g")


def _user_text_content_hash(
    calories: float, protein_g: float | None, carbs_g: float | None, fat_g: float | None
) -> str:
    """A reproducible fingerprint of the extracted as-logged facts (no raw text).

    Fingerprints only the bounded, validated numbers (a missing macro renders as
    ``null``), so the provenance is auditable without ever retaining the raw diary
    phrase (``evidence-retrieval.md`` → Privacy and Retention).
    """

    def _fmt(value: float | None) -> str:
        return "null" if value is None else f"{value}"

    canonical = (
        f"{USER_TEXT_SOURCE}|{AS_LOGGED_BASIS}|{calories}|"
        f"{_fmt(protein_g)}|{_fmt(carbs_g)}|{_fmt(fat_g)}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _has_stated_calorie_total(candidate: CandidateDraft) -> bool:
    """Whether ``candidate`` carries a usable stated calorie total (a positive value)."""

    return candidate.stated_calories is not None and candidate.stated_calories > 0


def _is_measured_unit(unit: str | None) -> bool:
    """Whether ``unit`` is a measured mass/volume unit (g, ml, oz, cup, tbsp, …).

    A measured portion means the stated calories are the as-logged total for *that*
    amount, not a per-unit anchor to multiply by the amount (``500 cals`` for ``100 g``
    is 500, not 50 000). Drawn from the serving-math vocabularies so it stays in sync.
    """

    if not unit:
        return False
    key = " ".join(unit.strip().lower().split())
    return key in _MASS_UNIT_GRAMS or key in _VOLUME_UNIT_GRAMS


def _anchor_quantity(candidate: CandidateDraft) -> float:
    """The unit-count multiplier a stated per-unit calorie anchor scales by (FTY-419).

    A stated calorie figure is the energy of one logged unit of the item — a per-unit
    anchor ("300 calorie sub bun" → 300 for one bun). A count / fraction quantity
    modifier scales it: "half" (``amount = 0.5``) → 150 kcal, "2×" (``amount = 2``) →
    600 kcal. Returns ``1.0`` when the item carries no scaling count — a bare stated
    total (``amount`` absent / non-positive) or a measured mass/volume portion, whose
    stated calories are the as-logged total for that amount rather than a per-unit
    anchor. Gross counts are already bounded by the FTY-156 parse plausibility gate.
    """

    amount = candidate.amount
    if amount is None or amount <= 0:
        return 1.0
    if _is_measured_unit(candidate.unit):
        return 1.0
    return amount


def _scaled(value: float | None, multiplier: float) -> float | None:
    """Scale a stated per-unit fact by the anchor multiplier, preserving ``None``."""

    return None if value is None else round(value * multiplier, 1)


def _validate_stated_facts(candidate: CandidateDraft) -> str | None:
    """Return a sanitized failure reason if the stated facts cannot back a number.

    Deterministic, fail-closed checks (``evidence-retrieval.md`` → Validation): every
    stated value finite and non-negative, the as-logged total under the abuse cap, and
    the co-stated macros not implying an energy that grossly exceeds the stated total
    (an Atwater cross-check). Returns ``None`` when the facts are trustworthy.
    """

    calories = candidate.stated_calories
    values = (
        calories,
        candidate.stated_protein_g,
        candidate.stated_carbs_g,
        candidate.stated_fat_g,
    )
    for value in values:
        if value is not None and (not math.isfinite(value) or value < 0):
            return "non_finite_or_negative_stated_fact"

    if calories is None or calories <= 0:
        # This step is only entered for a positive stated calorie total.
        return "no_stated_calorie_total"
    if calories > MAX_AS_LOGGED_KCAL:
        return "stated_calories_over_abuse_cap"

    implied = (
        _KCAL_PER_G_PROTEIN * (candidate.stated_protein_g or 0.0)
        + _KCAL_PER_G_CARB * (candidate.stated_carbs_g or 0.0)
        + _KCAL_PER_G_FAT * (candidate.stated_fat_g or 0.0)
    )
    if implied > calories * _ATWATER_MAX_RATIO + _ATWATER_ABS_SLACK_KCAL:
        return "stated_macros_contradict_calories"
    return None


@dataclass(frozen=True)
class UserTextResolveStep:
    """Resolve user-stated calorie candidates from the rank-1 ``user_text`` tier.

    ``macro_estimator`` is optional: without it, a user-stated item's missing macros
    are simply left unknown (``None``) — the item still resolves and its calories still
    count. The worker wires the full estimator (search + reference fetch + provider) so
    a missing macro is filled from evidence before falling back to unknown.
    """

    macro_estimator: UserTextMacroEstimator | None = None
    name: str = "user_text_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        claimed = [c for c in context.food_candidates if _has_stated_calorie_total(c)]
        if not claimed:
            context.record_step(self.name, "skipped")
            return

        # Claim the stated-calorie candidates so the USDA/OFF food step only resolves
        # the rest; ``user_text`` outranks those sources for the stated field(s).
        context.food_candidates = [
            c for c in context.food_candidates if not _has_stated_calorie_total(c)
        ]

        for candidate in claimed:
            context.resolved_food_items.append(self._resolve(context, candidate))

        context.record_step(self.name, "ok")

    def _resolve(self, context: EstimationContext, candidate: CandidateDraft) -> ResolvedFoodItem:
        """Validate + resolve one user-stated candidate, or fail closed to clarify."""

        reason = _validate_stated_facts(candidate)
        if reason is not None:
            context.clarification_questions = [
                ClarificationDraft(text=CONTRADICTORY_FACTS_QUESTION)
            ]
            raise NeedsClarification(reason)

        _record_source_ref(context, USER_TEXT_SOURCE)
        # ``_validate_stated_facts`` has guaranteed a positive, finite calorie total.
        # The stated facts are a per-unit anchor; a count/fraction quantity modifier
        # ("half", "2×") scales them (FTY-419). Validation ran on the per-unit values
        # (the Atwater ratio is scale-invariant); persistence uses the scaled total.
        stated_calories = cast(float, candidate.stated_calories)
        multiplier = _anchor_quantity(candidate)
        calories = cast(float, _scaled(stated_calories, multiplier))

        stated = {
            "protein_g": _scaled(candidate.stated_protein_g, multiplier),
            "carbs_g": _scaled(candidate.stated_carbs_g, multiplier),
            "fat_g": _scaled(candidate.stated_fat_g, multiplier),
        }
        missing = tuple(name for name, value in stated.items() if value is None)

        estimated = _EstimatedMacros(values={}, source_ref=None, assumptions=())
        if missing and self.macro_estimator is not None:
            estimated = self.macro_estimator.estimate(context, candidate, calories, missing)

        macros: dict[str, float | None] = {}
        provenance: dict[str, str] = {"calories": PROVENANCE_USER_STATED}
        for name in _MACRO_NAMES:
            if stated[name] is not None:
                macros[name] = stated[name]
                provenance[name] = PROVENANCE_USER_STATED
            elif name in estimated.values:
                macros[name] = estimated.values[name]
                provenance[name] = PROVENANCE_ESTIMATED
            else:
                macros[name] = None
                provenance[name] = PROVENANCE_UNKNOWN

        assumptions = tuple(estimated.assumptions)
        if multiplier != 1.0:
            # Honest, content-free provenance for the scaled anchor (numbers only —
            # never raw diary text): the per-unit calories, the count, and the total.
            assumptions = (
                f"calorie_anchor: {stated_calories:g} kcal/unit × {multiplier:g} "
                f"= {calories:g} kcal",
                *assumptions,
            )
        for assumption in assumptions:
            if assumption not in context.assumptions:
                context.assumptions.append(assumption)

        content_hash = _user_text_content_hash(
            calories, macros["protein_g"], macros["carbs_g"], macros["fat_g"]
        )
        return ResolvedFoodItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            grams=None,
            calories=calories,
            protein_g=macros["protein_g"],
            carbs_g=macros["carbs_g"],
            fat_g=macros["fat_g"],
            product_id=None,
            source_type=USER_TEXT_SOURCE_TYPE,
            source_ref=f"{USER_TEXT_SOURCE}:{content_hash}",
            content_hash=content_hash,
            fetched_at=datetime.now(UTC),
            calories_per_100g=calories,
            protein_per_100g=macros["protein_g"],
            carbs_per_100g=macros["carbs_g"],
            fat_per_100g=macros["fat_g"],
            assumptions=assumptions,
            basis=AS_LOGGED_BASIS,
            field_provenance=provenance,
        )
