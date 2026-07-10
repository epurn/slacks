"""Estimate-first parse recovery routing (FTY-300)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.estimator.clarify_policy import NL_PARSE_CLARIFY_POLICY
from app.estimator.parse import ParseStep
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.pipeline import EstimationContext, NeedsClarification, StepFailed
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider


def _context(raw_text: str = "some crackers") -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=raw_text)


def _parsed(items: list[dict[str, object]], confidence: float = 0.9) -> dict[str, object]:
    return {"disposition": "parsed", "confidence": confidence, "items": items}


def _clarify(text: str, options: list[str] | None = None) -> dict[str, object]:
    return {"text": text, "options": options or ["1 serving", "2 servings", "3 servings"]}


def _sampled(
    reply: dict[str, Any] | LLMError, count: int = SELF_CONSISTENCY_FIRST_WINDOW
) -> list[dict[str, Any] | LLMError]:
    return [reply for _ in range(count)]


def _run(
    provider: FakeProvider,
    context: EstimationContext,
    *,
    policy: ParsePolicySettings | None = None,
) -> None:
    step = ParseStep(provider) if policy is None else ParseStep(provider, policy=policy)
    step.run(context)


def _low() -> float:
    low = 0.2
    assert 0.6 + 0.4 * low < NL_PARSE_CLARIFY_POLICY.threshold
    return low


def _question_texts(context: EstimationContext) -> list[str]:
    return [question.text for question in context.clarification_questions]


def test_provider_clarification_with_identity_routes_to_candidates() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.3,
                "items": [
                    {"type": "food", "name": "crackers", "quantity_text": ""},
                    {"type": "food", "name": "peanut butter", "quantity_text": ""},
                ],
                "clarification_questions": [
                    _clarify("How many crackers did you have?", ["4", "8", "12"]),
                    _clarify("How much peanut butter?", ["1 tsp", "1 tbsp", "2 tbsp"]),
                ],
            }
        )
    )
    context = _context(raw_text="crackers and peanut butter")

    _run(provider, context)

    assert [candidate.name for candidate in context.food_candidates] == [
        "crackers",
        "peanut butter",
    ]
    assert all(candidate.amount is None for candidate in context.food_candidates)
    assert context.clarification_questions == []


def test_no_recognizable_identity_still_routes_to_clarification() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.3,
                "items": [{"type": "food", "name": "food", "quantity_text": ""}],
                "clarification_questions": [
                    _clarify("What food did you have?", ["Rice", "Eggs", "Yogurt"])
                ],
            }
        )
    )
    context = _context(raw_text="some stuff")

    with pytest.raises(NeedsClarification):
        _run(provider, context)

    assert _question_texts(context) == ["What food did you have?"]
    assert context.food_candidates == []


def test_calibrated_confident_generic_parsed_item_routes_to_clarification() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                **_parsed(
                    [{"type": "food", "name": "food", "quantity_text": "some"}],
                    confidence=0.95,
                ),
                "clarification_questions": [
                    _clarify("What food did you have?", ["Rice", "Eggs", "Yogurt"])
                ],
            }
        )
    )
    context = _context(raw_text="some stuff")

    with pytest.raises(NeedsClarification) as exc:
        _run(provider, context)

    assert exc.value.reason == "missing_identity"
    assert _question_texts(context) == ["What food did you have?"]
    assert context.food_candidates == []


def test_calibrated_confident_generic_parsed_item_without_question_fails_closed() -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [{"type": "food", "name": "food", "quantity_text": "some"}],
                confidence=0.95,
            )
        )
    )
    context = _context(raw_text="some stuff")

    with pytest.raises(StepFailed) as exc:
        _run(provider, context)

    assert exc.value.reason == "clarification_quality_failed"
    assert context.food_candidates == []


@pytest.mark.parametrize(
    "raw_text",
    [
        "6 crackers with about 1.5-2 tbsp dill pickle hummus",
        "six crackers and roughly 2 tbsp dill pickle hummus",
    ],
)
def test_counted_crackers_and_hummus_estimates_even_when_provider_asks(
    raw_text: str,
) -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.34,
                "items": [
                    {
                        "type": "food",
                        "name": "crackers",
                        "quantity_text": "6",
                        "amount": 6,
                        "unit": "crackers",
                    },
                    {
                        "type": "food",
                        "name": "dill pickle hummus",
                        "quantity_text": "about 1.5-2 tbsp",
                        "amount": 1.75,
                        "unit": "tbsp",
                    },
                ],
                "clarification_questions": [
                    _clarify("How much crackers did you have?", ["4", "6", "8"])
                ],
            }
        )
    )
    context = _context(raw_text=raw_text)

    _run(provider, context)

    assert [candidate.name for candidate in context.food_candidates] == [
        "crackers",
        "dill pickle hummus",
    ]
    assert context.food_candidates[0].amount == 6
    assert context.food_candidates[1].amount == 1.75
    assert context.clarification_questions == []


@pytest.mark.parametrize(
    "raw_text",
    [
        "3 toppables PB sandwiches (kraft)",
        "three Kraft Toppables peanut butter sandwiches",
    ],
)
def test_toppables_pb_sandwiches_estimate_even_when_provider_asks(raw_text: str) -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.36,
                "items": [
                    {
                        "type": "food",
                        "name": "Kraft Toppables crackers",
                        "quantity_text": "3 cracker sandwiches",
                        "brand": "Kraft",
                        "amount": 18,
                        "unit": "crackers",
                    },
                    {
                        "type": "food",
                        "name": "peanut butter",
                        "quantity_text": "~3 tbsp",
                        "amount": 3,
                        "unit": "tbsp",
                    },
                ],
                "clarification_questions": [
                    _clarify("How many cracker sandwiches?", ["1", "2", "3"])
                ],
            }
        )
    )
    context = _context(raw_text=raw_text)

    _run(provider, context)

    assert {candidate.name for candidate in context.food_candidates} == {
        "Kraft Toppables crackers",
        "peanut butter",
    }
    assert context.clarification_questions == []


def test_low_hybrid_with_identity_routes_to_candidates() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                **_parsed(
                    [{"type": "food", "name": "crackers", "quantity_text": "some"}],
                    confidence=_low(),
                ),
                "clarification_questions": [
                    _clarify("How many crackers did you have?", ["4", "8", "12"])
                ],
            }
        )
    )
    context = _context(raw_text="some crackers")

    _run(provider, context)

    assert [candidate.name for candidate in context.food_candidates] == ["crackers"]
    assert context.food_candidates[0].amount is None
    assert context.clarification_questions == []


def test_low_hybrid_uses_non_representative_recognizable_candidates() -> None:
    # The identity disagreement across samples triggers one FTY-325
    # re-interpretation call (the fourth scripted reply). When that re-read
    # still yields no recognizable identity, the estimate-first policy falls
    # back to the recognizable non-representative sample, as before FTY-325.
    generic = _parsed([{"type": "food", "name": "food", "quantity_text": "some"}], confidence=0.95)
    provider = FakeProvider(
        responses=[
            generic,
            _parsed(
                [{"type": "food", "name": "crackers", "quantity_text": "some"}],
                confidence=_low(),
            ),
            _parsed(
                [{"type": "food", "name": "crackers", "quantity_text": "some"}],
                confidence=_low(),
            ),
            generic,
        ]
    )
    context = _context(raw_text="some crackers")

    _run(provider, context)

    assert [candidate.name for candidate in context.food_candidates] == ["crackers"]
    assert context.clarification_questions == []


def test_mixed_detail_and_amountless_items_routes_to_candidates() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                **_parsed(
                    [
                        {"type": "food", "name": "eggs", "quantity_text": "2", "amount": 2},
                        {"type": "food", "name": "toast", "quantity_text": "some"},
                    ],
                    confidence=_low(),
                ),
                "clarification_questions": [
                    _clarify("How much toast did you have?", ["1 slice", "2 slices", "3 slices"])
                ],
            }
        )
    )
    context = _context(raw_text="2 eggs and some toast")

    _run(provider, context)

    assert [candidate.name for candidate in context.food_candidates] == ["eggs", "toast"]
    assert context.food_candidates[0].amount == 2
    assert context.food_candidates[1].amount is None
    assert context.clarification_questions == []


def test_balanced_mode_keeps_threshold_for_amountless_identity() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                **_parsed(
                    [{"type": "food", "name": "crackers", "quantity_text": "some"}],
                    confidence=_low(),
                ),
                "clarification_questions": [
                    _clarify("How many crackers did you have?", ["4", "8", "12"])
                ],
            }
        )
    )
    context = _context(raw_text="some crackers")

    with pytest.raises(NeedsClarification):
        _run(provider, context, policy=ParsePolicySettings(mode="balanced"))

    assert context.food_candidates == []
    assert _question_texts(context) == ["How many crackers did you have?"]


def test_balanced_mode_targets_missing_detail_when_provider_reasks_stated_item() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                **_parsed(
                    [
                        {
                            "type": "food",
                            "name": "crackers",
                            "quantity_text": "6",
                            "amount": 6,
                            "unit": "crackers",
                        },
                        {"type": "food", "name": "hummus", "quantity_text": ""},
                    ],
                    confidence=_low(),
                ),
                "clarification_questions": [
                    _clarify("How many crackers did you have?", ["4", "6", "8"])
                ],
            }
        )
    )
    context = _context(raw_text="6 crackers and hummus")

    with pytest.raises(NeedsClarification) as exc:
        _run(provider, context, policy=ParsePolicySettings(mode="balanced"))

    assert exc.value.reason == "low_confidence_or_ambiguous"
    assert context.food_candidates == []
    assert _question_texts(context) == ["How much hummus did you have?"]
    assert context.clarification_questions[0].options == ["1 tsp", "1 tbsp", "2 tbsp"]


def test_balanced_mode_does_not_reask_for_a_stated_detail() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                **_parsed(
                    [{"type": "food", "name": "crackers", "quantity_text": "6", "amount": 6}],
                    confidence=_low(),
                ),
                "clarification_questions": [
                    _clarify("How many crackers did you have?", ["4", "8", "12"])
                ],
            }
        )
    )
    context = _context(raw_text="6 crackers")

    _run(provider, context, policy=ParsePolicySettings(mode="balanced"))

    assert [candidate.name for candidate in context.food_candidates] == ["crackers"]
    assert context.clarification_questions == []


def test_strict_mode_can_keep_old_style_abstention_for_stated_detail() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                **_parsed(
                    [{"type": "food", "name": "crackers", "quantity_text": "6", "amount": 6}],
                    confidence=_low(),
                ),
                "clarification_questions": [
                    _clarify("How many crackers did you have?", ["4", "8", "12"])
                ],
            }
        )
    )
    context = _context(raw_text="6 crackers")

    with pytest.raises(NeedsClarification):
        _run(provider, context, policy=ParsePolicySettings(mode="strict"))

    assert context.food_candidates == []


def test_recoverable_provider_shape_mistakes_are_normalized() -> None:
    payload = {
        "result": {
            "disposition": "Parsed",
            "confidence": "0.82",
            "items": [
                {
                    "type": "Food",
                    "name": "crackers",
                    "quantity_text": "6",
                    "amount": "6",
                    "unit": "crackers",
                }
            ],
            "clarification_questions": None,
        }
    }
    provider = FakeProvider(responses=_sampled(payload))
    context = _context(raw_text="6 crackers")

    _run(provider, context)

    assert [candidate.name for candidate in context.food_candidates] == ["crackers"]
    assert context.food_candidates[0].amount == 6.0
    assert context.clarification_questions == []


def test_recovery_is_bounded_by_the_parse_policy_cap() -> None:
    payload = {
        "result": {
            "disposition": "Parsed",
            "confidence": 0.82,
            "items": [{"type": "Food", "name": "crackers", "quantity_text": "6"}],
        }
    }
    provider = FakeProvider(responses=_sampled(payload))
    context = _context(raw_text="6 crackers")

    with pytest.raises(StepFailed) as exc:
        _run(provider, context, policy=ParsePolicySettings(max_repair_attempts=1))

    assert exc.value.reason == "schema_validation_failed"
    assert context.food_candidates == []


def test_unrecoverable_provider_shape_still_fails_closed() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "ask_later",
                "confidence": 0.9,
                "items": [{"type": "food", "name": "crackers"}],
            }
        )
    )
    context = _context(raw_text="crackers")

    with pytest.raises(StepFailed) as exc:
        _run(provider, context)

    assert exc.value.reason == "schema_validation_failed"
    assert context.food_candidates == []


def test_schema_recovery_failure_does_not_echo_provider_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_output = "provider echoed private snack text"
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "parsed",
                "confidence": 0.9,
                "items": [{"type": "food", "name": "crackers", "raw_output": sensitive_output}],
            }
        )
    )
    context = _context(raw_text="crackers")

    with caplog.at_level("DEBUG"), pytest.raises(StepFailed) as exc:
        _run(provider, context)

    assert str(exc.value) == "schema_validation_failed"
    assert sensitive_output not in str(exc.value)
    assert sensitive_output not in caplog.text
