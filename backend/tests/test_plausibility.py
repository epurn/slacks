"""Unit tests for the deterministic parse-candidate plausibility validator (FTY-156).

Exercises :func:`app.estimator.plausibility.check_candidate` against:

- Implausible count, mass, and volume → reject with a targeted question.
- Unknown/garbage unit with a numeric amount → reject.
- Negative / non-finite amount → reject.
- **No false rejects**: a battery of legitimate, large-but-real portions and
  common household units → pass unchanged.
"""

from __future__ import annotations

import math

from app.enums import CandidateType
from app.estimator.plausibility import (
    MAX_PLAUSIBLE_COUNT,
    MAX_PLAUSIBLE_GRAMS,
    MAX_PLAUSIBLE_LARGE_ITEM_COUNT,
    MAX_PLAUSIBLE_ML,
    check_candidate,
)
from app.schemas.parse import ParsedCandidate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    name: str = "food",
    *,
    amount: float | None = None,
    unit: str | None = None,
    quantity_text: str = "",
) -> ParsedCandidate:
    return ParsedCandidate(
        type=CandidateType.FOOD,
        name=name,
        quantity_text=quantity_text,
        unit=unit,
        amount=amount,
    )


# ---------------------------------------------------------------------------
# Implausible count
# ---------------------------------------------------------------------------


def test_implausible_count_fails() -> None:
    # 50 eggs is the acceptance-criteria example — above the large-item count cap.
    result = check_candidate(_candidate("eggs", amount=50.0))
    assert not result.plausible
    assert result.reason == "implausible_count"
    assert result.clarification_question is not None
    assert "eggs" in result.clarification_question


def test_implausible_count_explicit_count_unit_fails() -> None:
    result = check_candidate(_candidate("eggs", amount=50.0, unit="piece"))
    assert not result.plausible
    assert result.reason == "implausible_count"


def test_count_at_max_boundary_passes() -> None:
    # MAX_PLAUSIBLE_COUNT itself must pass for generic/small countable foods.
    result = check_candidate(_candidate("grapes", amount=MAX_PLAUSIBLE_COUNT))
    assert result.plausible


def test_count_just_above_max_fails() -> None:
    result = check_candidate(_candidate("grapes", amount=MAX_PLAUSIBLE_COUNT + 1))
    assert not result.plausible
    assert result.reason == "implausible_count"


def test_large_item_count_at_override_boundary_passes() -> None:
    result = check_candidate(_candidate("eggs", amount=MAX_PLAUSIBLE_LARGE_ITEM_COUNT))
    assert result.plausible


def test_realistic_small_food_count_passes() -> None:
    # A counted bowl/bag of small items is realistic and must not hit the
    # narrower large-item cap that catches "50 eggs".
    result = check_candidate(_candidate("blueberries", amount=50.0))
    assert result.plausible


def test_realistic_small_food_specific_unit_count_passes() -> None:
    # Food-specific count units are common model output ("crackers" as the unit).
    result = check_candidate(_candidate("Kraft Toppables crackers", amount=50.0, unit="crackers"))
    assert result.plausible


# ---------------------------------------------------------------------------
# Implausible mass
# ---------------------------------------------------------------------------


def test_implausible_mass_grams_fails() -> None:
    # 5 000 g is the acceptance-criteria example.
    result = check_candidate(_candidate("chicken", amount=5000.0, unit="g"))
    assert not result.plausible
    assert result.reason == "implausible_mass"
    assert result.clarification_question is not None
    assert "chicken" in result.clarification_question


def test_implausible_mass_in_quantity_text_without_structured_amount_fails() -> None:
    # The model can carry the explicit measure only in quantity_text; the gate
    # must still apply the mass bound before the parse is trusted.
    result = check_candidate(_candidate("chicken", quantity_text="5000g"))
    assert not result.plausible
    assert result.reason == "implausible_mass"


def test_implausible_mass_in_quantity_text_with_comma_fails() -> None:
    result = check_candidate(_candidate("chicken", quantity_text="5,000 g"))
    assert not result.plausible
    assert result.reason == "implausible_mass"


def test_implausible_mass_in_quantity_text_with_structured_count_fails() -> None:
    # The raw portion phrase remains authoritative for measured quantity sanity:
    # a harmless structured serving/count must not hide an impossible mass.
    result = check_candidate(
        _candidate("chicken", quantity_text="5000g", amount=1.0, unit="serving")
    )
    assert not result.plausible
    assert result.reason == "implausible_mass"


