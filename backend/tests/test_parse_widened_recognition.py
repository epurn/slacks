"""Widened food-recognition parse routing tests (FTY-371).

The never-fail directive widens the recognition bar: informal, unbranded, homemade,
compositional, or borderline-consumable descriptions (gum, supplements, homemade
assemblies) are recognized as loggable food/consumable candidates and route to an
estimate, while terminal ``unparseable_input`` fires **only** when the parse samples
unanimously judge the input genuinely not food/exercise/consumable at all.

These drive :class:`~app.estimator.parse.ParseStep` with the network-free
:class:`FakeProvider` (scripting one reply per self-consistency sample), pinning the
routing side of the widened bar. The prompt guidance a live model consumes is asserted
separately here; its live effect is FTY-373's band-based smoke.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.estimator.parse import ParseStep
from app.estimator.parse_prompt import build_parse_prompt
from app.estimator.pipeline import EstimationContext, StepFailed
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider


def _context(raw_text: str) -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=raw_text)


def _sampled(reply: dict[str, Any]) -> list[dict[str, Any] | LLMError]:
    return [reply for _ in range(SELF_CONSISTENCY_FIRST_WINDOW)]


def _parsed(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"disposition": "parsed", "confidence": 0.9, "items": items}


def _unparseable() -> dict[str, Any]:
    return {"disposition": "unparseable", "confidence": 0.0, "reason": "not a log"}


@pytest.mark.parametrize(
    ("raw_text", "item"),
    [
        (
            "nicorette 4mg gum",
            {"type": "food", "name": "nicorette gum", "quantity_text": "1 piece"},
        ),
        (
            "banh mi on a brioche bun with shredded carrot, sriracha mayo, cucumber",
            {"type": "food", "name": "banh mi", "quantity_text": "1 sandwich", "amount": 1},
        ),
        ("one multivitamin", {"type": "food", "name": "multivitamin", "quantity_text": "1"}),
    ],
)
def test_borderline_consumable_routes_to_an_estimate(raw_text: str, item: dict[str, Any]) -> None:
    provider = FakeProvider(responses=_sampled(_parsed([item])))
    context = _context(raw_text)

    ParseStep(provider).run(context)

    # Recognized as a loggable food/consumable candidate — never unparseable.
    assert [candidate.name for candidate in context.food_candidates] == [item["name"]]
    assert context.clarification_questions == []


@pytest.mark.parametrize("raw_text", ["asdf", "how's the weather"])
def test_genuine_non_food_still_fails_closed_unparseable(raw_text: str) -> None:
    provider = FakeProvider(responses=_sampled(_unparseable()))
    context = _context(raw_text)

    with pytest.raises(StepFailed) as exc:
        ParseStep(provider).run(context)

    assert exc.value.reason == "unparseable_input"


def test_prompt_frames_borderline_consumables_as_recognizable() -> None:
    prompt = build_parse_prompt("nicorette 4mg gum")

    # The widened guidance names logged consumables and reserves unparseable for
    # genuine non-food, so a live model recognizes gum/supplements as food.
    assert "gum" in prompt
    assert "supplement" in prompt
    assert '"unparseable"' in prompt
