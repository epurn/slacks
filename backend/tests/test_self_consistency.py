"""Tests for the FTY-158 self-consistency confidence signal.

Covers the agreement metric's hand-checked math, the hybrid combiner's
fail-closed weighting, the parallel sampler's early-stop call counts (via the
fake provider — no live model), true window parallelism, and the failed-provider
/ schema-invalid paths propagating unchanged (fail closed).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import BaseModel

from app.estimator.clarify_policy import NL_PARSE_CLARIFY_POLICY
from app.estimator.parse_prompt import build_parse_prompt
from app.estimator.self_consistency import (
    HYBRID_AGREEMENT_WEIGHT,
    SelfConsistencySignal,
    agreement_score,
    apply_early_stop,
    collect_parse_samples,
    evaluate_self_consistency,
    hybrid_score,
    pair_concordance,
)
from app.llm.base import ImageInput, OutputT, Provider
from app.llm.errors import LLMResponseError, StructuredOutputValidationError
from app.llm.providers.fake import FakeProvider
from app.schemas.parse import ParseResult


def _item(
    name: str,
    *,
    amount: float | None = None,
    unit: str | None = None,
    kind: str = "food",
) -> dict[str, Any]:
    return {"type": kind, "name": name, "quantity_text": "", "amount": amount, "unit": unit}


def _payload(
    *,
    disposition: str = "parsed",
    confidence: float = 0.9,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "confidence": confidence,
        "items": items if items is not None else [_item("eggs", amount=2.0, unit="count")],
    }


def _result(**kwargs: Any) -> ParseResult:
    return ParseResult.model_validate(_payload(**kwargs))


# ---------------------------------------------------------------------------
# Pair concordance — the metric's hand-checked math.
# ---------------------------------------------------------------------------


def test_identical_parses_have_full_concordance() -> None:
    a = _result(items=[_item("eggs", amount=2.0, unit="count")])
    b = _result(items=[_item("Eggs", amount=2.0, unit="count")], confidence=0.4)

    # Name matching is case-insensitive and the verbalized score plays no part.
    assert pair_concordance(a, b) == 1.0


def test_disposition_mismatch_is_total_disagreement() -> None:
    a = _result(disposition="parsed")
    b = _result(disposition="needs_clarification")

    assert pair_concordance(a, b) == 0.0


def test_both_unparseable_agree() -> None:
    a = _result(disposition="unparseable", items=[])
    b = _result(disposition="unparseable", items=[])

    assert pair_concordance(a, b) == 1.0


def test_unmatched_items_dilute_matched_fraction() -> None:
    a = _result(items=[_item("eggs", amount=2.0), _item("toast", amount=1.0)])
    b = _result(items=[_item("eggs", amount=2.0)])

    # 1 match / max(2, 1) items, matched quantities agree fully.
    assert pair_concordance(a, b) == 0.5


def test_amount_disagreement_scores_min_over_max() -> None:
    a = _result(items=[_item("crackers", amount=2.0, unit="serving")])
    b = _result(items=[_item("crackers", amount=4.0, unit="serving")])

    assert pair_concordance(a, b) == 0.5


def test_unit_mismatch_zeroes_quantity_agreement() -> None:
    a = _result(items=[_item("yogurt", amount=170.0, unit="g")])
    b = _result(items=[_item("yogurt", amount=170.0, unit="ml")])

    assert pair_concordance(a, b) == 0.0


def test_missing_unit_is_not_a_contradiction() -> None:
    a = _result(items=[_item("banana", amount=1.0, unit=None)])
    b = _result(items=[_item("banana", amount=1.0, unit="count")])

    assert pair_concordance(a, b) == 1.0


def test_one_missing_amount_is_disagreement() -> None:
    a = _result(items=[_item("chips", amount=1.0)])
    b = _result(items=[_item("chips", amount=None)])

    assert pair_concordance(a, b) == 0.0


def test_both_missing_amounts_agree() -> None:
    a = _result(disposition="needs_clarification", items=[_item("chips")])
    b = _result(disposition="needs_clarification", items=[_item("chips")])

    assert pair_concordance(a, b) == 1.0


def test_duplicate_names_match_as_a_multiset() -> None:
    a = _result(items=[_item("egg", amount=1.0), _item("egg", amount=1.0)])
    b = _result(items=[_item("egg", amount=1.0)])

    # Only one of the two duplicate items can pair off.
    assert pair_concordance(a, b) == 0.5


def test_empty_item_lists() -> None:
    both_empty_a = _result(disposition="needs_clarification", items=[])
    both_empty_b = _result(disposition="needs_clarification", items=[])
    one_empty = _result(disposition="needs_clarification", items=[_item("chips")])

    assert pair_concordance(both_empty_a, both_empty_b) == 1.0
    assert pair_concordance(both_empty_a, one_empty) == 0.0


# ---------------------------------------------------------------------------
# Stated nutrition (FTY-279/FTY-280): the metric must compare the user-stated
# facts, so unstable/contradictory calorie extraction is not read as unanimous.
# ---------------------------------------------------------------------------


def _stated(name: str, **stated: float) -> dict[str, Any]:
    return {"type": "food", "name": name, "quantity_text": "1", **stated}


def test_matching_stated_calories_stay_fully_concordant() -> None:
    # Same item, same stated total → the stated-nutrition factor is 1.0 and the pair
    # is still unanimous (the ordinary user-text happy path is unaffected).
    a = _result(items=[_stated("wrap", stated_calories=580.0)])
    b = _result(items=[_stated("wrap", stated_calories=580.0)], confidence=0.4)

    assert pair_concordance(a, b) == 1.0


def test_contradictory_stated_calories_are_not_unanimous() -> None:
    # A conflicting stated total drops concordance below 1.0 (min/max ratio), so the
    # extraction can never be treated as unanimous and early-stop cannot fire on it.
    a = _result(items=[_stated("wrap", stated_calories=580.0)])
    b = _result(items=[_stated("wrap", stated_calories=900.0)])

    assert pair_concordance(a, b) == pytest.approx(580.0 / 900.0)


def test_one_sample_omitting_a_stated_calorie_total_is_disagreement() -> None:
    # One sample extracts a stated total, the other extracts none for the same item:
    # the samples disagree on whether the user even stated it → full disagreement on
    # that field, so the pair is not unanimous.
    a = _result(items=[_stated("wrap", stated_calories=580.0)])
    b = _result(items=[{"type": "food", "name": "wrap", "quantity_text": "1"}])

    assert pair_concordance(a, b) == 0.0


def test_both_omitting_stated_nutrition_is_unaffected() -> None:
    # No stated facts in play on either side → the stated-nutrition factor is 1.0 and
    # the metric matches the pre-FTY-280 amount-only behaviour exactly.
    a = _result(items=[_item("eggs", amount=2.0, unit="count")])
    b = _result(items=[_item("eggs", amount=2.0, unit="count")])

    assert pair_concordance(a, b) == 1.0


def test_stated_macro_disagreement_lowers_concordance() -> None:
    # Calories agree but a co-stated macro conflicts: only fields in play are scored
    # (calories 1.0, protein 20/40), so concordance is their mean, not diluted by the
    # untouched carbs/fat fields.
    a = _result(items=[_stated("wrap", stated_calories=580.0, stated_protein_g=20.0)])
    b = _result(items=[_stated("wrap", stated_calories=580.0, stated_protein_g=40.0)])

    assert pair_concordance(a, b) == pytest.approx((1.0 + 0.5) / 2)


# ---------------------------------------------------------------------------
# Agreement over N samples and the hybrid combiner.
# ---------------------------------------------------------------------------


def test_agreement_is_mean_over_all_pairs() -> None:
    unanimous = _result(items=[_item("rice", amount=2.0, unit="serving")])
    contested = _result(items=[_item("rice", amount=4.0, unit="serving")])

    # Pairs: (u, u) = 1.0, (u, c) = 0.5, (u, c) = 0.5 → 2/3.
    score = agreement_score([unanimous, unanimous, contested])
    assert score == pytest.approx(2 / 3)


def test_single_sample_agreement_is_degenerate_one() -> None:
    assert agreement_score([_result()]) == 1.0


def test_hybrid_weighting_fails_closed_on_total_disagreement() -> None:
    # The documented rationale for HYBRID_AGREEMENT_WEIGHT: a fully disagreeing
    # sample set must score below the parse gate's calibrated operating
    # threshold even when the model verbalizes total confidence. If the weight
    # changes, this property must be re-justified against the harness.
    assert hybrid_score(0.0, 1.0) == pytest.approx(1.0 - HYBRID_AGREEMENT_WEIGHT)
    assert hybrid_score(0.0, 1.0) < NL_PARSE_CLARIFY_POLICY.threshold


def test_hybrid_unanimity_rescues_a_timid_verbalized_score() -> None:
    # The over-ask fix: unanimous sampling lifts a low self-reported confidence
    # over the calibrated operating threshold.
    assert hybrid_score(1.0, 0.38) > NL_PARSE_CLARIFY_POLICY.threshold


def test_signal_fields_hand_checked() -> None:
    parsed_a = _result(items=[_item("rice", amount=2.0, unit="serving")], confidence=0.8)
    parsed_b = _result(items=[_item("rice", amount=4.0, unit="serving")], confidence=0.6)
    clarify = _result(disposition="needs_clarification", items=[_item("rice")], confidence=0.5)

    signal = SelfConsistencySignal.from_samples([parsed_a, clarify, parsed_b])

    # Pairs: (a, clarify) = 0, (clarify, b) = 0, (a, b) = 0.5 → 1/6.
    assert signal.agreement == pytest.approx(1 / 6)
    # Verbalized mean is over *parsed* samples only.
    assert signal.verbalized_confidence == pytest.approx(0.7)
    assert signal.hybrid == pytest.approx(
        HYBRID_AGREEMENT_WEIGHT * (1 / 6) + (1 - HYBRID_AGREEMENT_WEIGHT) * 0.7
    )
    assert signal.samples_used == 3
    assert not signal.unanimous
    assert not signal.all_non_parsed


def test_unanimous_clarify_is_a_direct_fail_closed_decision() -> None:
    clarify = _result(disposition="needs_clarification", items=[_item("chips")], confidence=0.9)

    signal = SelfConsistencySignal.from_samples([clarify, clarify])

    # Agreement is a perfect 1.0 *about asking*; the flag is what prevents that
    # from ever being read as estimate-confidence.
    assert signal.agreement == 1.0
    assert signal.all_non_parsed
    assert signal.verbalized_confidence == 0.0


def test_apply_early_stop_mirrors_the_live_stop_rule() -> None:
    unanimous = _result(items=[_item("rice", amount=2.0, unit="serving")])
    contested = _result(items=[_item("rice", amount=4.0, unit="serving")])

    assert len(apply_early_stop([unanimous, unanimous, contested])) == 2
    assert len(apply_early_stop([unanimous, contested, unanimous])) == 3
    assert len(apply_early_stop([unanimous, unanimous])) == 2


# ---------------------------------------------------------------------------
# The parallel sampler (fake provider — no live model, no network).
# ---------------------------------------------------------------------------


def test_unanimous_first_window_early_stops_at_two_calls() -> None:
    payload = _payload()
    fake = FakeProvider(responses=[payload, payload, payload])

    samples = collect_parse_samples(fake, "2 eggs", num_samples=3, first_window=2)

    assert len(samples) == 2
    assert fake.prompts == [build_parse_prompt("2 eggs")] * 2


def test_contested_first_window_pays_the_full_n() -> None:
    agree = _payload(items=[_item("rice", amount=2.0, unit="serving")])
    differ = _payload(items=[_item("rice", amount=4.0, unit="serving")])
    fake = FakeProvider(responses=[agree, differ, agree])

    samples = collect_parse_samples(fake, "rice", num_samples=3, first_window=2)

    assert len(samples) == 3
    assert len(fake.prompts) == 3


def test_single_sample_configuration_makes_one_call() -> None:
    fake = FakeProvider(responses=[_payload()])

    samples = collect_parse_samples(fake, "2 eggs", num_samples=1, first_window=2)

    assert len(samples) == 1
    assert len(fake.prompts) == 1


def test_window_of_one_cannot_attest_unanimity() -> None:
    payload = _payload()
    fake = FakeProvider(responses=[payload, payload, payload])

    samples = collect_parse_samples(fake, "2 eggs", num_samples=3, first_window=1)

    # A single sample can never attest agreement, so the full N is drawn.
    assert len(samples) == 3


def test_invalid_sampling_bounds_are_rejected() -> None:
    fake = FakeProvider(responses=[])

    with pytest.raises(ValueError):
        collect_parse_samples(fake, "2 eggs", num_samples=0)
    with pytest.raises(ValueError):
        collect_parse_samples(fake, "2 eggs", first_window=0)


class _PublicOnlyProvider(Provider):
    """Provider double that fails if callers bypass ``structured_completion``."""

    name = "public-only-fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(timeout_seconds=1.0, max_retries=0)
        self._payload = payload
        self.prompts: list[str] = []

    def structured_completion(
        self,
        prompt: str,
        schema: type[OutputT],
        *,
        images: Sequence[ImageInput] | None = None,
    ) -> OutputT:
        assert images is None
        self.prompts.append(prompt)
        return schema.model_validate(self._payload)

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        raise AssertionError("parse sampling must use structured_completion")


def test_sampler_uses_public_structured_completion_contract() -> None:
    provider = _PublicOnlyProvider(_payload())

    samples = collect_parse_samples(provider, "2 eggs", num_samples=1)

    assert len(samples) == 1
    assert samples[0].items[0].name == "eggs"
    assert provider.prompts == [build_parse_prompt("2 eggs")]


class _BarrierProvider(Provider):
    """Blocks each call until two are in flight — proves window parallelism."""

    name = "barrier-fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(timeout_seconds=1.0, max_retries=0)
        self._payload = payload
        self._barrier = threading.Barrier(parties=2)

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        # If the sampler ran the window sequentially, the first call would wait
        # here forever (no second party) and the barrier would break the test.
        self._barrier.wait(timeout=10.0)
        return self._payload


def test_first_window_samples_run_in_parallel() -> None:
    provider = _BarrierProvider(_payload())

    signal = evaluate_self_consistency(provider, "2 eggs", num_samples=3, first_window=2)

    assert signal.samples_used == 2
    assert signal.unanimous


def test_sample_failure_propagates_fail_closed() -> None:
    fake = FakeProvider(responses=[_payload(), LLMResponseError("provider replied 4xx")])

    with pytest.raises(LLMResponseError):
        collect_parse_samples(fake, "2 eggs", num_samples=3, first_window=2)


def test_schema_invalid_sample_is_rejected_not_scored() -> None:
    # Untrusted-analyst boundary: a sample that fails ParseResult validation is
    # rejected by the provider layer and never reaches the agreement metric.
    fake = FakeProvider(responses=[_payload(), {"nonsense": True}])

    with pytest.raises(StructuredOutputValidationError):
        collect_parse_samples(fake, "2 eggs", num_samples=3, first_window=2)