def test_implausible_later_mass_in_quantity_text_fails() -> None:
    # Regression: the scanner must inspect every explicit measure, not stop at
    # the first plausible one.
    result = check_candidate(_candidate("meal", quantity_text="100g chicken and 5,000 g rice"))
    assert not result.plausible
    assert result.reason == "implausible_mass"


def test_implausible_mass_kg_fails() -> None:
    # 3 kg = 3 000 g, above 2 000 g limit.
    result = check_candidate(_candidate("steak", amount=3.0, unit="kg"))
    assert not result.plausible
    assert result.reason == "implausible_mass"


def test_mass_at_max_boundary_passes() -> None:
    # Exactly MAX_PLAUSIBLE_GRAMS grams must pass.
    result = check_candidate(_candidate("food", amount=MAX_PLAUSIBLE_GRAMS, unit="g"))
    assert result.plausible


def test_mass_just_above_max_fails() -> None:
    result = check_candidate(_candidate("food", amount=MAX_PLAUSIBLE_GRAMS + 1, unit="g"))
    assert not result.plausible
    assert result.reason == "implausible_mass"


def test_implausible_mass_pounds_fails() -> None:
    # 10 lb ≈ 4 536 g, above the limit.
    result = check_candidate(_candidate("chicken breast", amount=10.0, unit="lb"))
    assert not result.plausible
    assert result.reason == "implausible_mass"


# ---------------------------------------------------------------------------
# Implausible volume
# ---------------------------------------------------------------------------


def test_implausible_volume_litres_fails() -> None:
    # 3 L = 3 000 ml, above 2 000 ml limit.
    result = check_candidate(_candidate("juice", amount=3.0, unit="l"))
    assert not result.plausible
    assert result.reason == "implausible_volume"


def test_implausible_volume_in_quantity_text_without_structured_amount_fails() -> None:
    result = check_candidate(_candidate("soup", quantity_text="3 liters"))
    assert not result.plausible
    assert result.reason == "implausible_volume"


def test_implausible_volume_in_quantity_text_with_structured_count_fails() -> None:
    result = check_candidate(_candidate("soup", quantity_text="3 liters", amount=1.0, unit="bowl"))
    assert not result.plausible
    assert result.reason == "implausible_volume"


def test_implausible_volume_cups_fails() -> None:
    # 10 cups ≈ 2 366 ml, above 2 000 ml limit.
    result = check_candidate(_candidate("milk", amount=10.0, unit="cups"))
    assert not result.plausible
    assert result.reason == "implausible_volume"


def test_volume_at_max_boundary_passes() -> None:
    result = check_candidate(_candidate("water", amount=MAX_PLAUSIBLE_ML, unit="ml"))
    assert result.plausible


# ---------------------------------------------------------------------------
# Unknown / garbage unit
# ---------------------------------------------------------------------------


def test_unknown_unit_with_large_amount_fails() -> None:
    # A garbage unit with an amount above the count cap is unambiguously implausible
    # regardless of how we interpret the unit.
    result = check_candidate(_candidate("rice", amount=50.0, unit="zxcv"))
    assert not result.plausible
    assert result.reason == "unknown_unit"
    assert result.clarification_question is not None
    assert "rice" in result.clarification_question


def test_unknown_unit_large_amount_question_asks_about_unit() -> None:
    result = check_candidate(_candidate("pasta", amount=50.0, unit="fathoms"))
    assert not result.plausible
    assert result.clarification_question is not None
    assert "unit" in result.clarification_question.lower()


def test_unknown_unit_small_amount_passes() -> None:
    # A food-specific count unit (e.g. "crackers" used as a count unit) with a
    # plausible amount is treated generously and passes through.
    result = check_candidate(_candidate("crackers", amount=6.0, unit="crackers"))
    assert result.plausible


def test_unknown_unit_large_food_specific_count_uses_count_cap() -> None:
    result = check_candidate(
        _candidate("crackers", amount=MAX_PLAUSIBLE_COUNT + 1, unit="crackers")
    )
    assert not result.plausible
    assert result.reason == "implausible_count"


# ---------------------------------------------------------------------------
# Negative / non-finite amount
# ---------------------------------------------------------------------------


def test_negative_amount_fails() -> None:
    # Schema enforces ge=0, but the validator guards defensively.
    # We construct the candidate by-passing schema validation to test the guard.
    candidate = ParsedCandidate.model_construct(
        type="food",
        name="eggs",
        quantity_text="",
        unit=None,
        amount=-1.0,
    )
    result = check_candidate(candidate)
    assert not result.plausible
    assert result.reason == "non_finite_or_negative_amount"


