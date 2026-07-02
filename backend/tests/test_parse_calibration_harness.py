"""Tests for the FTY-157 parse calibration fixture and harness.

FTY-158 adds the recorded self-consistency signals: the fixture-integrity
checks for the recorded samples, the committed hybrid summary pin, the
improvement bar over the verbalized baseline, the early-stop cost guard, and
the fail-closed unanimous-clarify decision mapping.
"""

from __future__ import annotations

import json
import re

import pytest

from app.estimator.self_consistency import (
    SELF_CONSISTENCY_FIRST_WINDOW,
    SELF_CONSISTENCY_NUM_SAMPLES,
    apply_early_stop,
)
from app.schemas.parse import ParseDisposition
from tests.parse_calibration.harness import (
    BASELINE_SUMMARY_PATH,
    DEFAULT_OPERATING_THRESHOLD,
    FIXTURE_PATH,
    RECORDED_SAMPLE_COUNT,
    SELF_CONSISTENCY_SUMMARY_PATH,
    LabeledParseExample,
    SignalResult,
    evaluate_recorded,
    evaluate_recorded_baseline,
    evaluate_signal,
    load_examples,
    recorded_agreement_signal,
    recorded_hybrid_signal,
    verbalized_confidence_baseline,
)

EXPECTED_TOTAL_EXAMPLES = 300
REGRESSION_FLOORS = {
    "correct_decision_rate": 0.84,
    "answered_accuracy": 0.88,
    "under_ask_rate": 0.25,
    "over_ask_rate": 0.13,
}
# FTY-158 improvement bar: the consistency signals must not regress below these
# at the 0.45 operating point (the committed values are 0.937 / 0.947 — see
# self_consistency_summary.json; floors leave headroom for fixture growth).
CONSISTENCY_FLOORS = {
    "agreement_correct_decision_rate": 0.92,
    "hybrid_correct_decision_rate": 0.93,
}


def test_metric_math_on_hand_checked_fixture() -> None:
    examples = [
        _example("clear-a", "unambiguous", "estimate"),
        _example("clear-b", "inferable", "estimate"),
        _example("ask-a", "indeterminate", "needs_clarification"),
        _example("ask-b", "indeterminate", "needs_clarification"),
    ]
    scores = {
        "clear-a": 0.9,
        "clear-b": 0.2,
        "ask-a": 0.8,
        "ask-b": 0.1,
    }

    summary = evaluate_signal(
        examples,
        lambda example: SignalResult(score=scores[example.id]),
        signal_name="hand_checked",
        fixture_name="inline",
        operating_threshold=0.5,
        risk_thresholds=(0.0, 0.5, 1.0),
    )

    operating = summary.operating
    assert operating.total == 4
    assert operating.answered == 2
    assert operating.asked == 2
    assert operating.correct_estimates == 1
    assert operating.coverage == 0.5
    assert operating.answered_accuracy == 0.5
    assert operating.over_ask == 1
    assert operating.over_ask_rate == 0.5
    assert operating.under_ask == 1
    assert operating.under_ask_rate == 0.5
    assert operating.correct_decision_rate == 0.5


def test_recorded_baseline_keeps_nonparsed_rows_asked_at_zero_threshold() -> None:
    examples = [
        _example(
            "ask-a",
            "indeterminate",
            "needs_clarification",
            baseline_disposition="needs_clarification",
            baseline_confidence=1.0,
        )
    ]

    summary = evaluate_signal(
        examples,
        verbalized_confidence_baseline,
        signal_name="baseline_edge_case",
        fixture_name="inline",
        operating_threshold=0.0,
        risk_thresholds=(0.0,),
    )

    assert summary.operating.answered == 0
    assert summary.operating.asked == 1
    assert summary.operating.under_ask == 0
    assert summary.operating.correct_decision_rate == 1.0


def test_committed_fixture_validates_and_is_stratified_synthetic_only() -> None:
    examples = load_examples(FIXTURE_PATH)

    assert len(examples) == EXPECTED_TOTAL_EXAMPLES
    assert _counts_by_difficulty(examples) == {
        "unambiguous": 100,
        "inferable": 100,
        "indeterminate": 100,
    }
    assert all(example.source_kind == "synthetic_by_construction" for example in examples)
    assert all(example.gold_parse for example in examples)
    assert {
        example.gold_decision for example in examples if example.difficulty == "indeterminate"
    } == {"needs_clarification"}
    assert {
        example.gold_decision
        for example in examples
        if example.difficulty in {"unambiguous", "inferable"}
    } == {"estimate"}
    assert not any(_looks_like_pii(example.input) for example in examples)


def test_recorded_baseline_summary_matches_harness_output() -> None:
    summary = evaluate_recorded_baseline(FIXTURE_PATH)
    recorded = json.loads(BASELINE_SUMMARY_PATH.read_text(encoding="utf-8"))

    assert recorded == summary.to_dict()
    assert summary.operating.threshold == DEFAULT_OPERATING_THRESHOLD
    assert summary.operating.correct_decision_rate >= REGRESSION_FLOORS["correct_decision_rate"]
    assert summary.operating.answered_accuracy is not None
    assert summary.operating.answered_accuracy >= REGRESSION_FLOORS["answered_accuracy"]
    assert summary.operating.under_ask_rate <= REGRESSION_FLOORS["under_ask_rate"]
    assert summary.operating.over_ask_rate <= REGRESSION_FLOORS["over_ask_rate"]


