"""Regression gate for the FTY-159 data-calibrated clarify decision.

This suite is what makes the operating point *held*, not just derived once:

- the committed bake-off artifact (``calibration_summary.json``) must match a
  fresh derivation over the combined labeled sets, so any fixture, signal, or
  selection-rule change reprints the evidence;
- the production constant (``NL_PARSE_CLARIFY_POLICY``) must equal the derived
  winner's threshold, so the live gate can never drift from the data;
- the calibrated decision must keep beating the retired verbalized-vs-0.45
  baseline and must stay above absolute floors — a prompt or model change that
  degrades the operating point past them fails verification and requires
  recalibrating against the harness (ADR 0003, Consequences).

Everything here is deterministic and offline (recorded fixture signals only).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.estimator.clarify_policy import (
    BASIS_DATA_CALIBRATED,
    BASIS_DOCUMENTED_TUNABLE,
    LABEL_CLARIFY_POLICY,
    NL_PARSE_CLARIFY_POLICY,
)
from tests.parse_calibration.harness import (
    CALIBRATION_SUMMARY_PATH,
    TARGET_ANSWERED_PRECISION,
    LabeledParseExample,
    SignalResult,
    run_bake_off,
    select_operating_point,
)

#: Absolute floors for the calibrated NL operating point on the combined set.
#: The committed values are correct 0.951 / precision 0.990 / over-ask 0.065 /
#: under-ask 0.019 / coverage 0.631 (see ``calibration_summary.json``); the
#: floors leave headroom for labeled-set growth while still failing CI on a
#: real degradation.
CALIBRATED_FLOORS = {
    "correct_decision_rate": 0.93,
    "answered_accuracy": 0.98,
    "over_ask_rate": 0.10,
    "under_ask_rate": 0.05,
    "coverage": 0.55,
}

#: Per-band floor: the calibrated point must stay sound on each distribution
#: band individually, not just on the union (a synthetic-heavy average could
#: otherwise hide a collapse on the messy band).
PER_BAND_CORRECT_FLOOR = 0.85


@pytest.fixture(scope="module")
def bake_off() -> dict[str, Any]:
    return run_bake_off("combined")


def test_committed_calibration_summary_matches_bake_off(bake_off: dict[str, Any]) -> None:
    recorded = json.loads(CALIBRATION_SUMMARY_PATH.read_text(encoding="utf-8"))

    assert recorded == bake_off
    assert bake_off["target_answered_precision"] == TARGET_ANSWERED_PRECISION


def test_hybrid_wins_the_bake_off(bake_off: dict[str, Any]) -> None:
    """The winning-signal selection is measured, not assumed (story spec)."""

    winner = bake_off["winner"]
    selections = bake_off["selections"]

    assert winner["signal"] == "hybrid"
    # Agreement-only never reaches the precision target on the labeled sets.
    assert selections["agreement"] is None
    # The verbalized baseline reaches it only at far lower coverage.
    baseline = selections["baseline"]
    hybrid = selections["hybrid"]
    assert baseline is not None and hybrid is not None
    assert hybrid["operating"]["coverage"] > baseline["operating"]["coverage"]
    assert (
        hybrid["operating"]["correct_decision_rate"]
        > baseline["operating"]["correct_decision_rate"]
    )


def test_production_policy_matches_the_derived_operating_point(
    bake_off: dict[str, Any],
) -> None:
    """The live constant cannot drift from the data-derived point."""

    winner = bake_off["winner"]

    assert NL_PARSE_CLARIFY_POLICY.threshold == pytest.approx(winner["threshold"], abs=1e-9)
    assert winner["signal"] == "hybrid"
    assert NL_PARSE_CLARIFY_POLICY.signal == "hybrid_self_consistency"
    assert NL_PARSE_CLARIFY_POLICY.basis == BASIS_DATA_CALIBRATED


def test_label_policy_is_a_documented_tunable_in_the_shared_mechanism() -> None:
    # The label path shares the mechanism but honestly does not claim a
    # data-derived point: the calibration sets are NL descriptions, not label
    # scans (story spec, "Honesty caveat"). A label-image eval slice flips this
    # basis when it lands.
    assert LABEL_CLARIFY_POLICY.basis == BASIS_DOCUMENTED_TUNABLE
    assert LABEL_CLARIFY_POLICY.signal == "verbalized_confidence"
    assert LABEL_CLARIFY_POLICY.threshold == 0.5
    # Fail-closed comparison direction: below the point clarifies.
    assert LABEL_CLARIFY_POLICY.should_clarify(LABEL_CLARIFY_POLICY.threshold - 0.01)
    assert not LABEL_CLARIFY_POLICY.should_clarify(LABEL_CLARIFY_POLICY.threshold)


def test_calibrated_decision_beats_the_verbalized_baseline(bake_off: dict[str, Any]) -> None:
    """The FTY-159 acceptance bar: measured over-/under-ask improvement.

    The calibrated hybrid decision must beat the recorded verbalized-vs-0.45
    production gate it replaces on every decision metric, over the combined
    labeled sets.
    """

    baseline = bake_off["baseline_reference"]["operating"]
    calibrated = bake_off["winner"]["summary"]["operating"]

    assert calibrated["correct_decision_rate"] > baseline["correct_decision_rate"]
    assert calibrated["over_ask_rate"] < baseline["over_ask_rate"]
    assert calibrated["under_ask_rate"] < baseline["under_ask_rate"]
    assert calibrated["answered_accuracy"] > baseline["answered_accuracy"]


def test_calibrated_operating_point_holds_its_floors(bake_off: dict[str, Any]) -> None:
    """The regression gate: degrade past these and verification fails."""

    operating = bake_off["winner"]["summary"]["operating"]

    assert operating["correct_decision_rate"] >= CALIBRATED_FLOORS["correct_decision_rate"]
    assert operating["answered_accuracy"] >= CALIBRATED_FLOORS["answered_accuracy"]
    assert operating["over_ask_rate"] <= CALIBRATED_FLOORS["over_ask_rate"]
    assert operating["under_ask_rate"] <= CALIBRATED_FLOORS["under_ask_rate"]
    assert operating["coverage"] >= CALIBRATED_FLOORS["coverage"]


def test_calibrated_point_holds_on_each_band(bake_off: dict[str, Any]) -> None:
    per_band = bake_off["winner"]["per_band"]

    assert set(per_band) == {"synthetic", "naturalistic"}
    for metrics in per_band.values():
        assert metrics["correct_decision_rate"] >= PER_BAND_CORRECT_FLOOR


def test_select_operating_point_math_on_hand_checked_scores() -> None:
    # Gold asks score 0.2/0.4; gold estimates score 0.8/0.9. The only feasible
    # thresholds at precision 1.0 are 0.8 and 0.9; max coverage picks 0.8, and
    # the committed cutoff is the midpoint of the (0.4, 0.8] margin band.
    examples = [
        _example("ask-a", "needs_clarification"),
        _example("ask-b", "needs_clarification"),
        _example("est-a", "estimate"),
        _example("est-b", "estimate"),
    ]
    scores = {"ask-a": 0.2, "ask-b": 0.4, "est-a": 0.8, "est-b": 0.9}

    selection = select_operating_point(
        examples,
        lambda example: SignalResult(score=scores[example.id]),
        signal_name="hand_checked",
        target_precision=1.0,
    )

    assert selection is not None
    assert selection.feasible_score == 0.8
    assert selection.margin_low == 0.4
    assert selection.threshold == pytest.approx(0.6)
    assert selection.metrics.coverage == 0.5
    assert selection.metrics.answered_accuracy == 1.0
    assert selection.metrics.over_ask == 0
    assert selection.metrics.under_ask == 0


def test_select_operating_point_returns_none_when_infeasible() -> None:
    # A signal that ranks an ask above every estimate can never hit precision
    # 1.0 with anything answered: selection must refuse, not pick a bad point.
    examples = [
        _example("ask-a", "needs_clarification"),
        _example("est-a", "estimate"),
    ]
    scores = {"ask-a": 0.9, "est-a": 0.4}

    selection = select_operating_point(
        examples,
        lambda example: SignalResult(score=scores[example.id]),
        signal_name="hand_checked",
        target_precision=1.0,
    )

    assert selection is None


def _example(example_id: str, gold_decision: str) -> LabeledParseExample:
    return LabeledParseExample.model_validate(
        {
            "id": example_id,
            "difficulty": "inferable",
            "source_kind": "synthetic_by_construction",
            "source_template": "hand_checked",
            "input": f"{example_id} synthetic input",
            "gold_decision": gold_decision,
            "gold_parse": [
                {
                    "type": "food",
                    "name": "synthetic food",
                    "quantity_text": "1 serving",
                    "amount": 1,
                    "unit": "serving",
                }
            ],
            "baseline": {"disposition": "parsed", "confidence": 0.9},
        }
    )
