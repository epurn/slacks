"""Unit tests for the deterministic comparable-reference aggregation (FTY-281).

Cover the two pure halves the LLM has no part in: :func:`compatibility` (food
form/category + ingredient/flavor overlap) and :func:`aggregate` (median over
compatible per-100g compositions, outlier rejection, minimum-source and
material-disagreement fall-through).
"""

from __future__ import annotations

import pytest

from app.estimator.comparable_reference import (
    MIN_COMPARABLE_SOURCES,
    ComparableCandidate,
    aggregate,
    compatibility,
)
from app.estimator.food_serving import NutritionFacts

_TARGET = "buffalo chicken lime wrap"


def _candidate(
    calories: float, protein: float, carbs: float, fat: float, *, ref: str = "reference_source:u"
) -> ComparableCandidate:
    return ComparableCandidate(
        facts=NutritionFacts(calories=calories, protein_g=protein, carbs_g=carbs, fat_g=fat),
        source_ref=ref,
        shared_terms=("buffalo", "chicken"),
        form="wrap",
    )


# --- compatibility ----------------------------------------------------------------


def test_compatible_wrap_shares_form_and_ingredients() -> None:
    match = compatibility(_TARGET, "Buffalo Chicken Wrap")
    assert match is not None
    assert "buffalo" in match.shared_terms
    assert "chicken" in match.shared_terms
    assert match.form == "wrap"


def test_wrong_food_form_is_incompatible() -> None:
    # A salad is a different physical form than a wrap: rejected even though it shares
    # "buffalo"/"chicken".
    assert compatibility(_TARGET, "Buffalo Chicken Salad") is None


def test_form_only_overlap_is_incompatible() -> None:
    # Shares only the form word "wrap", no ingredient/flavor overlap → not a comparable.
    assert compatibility(_TARGET, "Veggie Hummus Wrap") is None


def test_missing_or_blank_page_name_is_incompatible() -> None:
    assert compatibility(_TARGET, None) is None
    assert compatibility(_TARGET, "   ") is None


def test_page_without_a_named_form_is_allowed_on_ingredient_overlap() -> None:
    # A bare nutrition table naming only the ingredients (no form word) is compatible.
    match = compatibility(_TARGET, "Buffalo Chicken")
    assert match is not None
    assert set(match.shared_terms) == {"buffalo", "chicken"}


# --- aggregate --------------------------------------------------------------------


def test_too_few_sources_produce_no_aggregate() -> None:
    candidates = [_candidate(100, 5, 12, 3)] * (MIN_COMPARABLE_SOURCES - 1)
    assert aggregate(candidates) is None


def test_median_aggregate_over_compatible_sources() -> None:
    # Three references with identical macro *densities* (grams per kcal) at different
    # portion sizes → the median density is exact.
    candidates = [
        _candidate(100, 5.0, 12.0, 3.0),
        _candidate(200, 10.0, 24.0, 6.0),
        _candidate(150, 7.5, 18.0, 4.5),
    ]
    result = aggregate(candidates)
    assert result is not None
    assert result.dropped_outliers == 0
    assert result.densities["protein_g"] == pytest.approx(0.05)
    assert result.densities["carbs_g"] == pytest.approx(0.12)
    assert result.densities["fat_g"] == pytest.approx(0.03)
    assert len(result.source_refs) == 3


def test_outlier_is_dropped_before_aggregation() -> None:
    # Three consistent references plus one wildly protein-skewed outlier: the outlier is
    # dropped and the aggregate reflects only the consistent three.
    candidates = [
        _candidate(100, 5.0, 12.0, 3.0, ref="reference_source:a"),
        _candidate(200, 10.0, 24.0, 6.0, ref="reference_source:b"),
        _candidate(150, 7.5, 18.0, 4.5, ref="reference_source:c"),
        _candidate(100, 30.0, 5.0, 1.0, ref="reference_source:outlier"),
    ]
    result = aggregate(candidates)
    assert result is not None
    assert result.dropped_outliers == 1
    assert "reference_source:outlier" not in result.source_refs
    assert result.densities["protein_g"] == pytest.approx(0.05)
    assert result.densities["carbs_g"] == pytest.approx(0.12)


def test_materially_disagreeing_sources_produce_no_aggregate() -> None:
    # A bimodal sample (two high-protein, two high-fat) has no consistent centre: after
    # outlier filtering nothing survives that agrees, so no aggregate is produced.
    candidates = [
        _candidate(100, 20.0, 5.0, 0.5),
        _candidate(100, 20.0, 5.0, 0.5),
        _candidate(100, 2.0, 5.0, 10.0),
        _candidate(100, 2.0, 5.0, 10.0),
    ]
    assert aggregate(candidates) is None
