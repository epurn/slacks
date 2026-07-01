"""Tests for the FTY-157 parse calibration fixture and harness."""

from __future__ import annotations

import json
import re

from tests.parse_calibration.harness import (
    BASELINE_SUMMARY_PATH,
    DEFAULT_OPERATING_THRESHOLD,
    FIXTURE_PATH,
    LabeledParseExample,
    SignalResult,
    evaluate_recorded_baseline,
    evaluate_signal,
    load_examples,
    verbalized_confidence_baseline,
)

EXPECTED_TOTAL_EXAMPLES = 300
REGRESSION_FLOORS = {
    "correct_decision_rate": 0.84,
    "answered_accuracy": 0.88,
    "under_ask_rate": 0.25,
    "over_ask_rate": 0.13,
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