def test_committed_fixture_carries_recorded_consistency_samples() -> None:
    examples = load_examples(FIXTURE_PATH)

    assert RECORDED_SAMPLE_COUNT == SELF_CONSISTENCY_NUM_SAMPLES
    assert all(len(example.samples) == RECORDED_SAMPLE_COUNT for example in examples)


def test_consistency_signals_beat_the_verbalized_baseline() -> None:
    """The FTY-158 acceptance bar, measured on the labeled set.

    Both consistency signals must beat the recorded verbalized-vs-0.45 baseline
    at the shared operating point on every decision metric, and the hybrid must
    be at least as good as agreement-only (the research's expected ordering).
    """

    baseline = evaluate_recorded_baseline(FIXTURE_PATH).operating
    agreement = evaluate_recorded("agreement", FIXTURE_PATH).operating
    hybrid = evaluate_recorded("hybrid", FIXTURE_PATH).operating

    for signal in (agreement, hybrid):
        assert signal.correct_decision_rate > baseline.correct_decision_rate
        assert signal.over_ask_rate < baseline.over_ask_rate
        assert signal.under_ask_rate < baseline.under_ask_rate

    assert hybrid.correct_decision_rate >= agreement.correct_decision_rate
    assert (
        agreement.correct_decision_rate >= (CONSISTENCY_FLOORS["agreement_correct_decision_rate"])
    )
    assert hybrid.correct_decision_rate >= CONSISTENCY_FLOORS["hybrid_correct_decision_rate"]


def test_committed_self_consistency_summary_matches_harness_output() -> None:
    summary = evaluate_recorded("hybrid", FIXTURE_PATH)
    recorded = json.loads(SELF_CONSISTENCY_SUMMARY_PATH.read_text(encoding="utf-8"))

    assert recorded == summary.to_dict()
    assert summary.operating.threshold == DEFAULT_OPERATING_THRESHOLD


def test_easy_examples_early_stop_at_the_first_window() -> None:
    """The cost guard: unanimous inputs must not pay the full N samples."""

    examples = load_examples(FIXTURE_PATH)
    stopped_early = [
        example
        for example in examples
        if len(apply_early_stop(example.samples)) == SELF_CONSISTENCY_FIRST_WINDOW
    ]

    # Every explicit-quantity input samples unanimously and stops early…
    unambiguous = [e for e in examples if e.difficulty == "unambiguous"]
    assert all(
        len(apply_early_stop(e.samples)) == SELF_CONSISTENCY_FIRST_WINDOW for e in unambiguous
    )
    # …and easy inputs dominate the set, so most of it never pays the full N.
    assert len(stopped_early) / len(examples) >= 0.6


def test_unanimous_clarify_examples_fail_closed_to_a_decision() -> None:
    """A sample set that never parses maps to a direct clarify decision.

    Its agreement is a perfect 1.0 (unanimously asking), so a score would read
    as estimate-confidence — the decision mapping is the fail-closed guard.
    """

    examples = load_examples(FIXTURE_PATH)
    unanimous_clarify = [
        example
        for example in examples
        if example.samples
        and all(s.disposition is not ParseDisposition.PARSED for s in example.samples)
    ]

    assert unanimous_clarify, "fixture must exercise the unanimous-clarify path"
    for example in unanimous_clarify:
        assert recorded_hybrid_signal(example).decision == "needs_clarification"
        assert recorded_agreement_signal(example).decision == "needs_clarification"


def test_recorded_consistency_signal_requires_samples() -> None:
    example = _example("no-samples", "inferable", "estimate")

    with pytest.raises(ValueError, match="no recorded self-consistency samples"):
        recorded_hybrid_signal(example)


def test_harness_outputs_machine_and_human_readable_metrics() -> None:
    summary = evaluate_recorded_baseline(FIXTURE_PATH)
    machine = summary.to_dict()
    human = summary.human_table()

    assert machine["operating"]["over_ask_rate"] == round(summary.operating.over_ask_rate, 6)
    assert machine["operating"]["under_ask_rate"] == round(summary.operating.under_ask_rate, 6)
    assert machine["risk_coverage_curve"]
    assert "Risk-coverage curve" in human
    assert "Operating point" in human


def _example(
    example_id: str,
    difficulty: str,
    gold_decision: str,
    *,
    baseline_disposition: str = "parsed",
    baseline_confidence: float = 0.9,
) -> LabeledParseExample:
    return LabeledParseExample.model_validate(
        {
            "id": example_id,
            "difficulty": difficulty,
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
            "baseline": {"disposition": baseline_disposition, "confidence": baseline_confidence},
        }
    )


def _counts_by_difficulty(examples: list[LabeledParseExample]) -> dict[str, int]:
    return {
        difficulty: sum(1 for example in examples if example.difficulty == difficulty)
        for difficulty in ("unambiguous", "inferable", "indeterminate")
    }


def _looks_like_pii(text: str) -> bool:
    patterns = [
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b",
        r"\b\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd)\b",
    ]
    return any(re.search(pattern, text) is not None for pattern in patterns)
