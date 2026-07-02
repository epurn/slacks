"""Clarification quality routing for the structured parse step (FTY-172)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.estimator.parse import DEFAULT_CLARIFICATION_QUESTION, ParseStep
from app.estimator.pipeline import EstimationContext, NeedsClarification, StepFailed
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider


def _context(raw_text: str = "some rice") -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=raw_text)


def _parsed(items: list[dict[str, object]], confidence: float = 0.9) -> dict[str, object]:
    return {"disposition": "parsed", "confidence": confidence, "items": items}


def _clarify(text: str, options: list[str] | None = None) -> dict[str, object]:
    return {"text": text, "options": options or ["1 serving", "2 servings", "3 servings"]}


def _sampled(
    reply: dict[str, Any] | LLMError, count: int = SELF_CONSISTENCY_FIRST_WINDOW
) -> list[dict[str, Any] | LLMError]:
    return [reply for _ in range(count)]


def _run(provider: FakeProvider, context: EstimationContext) -> None:
    ParseStep(provider).run(context)


def _question_texts(context: EstimationContext) -> list[str]:
    return [question.text for question in context.clarification_questions]


def _question_options(context: EstimationContext) -> list[list[str]]:
    return [question.options for question in context.clarification_questions]


def test_needs_clarification_disposition_collects_questions() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.8,
                "clarification_questions": [
                    _clarify("How much rice?", ["1/2 cup", "1 cup", "2 cups"]),
                    _clarify("Cooked or raw?", ["Cooked", "Raw"]),
                    _clarify("How much rice?", ["1/2 cup", "1 cup", "2 cups"]),
                ],
            }
        )
    )
    context = _context()

    with pytest.raises(NeedsClarification):
        _run(provider, context)

    assert _question_texts(context) == ["How much rice?", "Cooked or raw?"]
    assert _question_options(context) == [["1/2 cup", "1 cup", "2 cups"], ["Cooked", "Raw"]]


def test_needs_clarification_without_questions_fails_closed() -> None:
    provider = FakeProvider(
        responses=_sampled({"disposition": "needs_clarification", "confidence": 0.8})
    )
    context = _context()

    with pytest.raises(StepFailed) as exc:
        _run(provider, context)

    assert exc.value.reason == "clarification_quality_failed"
    assert context.clarification_questions == []


def test_generic_clarification_question_fails_closed() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.8,
                "clarification_questions": [
                    _clarify(DEFAULT_CLARIFICATION_QUESTION, ["1 serving", "2 servings"]),
                ],
            }
        )
    )

    with pytest.raises(StepFailed) as exc:
        _run(provider, _context())

    assert exc.value.reason == "clarification_quality_failed"


def test_generic_amount_clarification_without_item_fails_closed() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.8,
                "clarification_questions": [
                    _clarify("What amount did you have?", ["1 serving", "2 servings"]),
                ],
            }
        )
    )

    with pytest.raises(StepFailed) as exc:
        _run(provider, _context())

    assert exc.value.reason == "clarification_quality_failed"


def test_clarification_question_without_two_options_fails_closed() -> None:
    provider = FakeProvider(
        responses=_sampled(
            {
                "disposition": "needs_clarification",
                "confidence": 0.8,
                "clarification_questions": [_clarify("How much rice?", ["1 cup"])],
            }
        )
    )

    with pytest.raises(StepFailed) as exc:
        _run(provider, _context())

    assert exc.value.reason == "clarification_quality_failed"


def test_low_confidence_parsed_synthesizes_backend_clarification() -> None:
    reply = _parsed([{"type": "food", "name": "rice", "quantity_text": "some"}], confidence=0.1)
    provider = FakeProvider(responses=_sampled(reply))
    context = _context(raw_text="some rice")

    with pytest.raises(NeedsClarification) as exc:
        _run(provider, context)

    assert exc.value.reason == "low_confidence_or_ambiguous"
    assert context.food_candidates == []
    assert _question_texts(context) == ["How much rice did you have?"]
    assert _question_options(context) == [["1/2 cup", "1 cup", "2 cups"]]
