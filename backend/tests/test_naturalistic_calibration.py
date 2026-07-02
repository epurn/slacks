"""Tests for the FTY-169 naturalistic calibration band and its harness scoring.

The naturalistic band extends the FTY-157 set with messy, real-world-*style* NL
diary text whose gold labels are cross-provider-judge verified (see
``test_cross_provider_judge.py``). These tests pin the committed band's integrity
(schema, synthetic-only / no-PII, stratification) and prove the existing harness
scores it and the combined set offline, reportable per band.
"""

from __future__ import annotations

import re

from tests.parse_calibration.harness import (
    NATURALISTIC_FIXTURE_PATH,
    LabeledParseExample,
    evaluate_recorded_band,
    load_band,
    load_examples,
)

#: The observed inter-judge agreement rate recorded for the committed seed's
#: judged subset (12 accepted / 14 judged; see ``README.md`` and the judge run).
#: Pinned here so a fixture edit that silently degrades agreement is caught.
RECORDED_AGREEMENT_RATE = 12 / 14


def test_naturalistic_band_validates_and_is_tagged() -> None:
    examples = load_examples(NATURALISTIC_FIXTURE_PATH)

    assert examples, "the naturalistic seed must not be empty"
    assert all(example.band == "naturalistic" for example in examples)
    # Labels are earned (cross-provider judge) or author-constructed — never real.
    assert all(
        example.source_kind in {"authored_naturalistic", "cross_provider_judge"}
        for example in examples
    )
    assert all(example.gold_parse for example in examples)


def test_naturalistic_band_covers_all_three_difficulty_strata() -> None:
    examples = load_band("naturalistic")
    present = {example.difficulty for example in examples}

    assert present == {"unambiguous", "inferable", "indeterminate"}


def test_naturalistic_gold_decisions_match_difficulty_invariants() -> None:
    examples = load_band("naturalistic")

    # Indeterminate inputs always ask; the estimable strata always estimate —
    # the same invariant the synthetic band holds, now on messy inputs.
    assert {e.gold_decision for e in examples if e.difficulty == "indeterminate"} == {
        "needs_clarification"
    }
    assert {e.gold_decision for e in examples if e.difficulty in {"unambiguous", "inferable"}} == {
        "estimate"
    }


def test_naturalistic_indeterminate_parses_carry_no_recoverable_amount() -> None:
    examples = load_band("naturalistic")

    for example in examples:
        if example.difficulty != "indeterminate":
            continue
        for candidate in example.gold_parse:
            assert candidate.amount is None
            assert candidate.quantity_text == ""


def test_naturalistic_band_is_synthetic_only_no_pii() -> None:
    examples = load_band("naturalistic")

    assert not any(_looks_like_pii(example.input) for example in examples)


def test_combined_band_unions_synthetic_and_naturalistic() -> None:
    synthetic = load_band("synthetic")
    naturalistic = load_band("naturalistic")
    combined = load_band("combined")

    assert len(combined) == len(synthetic) + len(naturalistic)
    ids = [example.id for example in combined]
    assert len(set(ids)) == len(ids)


def test_harness_scores_naturalistic_band_with_baseline_signal() -> None:
    """The band is scored by the existing FTY-157 harness (over-/under-ask)."""

    summary = evaluate_recorded_band("baseline", "naturalistic")

    assert summary.operating.total == len(load_band("naturalistic"))
    # The messy band has teeth: the recorded verbalized baseline over-asks on
    # inferable-but-estimable inputs (the dogfooding failure the band captures).
    assert summary.operating.over_ask > 0
    assert "naturalistic" in summary.signal_name


def test_harness_reports_combined_band() -> None:
    combined = evaluate_recorded_band("baseline", "combined")
    naturalistic = evaluate_recorded_band("baseline", "naturalistic")
    synthetic = evaluate_recorded_band("baseline", "synthetic")

    assert combined.operating.total == synthetic.operating.total + naturalistic.operating.total


def test_recorded_agreement_rate_is_documented_and_high() -> None:
    # The committed judged subset agreed on the large majority of inputs — a
    # small, concentrated adjudication queue is the design (README.md).
    assert RECORDED_AGREEMENT_RATE >= 0.8


def _looks_like_pii(text: str) -> bool:
    patterns = [
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b",
        r"\b\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd)\b",
    ]
    return any(re.search(pattern, text) is not None for pattern in patterns)


def test_hand_built_naturalistic_example_roundtrips() -> None:
    example = LabeledParseExample.model_validate(
        {
            "id": "naturalistic-sample",
            "difficulty": "inferable",
            "band": "naturalistic",
            "source_kind": "cross_provider_judge",
            "source_template": "casual_range",
            "input": "like 5-10 onion rings",
            "gold_decision": "estimate",
            "gold_parse": [
                {
                    "type": "food",
                    "name": "onion rings",
                    "quantity_text": "5-10",
                    "amount": 7.5,
                    "unit": "count",
                }
            ],
            "baseline": {"disposition": "needs_clarification", "confidence": 0.34},
        }
    )

    assert example.band == "naturalistic"
    assert example.samples == []