def test_nan_amount_fails() -> None:
    candidate = ParsedCandidate.model_construct(
        type="food",
        name="eggs",
        quantity_text="",
        unit=None,
        amount=math.nan,
    )
    result = check_candidate(candidate)
    assert not result.plausible
    assert result.reason == "non_finite_or_negative_amount"


def test_inf_amount_fails() -> None:
    candidate = ParsedCandidate.model_construct(
        type="food",
        name="eggs",
        quantity_text="",
        unit=None,
        amount=math.inf,
    )
    result = check_candidate(candidate)
    assert not result.plausible
    assert result.reason == "non_finite_or_negative_amount"


# ---------------------------------------------------------------------------
# No false rejects — legitimate, large-but-real portions must pass
# ---------------------------------------------------------------------------


def test_no_amount_always_passes() -> None:
    # No amount: the gate has nothing to check; must not reject.
    result = check_candidate(_candidate("salad", amount=None, quantity_text="a bowl"))
    assert result.plausible


def test_zero_amount_passes() -> None:
    # Zero is the boundary; must pass (schema enforces ge=0).
    result = check_candidate(_candidate("water", amount=0.0, unit="ml"))
    assert result.plausible


def test_typical_egg_count_passes() -> None:
    result = check_candidate(_candidate("eggs", amount=2.0))
    assert result.plausible


def test_large_salad_grams_passes() -> None:
    # A large restaurant salad might be 500–600 g.
    result = check_candidate(_candidate("caesar salad", amount=600.0, unit="g"))
    assert result.plausible


def test_large_smoothie_ml_passes() -> None:
    # A large blended smoothie might be 600–800 ml.
    result = check_candidate(_candidate("banana smoothie", amount=750.0, unit="ml"))
    assert result.plausible


def test_realistic_quantity_text_measure_without_structured_amount_passes() -> None:
    result = check_candidate(_candidate("banana smoothie", quantity_text="750 ml"))
    assert result.plausible


def test_realistic_quantity_text_measure_with_structured_count_passes() -> None:
    result = check_candidate(
        _candidate("banana smoothie", quantity_text="750 ml", amount=1.0, unit="bottle")
    )
    assert result.plausible


def test_tbsp_passes() -> None:
    result = check_candidate(_candidate("peanut butter", amount=2.0, unit="tbsp"))
    assert result.plausible


def test_teaspoon_passes() -> None:
    result = check_candidate(_candidate("olive oil", amount=1.0, unit="tsp"))
    assert result.plausible


def test_cups_passes() -> None:
    result = check_candidate(_candidate("rice", amount=2.0, unit="cups"))
    assert result.plausible


def test_slices_passes() -> None:
    result = check_candidate(_candidate("bread", amount=3.0, unit="slices"))
    assert result.plausible


def test_realistic_large_meal_passes() -> None:
    # A large BBQ plate: 700 g of mixed food — well within the limit.
    result = check_candidate(_candidate("BBQ platter", amount=700.0, unit="g"))
    assert result.plausible


def test_ounces_realistic_passes() -> None:
    # 6 oz of steak ≈ 170 g — a typical portion, well within mass limit.
    result = check_candidate(_candidate("steak", amount=6.0, unit="oz"))
    assert result.plausible


def test_grams_at_limit_passes() -> None:
    # 2 kg converted = 2000 g, exactly the limit.
    result = check_candidate(_candidate("thanksgiving feast", amount=2.0, unit="kg"))
    assert result.plausible


def test_handful_passes() -> None:
    result = check_candidate(_candidate("almonds", amount=1.0, unit="handful"))
    assert result.plausible


def test_pinch_passes() -> None:
    result = check_candidate(_candidate("salt", amount=1.0, unit="pinch"))
    assert result.plausible


def test_scoop_passes() -> None:
    result = check_candidate(_candidate("protein powder", amount=2.0, unit="scoop"))
    assert result.plausible


def test_no_unit_with_plausible_count_passes() -> None:
    # No unit: treated as a count; 3 is realistic.
    result = check_candidate(_candidate("cookies", amount=3.0, unit=None))
    assert result.plausible


def test_exercise_candidate_passes() -> None:
    # Exercise candidates have no numeric amount typically; must not be falsely
    # rejected.
    candidate = ParsedCandidate(
        type=CandidateType.EXERCISE,
        name="run",
        quantity_text="30 minutes",
        unit=None,
        amount=None,
    )
    result = check_candidate(candidate)
    assert result.plausible
