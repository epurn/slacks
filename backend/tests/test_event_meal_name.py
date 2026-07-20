"""Event-level meal name generation and persistence (FTY-422).

The estimator derives a short, model-generated meal name for a food-bearing event
and writes it to ``log_events.name`` (the nullable field FTY-421 created) on the
terminal completing transition. These tests pin:

- the parse step derives ``context.event_name`` from the model's whole-event name
  for a multi-item and a single-item entry, falls back to the single food's own
  name when the model offers none, and leaves it ``None`` for an exercise-only
  entry rather than fabricating a meal label;
- the untrusted model name is bounded and sanitized before it is trusted;
- an end-to-end run persists a concise name for a multi-item meal, a sensible name
  for a single item, ``null`` for an exercise-only or unparseable/failed event, and
  never copies the name into the sanitized run ``trace``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.estimator.parse import ParseStep
from app.estimator.pipeline import EstimationContext, Pipeline
from app.estimator.processing import process_estimation
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.estimation import EstimationRun
from app.models.log_events import LogEvent
from app.schemas.parse import (
    MAX_EVENT_NAME_LEN,
    ParseResult,
    sanitize_event_name,
)


def _context(raw_text: str) -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=raw_text)


def _parsed(
    items: list[dict[str, object]],
    *,
    event_name: str | None = None,
    confidence: float = 0.9,
) -> dict[str, object]:
    reply: dict[str, object] = {
        "disposition": "parsed",
        "confidence": confidence,
        "items": items,
    }
    if event_name is not None:
        reply["event_name"] = event_name
    return reply


def _sampled(reply: dict[str, Any], count: int = SELF_CONSISTENCY_FIRST_WINDOW) -> list[Any]:
    """Repeat ``reply`` once per sample; identical replies early-stop at the window."""

    return [reply for _ in range(count)]


# ---------------------------------------------------------------------------
# Parse-step derivation (no database)
# ---------------------------------------------------------------------------


def test_multi_item_event_names_to_a_concise_dish_label() -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [
                    {"type": "food", "name": "sub bun", "quantity_text": "half", "amount": 0.5},
                    {"type": "food", "name": "turkey", "quantity_text": "2 oz"},
                    {"type": "food", "name": "mozzarella", "quantity_text": "1 slice"},
                ],
                event_name="Turkey sandwich",
            )
        )
    )
    context = _context("half a sub bun with turkey, mozzarella and mustard")

    ParseStep(provider).run(context)

    # A short dish label, not the raw phrase and not a single item's name.
    assert context.event_name == "Turkey sandwich"
    assert len(context.food_candidates) == 3


def test_single_food_event_names_from_the_model() -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [{"type": "food", "name": "oatmeal", "quantity_text": "1 cup", "amount": 1}],
                event_name="Oatmeal",
            )
        )
    )
    context = _context("a cup of oatmeal")

    ParseStep(provider).run(context)

    assert context.event_name == "Oatmeal"


def test_single_food_event_falls_back_to_the_food_name_when_model_omits_it() -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed([{"type": "food", "name": "banana", "quantity_text": "1", "amount": 1}])
        )
    )
    context = _context("a banana")

    ParseStep(provider).run(context)

    # No model name, single plain food → the food's own name is a sensible, honest label.
    assert context.event_name == "banana"


def test_exercise_only_event_leaves_name_null_even_if_model_offers_one() -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [{"type": "exercise", "name": "run", "quantity_text": "30 minutes"}],
                event_name="Morning run",
            )
        )
    )
    context = _context("a 30 minute run")

    ParseStep(provider).run(context)

    # ``name`` is a meal label: an exercise-only entry stays null rather than
    # fabricating one, regardless of what the model returned.
    assert context.exercise_candidates and not context.food_candidates
    assert context.event_name is None


def test_mixed_food_and_exercise_event_names_from_the_food() -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [
                    {"type": "food", "name": "eggs", "quantity_text": "two", "amount": 2},
                    {"type": "exercise", "name": "run", "quantity_text": "30 minutes"},
                ],
                event_name="Eggs",
            )
        )
    )
    context = _context("two eggs and a 30 minute run")

    ParseStep(provider).run(context)

    assert context.event_name == "Eggs"


def test_model_name_is_bounded_and_sanitized_before_it_is_trusted() -> None:
    noisy = "Turkey\tsandwich\nwith\x00 control chars " + "x" * 200
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [{"type": "food", "name": "sandwich", "quantity_text": "1", "amount": 1}],
                event_name=noisy,
            )
        )
    )
    context = _context("a sandwich")

    ParseStep(provider).run(context)

    name = context.event_name
    assert name is not None
    assert len(name) <= MAX_EVENT_NAME_LEN
    # Control characters are stripped and whitespace collapsed.
    assert "\x00" not in name and "\t" not in name and "\n" not in name
    assert name.startswith("Turkey sandwich with control chars")


# ---------------------------------------------------------------------------
# Schema-level sanitization
# ---------------------------------------------------------------------------


def test_sanitize_event_name_drops_blank_and_non_string() -> None:
    assert sanitize_event_name("   ") is None
    assert sanitize_event_name(None) is None
    assert sanitize_event_name({"nope": 1}) is None
    assert sanitize_event_name("  Turkey  sandwich  ") == "Turkey sandwich"


def test_overlong_event_name_is_truncated_not_rejected() -> None:
    # A cosmetic label must never fail an otherwise-valid extraction.
    result = ParseResult.model_validate(
        {
            "disposition": "parsed",
            "confidence": 0.9,
            "items": [{"type": "food", "name": "x"}],
            "event_name": "y" * 500,
        }
    )
    assert result.event_name is not None
    assert len(result.event_name) == MAX_EVENT_NAME_LEN


# ---------------------------------------------------------------------------
# End-to-end persistence through the worker
# ---------------------------------------------------------------------------


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _seed_event(client: TestClient, email: str, raw_text: str) -> tuple[uuid.UUID, uuid.UUID]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": raw_text},
    )
    assert created.status_code == 201
    # FTY-421: freshly-created events are unnamed until the estimator names them.
    assert created.json()["name"] is None
    return user_id, uuid.UUID(created.json()["id"])


def _parse_only(provider: FakeProvider) -> Pipeline:
    """A single-step parse pipeline: enough to reach ``completed`` and name the event."""

    return Pipeline([ParseStep(provider)])


def test_multi_item_meal_name_persists_to_log_events_name(
    client: TestClient, session: Session
) -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [
                    {"type": "food", "name": "sub bun", "quantity_text": "half", "amount": 0.5},
                    {"type": "food", "name": "turkey", "quantity_text": "2 oz"},
                    {"type": "food", "name": "mozzarella", "quantity_text": "1 slice"},
                ],
                event_name="Turkey sandwich",
            )
        )
    )
    user_id, event_id = _seed_event(
        client, "meal-multi@example.com", "half a sub bun with turkey and mozzarella"
    )

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=_parse_only(provider)
    )

    assert result.event_status is LogEventStatus.COMPLETED
    event = session.get(LogEvent, event_id)
    assert event is not None and event.name == "Turkey sandwich"

    # Privacy: the derived name is never copied into the sanitized run trace.
    run = session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id)).one()
    assert "Turkey sandwich" not in repr(run.trace)


def test_single_food_meal_name_persists(client: TestClient, session: Session) -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [{"type": "food", "name": "oatmeal", "quantity_text": "1 cup", "amount": 1}],
                event_name="Oatmeal",
            )
        )
    )
    user_id, event_id = _seed_event(client, "meal-single@example.com", "a cup of oatmeal")

    process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=_parse_only(provider)
    )

    event = session.get(LogEvent, event_id)
    assert event is not None and event.name == "Oatmeal"


def test_exercise_only_event_leaves_name_null(client: TestClient, session: Session) -> None:
    provider = FakeProvider(
        responses=_sampled(
            _parsed(
                [{"type": "exercise", "name": "run", "quantity_text": "30 minutes"}],
                event_name="Morning run",
            )
        )
    )
    user_id, event_id = _seed_event(client, "meal-exercise@example.com", "a 30 minute run")

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=_parse_only(provider)
    )

    assert result.event_status is LogEventStatus.COMPLETED
    event = session.get(LogEvent, event_id)
    assert event is not None and event.name is None


def test_unparseable_failed_event_leaves_name_null(client: TestClient, session: Session) -> None:
    provider = FakeProvider(
        responses=_sampled({"disposition": "unparseable", "confidence": 0.0, "reason": "not a log"})
    )
    user_id, event_id = _seed_event(client, "meal-failed@example.com", "asdf qwerty")

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=_parse_only(provider)
    )

    assert result.event_status is LogEventStatus.FAILED
    event = session.get(LogEvent, event_id)
    assert event is not None and event.name is None
