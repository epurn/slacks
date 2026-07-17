"""Deterministic resolved-value plausibility gate for composed dishes (FTY-368).

The parse-stage validator (:mod:`app.estimator.plausibility`, FTY-156) bounds the
parsed **quantity/unit** before resolution; the per-100g bound
(:func:`app.estimator.food_serving.nutrition_facts_plausible`, FTY-115) bounds the
**source facts**. Neither sees the **final resolved total**, so a plausible
per-100g row scaled by a wrong portion could still commit an absurd number — the
2026-07-16 live incident resolved a whole ``tuna salad sandwich`` to 65 kcal by
applying a bare 30 g bread-slice common portion as the dish's grams.

This module closes that gap for **composed/assembled dishes** (sandwich, burger,
wrap, taco, …): after serving math produces a final total, a dish-class item whose
resolved calories fall outside a generous dish-class band — or whose resolved
grams fall below a **stated component amount** ("about 1/2 a can of tuna" bounds
the sandwich from below) — is not committed as-is. The caller routes it back to
re-estimation (the official/reference/model-prior tiers per the active policy)
and records the content-free :func:`refit_assumption` label so the refit stays
visible on the final item's provenance. The gate never produces a terminal
failure: a trip only re-routes within the existing estimate-first fallback chain.

All bounds are **generous, documented tunables** in the
:mod:`app.estimator.plausibility` philosophy — set just outside any realistic
value so a false reject of a large-but-real dish is effectively impossible, and
the fail-safe failure mode is *loose* (an over-generous bound lets a rare absurd
value through once; a tight bound would churn real meals through re-estimation).

Pure functions, no I/O, no LLM, bounded vocabulary — untrusted candidate text is
only tokenized against closed tables and never echoed into any label.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final

from app.estimator.food_serving import _COUNT_UNITS, _MASS_UNIT_GRAMS, _VOLUME_UNIT_GRAMS

# ---------------------------------------------------------------------------
# Tunables — documented constants block (per FTY-042/FTY-156 precedent).
# Each bound has a rationale + cited basis so maintainers can judge whether a
# value should move.
# ---------------------------------------------------------------------------

#: Minimum plausible calories for ONE counted composed dish. USDA FoodData
#: Central survey (FNDDS) prepared-dish rows put the lightest real composed
#: dishes well above this — a plain small corn-tortilla street taco ≈ 150 kcal,
#: a single sandwich ≈ 200-400 kcal (two regular bread slices alone ≈ 160 kcal),
#: a plain hamburger ≈ 250-300 kcal. 100 kcal sits safely below all of them
#: (fail loose) while catching the 65-kcal-sandwich incident class.
DISH_CLASS_MIN_KCAL_PER_COUNT: Final[float] = 100.0

#: Maximum plausible calories for ONE counted composed dish. The largest real
#: single restaurant dishes (fully loaded burritos, triple burgers) top out
#: around 2 000-2 500 kcal per USDA FDC branded/survey rows; 3 000 leaves
#: generous room above that, while a kJ-scale or portion-math blunder
#: (the 4 000-kcal single item class) is still caught.
DISH_CLASS_MAX_KCAL_PER_COUNT: Final[float] = 3000.0

#: A resolved dish is rejected only when its grams fall below this fraction of
#: the stated component's grams. A dish weighs at least its stated component
#: plus everything else, so requiring only 90% of the component alone is a
#: deliberately loose bound that absorbs rounding and conversion slack.
STATED_COMPONENT_SLACK: Final[float] = 0.9

#: Lower-bound grams for one retail can/tin stated as a component ("1/2 a can
#: of tuna"). 85 g is the smallest common US retail can (3 oz), deliberately
#: below the standard 5 oz / 142 g tuna can and far below vegetable/soup cans,
#: so the component floor under-claims rather than over-claims.
_CONTAINER_MIN_GRAMS: Final[dict[str, float]] = {"can": 85.0, "tin": 85.0}

#: Content-free trace/evidence outcome recorded when the gate rejects a
#: resolved total, shared by the food and official/reference steps.
IMPLAUSIBLE_RESOLVED_TOTAL_OUTCOME: Final[str] = "rejected_implausible_resolved_total"

#: Prefix for the content-free assumption label a refit item carries.
REFIT_ASSUMPTION_PREFIX: Final[str] = "resolved_plausibility_refit"

#: Closed vocabulary of composed/assembled-dish nouns: a dish whose total is the
#: sum of parts, so no single incidental component's common portion can stand in
#: for the whole. A bounded, documented tunable — not a food taxonomy.
_COMPOSED_DISH_WORDS: Final[frozenset[str]] = frozenset(
    {
        "blt",
        "burger",
        "burrito",
        "calzone",
        "cheeseburger",
        "gyro",
        "hamburger",
        "hoagie",
        "hotdog",
        "melt",
        "panini",
        "pizza",
        "quesadilla",
        "sandwich",
        "sub",
        "taco",
        "wrap",
    }
)

#: Snack-form nouns that opt a name OUT of the dish class: a "cracker sandwich"
#: or "sandwich cookie" is a small counted snack (FTY-167/FTY-292 class), not a
#: composed meal, and must keep its existing resolution untouched.
_SNACK_FORM_WORDS: Final[frozenset[str]] = frozenset({"biscuit", "cookie", "cracker", "wafer"})

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]+")

# Match a stated "<number>[/<denominator>] [of|a|an] <unit>" component measure in
# the bounded parse quantity phrase ("about 1/2 a can of tuna", "2 tbsp mayo").
_STATED_MEASURE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9A-Za-z.])(\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?))?\s*(?:(?:of|an?)\s+)*([A-Za-z_]+)"
)


@dataclass(frozen=True)
class ResolvedTotalCheck:
    """Outcome of one resolved-total plausibility check.

    ``plausible`` is ``True`` when the total passes (including every non-dish
    item — the gate is a no-op outside the dish class). When ``False``,
    ``reason`` is a short fixed label (never raw user text) naming which bound
    tripped, suitable for traces and the :func:`refit_assumption` label.
    """

    plausible: bool
    reason: str | None = None


def refit_assumption(reason: str) -> str:
    """The content-free assumption label a gate-tripped refit item carries."""

    return f"{REFIT_ASSUMPTION_PREFIX}:{reason}"


def _vocab_match(token: str, vocabulary: frozenset[str]) -> bool:
    """Whether ``token`` (or its naive singular) is in the closed ``vocabulary``."""

    if token in vocabulary:
        return True
    if token.endswith("es") and token[:-2] in vocabulary:
        return True
    return token.endswith("s") and token[:-1] in vocabulary


def is_composed_dish(name: str, unit: str | None = None) -> bool:
    """Whether the candidate names a composed/assembled dish (sandwich, wrap, …).

    Matched on the closed dish vocabulary across the name and unit tokens, with
    the snack-form exclusion applied first: ``3 cracker sandwiches`` is a counted
    snack, not a dish. Deliberately loose in both directions — the consumers
    (the common-portion guard and the resolved-total gate) are themselves
    fail-loose, so a miss here only preserves existing behaviour.
    """

    tokens = [*_TOKEN_RE.findall(name.lower()), *_TOKEN_RE.findall((unit or "").lower())]
    if any(_vocab_match(token, _SNACK_FORM_WORDS) for token in tokens):
        return False
    return any(_vocab_match(token, _COMPOSED_DISH_WORDS) for token in tokens)


def stated_component_floor_grams(quantity_text: str | None) -> float | None:
    """The largest stated component measure in ``quantity_text``, in grams.

    Reads explicit "<number> <mass|volume|container unit>" component amounts
    (fractions included: ``1/2 a can``) through the same mass/volume tables the
    serving math uses plus the documented container minimums. Each stated
    component is individually a lower bound on the dish; the largest is the
    binding one. Returns ``None`` when nothing convertible is stated.
    """

    best: float | None = None
    for match in _STATED_MEASURE_RE.finditer(quantity_text or ""):
        value = float(match.group(1))
        denominator = match.group(2)
        if denominator is not None:
            denominator_value = float(denominator)
            if denominator_value <= 0:
                continue
            value /= denominator_value
        if not math.isfinite(value) or value <= 0:
            continue
        unit = match.group(3).lower()
        grams_per_unit = (
            _MASS_UNIT_GRAMS.get(unit) or _VOLUME_UNIT_GRAMS.get(unit) or _container_grams(unit)
        )
        if grams_per_unit is None:
            continue
        grams = value * grams_per_unit
        if best is None or grams > best:
            best = grams
    return best


def _container_grams(unit: str) -> float | None:
    """Lower-bound grams for a stated container unit (``can``/``cans``/``tin``)."""

    for word, grams in _CONTAINER_MIN_GRAMS.items():
        if _vocab_match(unit, frozenset({word})):
            return grams
    return None


def _dish_count(unit: str | None, amount: float | None) -> float:
    """The counted dish multiplier the class band scales by (1.0 when unknown)."""

    if amount is None or not math.isfinite(amount) or amount <= 0:
        return 1.0
    normalized = re.sub(r"\s+", " ", (unit or "").strip().lower())
    if normalized in _COUNT_UNITS:
        return amount
    tokens = _TOKEN_RE.findall(normalized)
    if tokens and all(_vocab_match(token, _COMPOSED_DISH_WORDS) for token in tokens):
        return amount
    return 1.0


def check_resolved_food_total(
    *,
    name: str,
    unit: str | None,
    amount: float | None,
    quantity_text: str,
    grams: float | None,
    calories: float,
) -> ResolvedTotalCheck:
    """Return whether a resolved item's final total is plausible for its dish class.

    Runs **after** serving math produced the final total. Rules (generous,
    documented tunables — see the module constants):

    1. **Non-dish item → no-op.** The band is defensible only for the closed
       composed-dish class; everything else keeps its existing gates.
    2. **Dish total below the class band → fail.** Scaled by the counted dish
       amount, so ``half a sandwich`` halves the floor.
    3. **Dish total above the class band → fail.** Catches the 4 000-kcal
       single-item class without rejecting a large-but-real meal.
    4. **Dish grams below a stated component alone → fail.** A composed dish is
       the sum of its parts, so a stated component amount ("1/2 a can of tuna")
       bounds the whole dish from below (with :data:`STATED_COMPONENT_SLACK`).
    """

    if not is_composed_dish(name, unit):
        return ResolvedTotalCheck(plausible=True)
    if not math.isfinite(calories):
        return ResolvedTotalCheck(plausible=False, reason="non_finite_total")
    count = _dish_count(unit, amount)
    if calories < DISH_CLASS_MIN_KCAL_PER_COUNT * count:
        return ResolvedTotalCheck(plausible=False, reason="dish_total_below_class_band")
    if calories > DISH_CLASS_MAX_KCAL_PER_COUNT * max(1.0, count):
        return ResolvedTotalCheck(plausible=False, reason="dish_total_above_class_band")
    floor = stated_component_floor_grams(quantity_text)
    if (
        floor is not None
        and grams is not None
        and math.isfinite(grams)
        and grams < STATED_COMPONENT_SLACK * floor
    ):
        return ResolvedTotalCheck(plausible=False, reason="dish_total_below_stated_component")
    return ResolvedTotalCheck(plausible=True)
