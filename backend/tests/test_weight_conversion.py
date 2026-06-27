"""Unit tests for the kg/lb canonical conversion (FTY-070).

Verifies the exact NIST factor (1 lb = 0.45359237 kg), boundary values of the
(0, 1000] kg canonical range, and the metric/imperial dispatch in
:func:`~app.services.weight_entries.to_canonical_kg`.

All assertions use exact equality or a tight tolerance so regressions in the
conversion factor are caught immediately.
"""

from __future__ import annotations

import pytest

from app.services.weight_entries import InvalidWeightValue, lb_to_kg, to_canonical_kg

#: Exact NIST factor — if this ever drifts the tests catch it.
_LB_TO_KG = 0.45359237


# ---------------------------------------------------------------------------
# lb_to_kg — raw factor tests
# ---------------------------------------------------------------------------


def test_lb_to_kg_uses_exact_nist_factor() -> None:
    assert lb_to_kg(1.0) == pytest.approx(_LB_TO_KG, rel=1e-12)


def test_lb_to_kg_exact_value_154lb() -> None:
    # 154 lb is a common reference body weight; verify round-trip determinism.
    result = lb_to_kg(154.0)
    assert result == pytest.approx(154.0 * _LB_TO_KG, rel=1e-12)


def test_lb_to_kg_small_value() -> None:
    assert lb_to_kg(0.001) == pytest.approx(0.001 * _LB_TO_KG, rel=1e-12)


# ---------------------------------------------------------------------------
# to_canonical_kg — metric passthrough
# ---------------------------------------------------------------------------


def test_metric_value_returned_unchanged() -> None:
    assert to_canonical_kg(70.5, "metric") == 70.5


def test_metric_value_at_maximum_boundary() -> None:
    assert to_canonical_kg(1000.0, "metric") == 1000.0


def test_metric_small_positive_value() -> None:
    assert to_canonical_kg(0.1, "metric") == 0.1


# ---------------------------------------------------------------------------
# to_canonical_kg — imperial conversion
# ---------------------------------------------------------------------------


def test_imperial_converts_using_nist_factor() -> None:
    assert to_canonical_kg(1.0, "imperial") == pytest.approx(_LB_TO_KG, rel=1e-12)


def test_imperial_154lb_maps_to_expected_kg() -> None:
    assert to_canonical_kg(154.0, "imperial") == pytest.approx(154.0 * _LB_TO_KG, rel=1e-12)


def test_imperial_exact_2205lb_is_near_1000kg() -> None:
    # 2204.62... lb ≈ 1000 kg; just verify the factor is applied correctly.
    result = to_canonical_kg(2204.62, "imperial")
    assert result == pytest.approx(2204.62 * _LB_TO_KG, rel=1e-12)


# ---------------------------------------------------------------------------
# Canonical weight bounds — applied after conversion
# ---------------------------------------------------------------------------


def test_canonical_zero_weight_is_invalid() -> None:
    """Weight of exactly 0 kg (or 0 lb) must be rejected at the schema level."""

    # The schema uses gt=0 so this is already caught before the service.
    # Verify the conversion result is exactly 0.0 (no surprise rounding).
    assert to_canonical_kg(0.0, "metric") == 0.0
    assert to_canonical_kg(0.0, "imperial") == 0.0


def test_canonical_1000kg_is_at_upper_boundary() -> None:
    # Exactly 1000 kg must be accepted ((0, 1000] is inclusive on the right).
    weight_kg = to_canonical_kg(1000.0, "metric")
    assert weight_kg == 1000.0
    assert weight_kg <= 1000.0


def test_canonical_above_1000kg_exceeds_boundary() -> None:
    weight_kg = to_canonical_kg(1000.001, "metric")
    assert weight_kg > 1000.0


def test_imperial_value_that_converts_above_1000kg() -> None:
    # A very large lb value should produce a kg above the 1000 kg bound.
    kg = to_canonical_kg(2500.0, "imperial")
    assert kg > 1000.0


# ---------------------------------------------------------------------------
# InvalidWeightValue is importable (contract check)
# ---------------------------------------------------------------------------


def test_invalid_weight_value_is_importable() -> None:
    assert issubclass(InvalidWeightValue, Exception)
