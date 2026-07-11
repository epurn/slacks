"""Daily-summary API integration tests (FTY-071).

Covers all acceptance criteria from the story:
- Aggregation correctness: separated intake, target, burn for a day with finalized items.
- Empty day: zeroed totals + resolved target (or null when none exists).
- Finalized-state exclusion: non-``completed`` events and ``unresolved`` items excluded.
- Post-correction: current value (not the estimated original) is reflected.
- Timezone boundary: items near local midnight are attributed to the correct day;
  ``day`` defaults to the current local day; malformed ``day`` → 422.
- Object-level authz: cross-user request fails closed (404), negative auth test.
- Authentication: missing/invalid token → 401.

All fixtures use synthetic data; no real user logs, body data, or tokens.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus
from app.models.derived import (
    ClarificationAnswer,
    ClarificationQuestion,
    DerivedExerciseItem,
    DerivedFoodItem,
)
from app.models.log_events import LogEvent
from app.models.targets import DailyTarget, Goal

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user, returning ``(user_id, auth_header_value)``."""

    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _set_timezone(client: TestClient, user_id: str, auth: str, tz: str) -> None:
    """Update the user's profile timezone."""

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"timezone": tz},
    )
    assert resp.status_code == 200


def _seed_completed_event(
    db_engine: Engine,
    user_id: str,
    *,
    created_at: datetime | None = None,
    status: str = LogEventStatus.COMPLETED,
) -> uuid.UUID:
    """Insert a log event at the given status and return its id."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(
            user_id=uuid.UUID(user_id),
            raw_text="seed event",
            status=status,
            **({"created_at": created_at} if created_at is not None else {}),
        )
        session.add(event)
        session.commit()
        return event.id


def _seed_food_item(
    db_engine: Engine,
    user_id: str,
    event_id: uuid.UUID,
    *,
    calories: float | None = 200.0,
    protein_g: float | None = 10.0,
    carbs_g: float | None = 30.0,
    fat_g: float | None = 5.0,
    item_status: str = DerivedItemStatus.RESOLVED,
) -> uuid.UUID:
    """Insert a derived food item and return its id."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedFoodItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name="test food",
            quantity_text="1 serving",
            status=item_status,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            calories_estimated=calories,
            protein_g_estimated=protein_g,
            carbs_g_estimated=carbs_g,
            fat_g_estimated=fat_g,
        )
        session.add(item)
        session.commit()
        return item.id


def _seed_exercise_item(
    db_engine: Engine,
    user_id: str,
    event_id: uuid.UUID,
    *,
    active_calories: float | None = 150.0,
    item_status: str = DerivedItemStatus.RESOLVED,
) -> uuid.UUID:
    """Insert a derived exercise item and return its id."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedExerciseItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name="running",
            quantity_text="30 min",
            status=item_status,
            active_calories=active_calories,
            active_calories_estimated=active_calories,
        )
        session.add(item)
        session.commit()
        return item.id


def _seed_daily_target(
    db_engine: Engine,
    user_id: str,
    *,
    for_date: date,
    daily_calorie_target_kcal: int = 2000,
    is_active: bool = True,
    override_calorie_target_kcal: int | None = None,
    override_protein_target_g: int | None = None,
    override_carbs_target_g: int | None = None,
    override_fat_target_g: int | None = None,
) -> None:
    """Insert an active goal + daily_target for ``for_date``.

    Persists the derived macro columns (FTY-094/FTY-095) so the NOT NULL schema is
    satisfied; the optional calorie/macro overrides exercise the per-target
    read-model provenance independently (FTY-105).
    """

    factory = create_session_factory(db_engine)
    with factory() as session:
        goal = Goal(
            user_id=uuid.UUID(user_id),
            start_weight_kg=80.0,
            start_date=date(2026, 1, 1),
            target_weight_kg=75.0,
            target_date=date(2026, 12, 31),
            is_active=is_active,
        )
        session.add(goal)
        session.flush()
        target = DailyTarget(
            user_id=uuid.UUID(user_id),
            goal_id=goal.id,
            for_date=for_date,
            rmr_kcal=1680.0,
            tdee_kcal=2016.0,
            daily_calorie_target_kcal=daily_calorie_target_kcal,
            clamped=False,
            protein_target_g=128,
            carbs_target_g=200,
            fat_target_g=67,
            macros_clamped=False,
            override_calorie_target_kcal=override_calorie_target_kcal,
            override_protein_target_g=override_protein_target_g,
            override_carbs_target_g=override_carbs_target_g,
            override_fat_target_g=override_fat_target_g,
            inputs={},
            assumptions={},
        )
        session.add(target)
        session.commit()


# ---------------------------------------------------------------------------
# Aggregation: correct separated totals
# ---------------------------------------------------------------------------


def test_calorie_only_user_text_item_counts_calories_without_fabricating_macros(
    client: TestClient, db_engine: Engine
) -> None:
    """A calorie-only ``user_text`` item counts its calories; unknown macros are skipped.

    FTY-279/280: a resolved item with known calories but ``None`` macros contributes
    its calories to ``intake.calories`` while each unknown macro contributes **no**
    grams (skipped, never summed as ``0``) — so mixing it with a fully-known item
    yields the known item's macros, not an inflated-by-zero total.
    """

    user_id, auth = _register(client, "usertext-summary@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)

    # A calorie-only user-stated item: 580 kcal, macros unknown (None).
    _seed_food_item(
        db_engine,
        user_id,
        event_id,
        calories=580.0,
        protein_g=None,
        carbs_g=None,
        fat_g=None,
    )
    # A fully-known item alongside it.
    _seed_food_item(
        db_engine,
        user_id,
        event_id,
        calories=200.0,
        protein_g=10.0,
        carbs_g=30.0,
        fat_g=5.0,
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    # Calories from both items count; the unknown macros are skipped, so the macro
    # totals reflect only the known item — never inflated by a fabricated 0.
    assert body["intake"]["calories"] == 780.0
    assert body["intake"]["protein_g"] == 10.0
    assert body["intake"]["carbs_g"] == 30.0
    assert body["intake"]["fat_g"] == 5.0
    assert body["has_intake"] is True


def test_aggregation_returns_correct_separated_totals(
    client: TestClient, db_engine: Engine
) -> None:
    """A day with finalized food+exercise items returns correct separated totals."""

    user_id, auth = _register(client, "aggr@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)

    # Two food items: totals should be summed across both
    _seed_food_item(
        db_engine,
        user_id,
        event_id,
        calories=300.0,
        protein_g=20.0,
        carbs_g=40.0,
        fat_g=8.0,
    )
    _seed_food_item(
        db_engine,
        user_id,
        event_id,
        calories=150.5,
        protein_g=5.5,
        carbs_g=18.0,
        fat_g=3.0,
    )
    _seed_exercise_item(db_engine, user_id, event_id, active_calories=210.0)
    _seed_daily_target(db_engine, user_id, for_date=today, daily_calorie_target_kcal=1800)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()

    # Intake sums (rounded to 0.1)
    assert body["intake"]["calories"] == 450.5
    assert body["intake"]["protein_g"] == 25.5
    assert body["intake"]["carbs_g"] == 58.0
    assert body["intake"]["fat_g"] == 11.0
    # Finalized food items were logged → has_intake is True.
    assert body["has_intake"] is True

    # Exercise: not netted into intake
    assert body["exercise"]["active_calories"] == 210.0

    # Target from stored daily_targets row: derived calorie target, no override.
    assert body["target"] is not None
    assert body["target"]["calories"] == {
        "effective": 1800,
        "derived": 1800,
        "source": "derived",
    }
    # Macro targets ride along with provenance (FTY-094/FTY-095).
    assert body["target"]["protein_g"]["effective"] == 128
    assert body["target"]["protein_g"]["source"] == "derived"

    # Date echoed back
    assert body["date"] == str(today)


def test_burn_is_not_netted_into_intake(client: TestClient, db_engine: Engine) -> None:
    """Burn is reported separately; intake is not reduced by exercise burn."""

    user_id, auth = _register(client, "net@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)
    _seed_food_item(db_engine, user_id, event_id, calories=500.0)
    _seed_exercise_item(db_engine, user_id, event_id, active_calories=100.0)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    # Intake must equal the raw food total, not (food - burn)
    assert body["intake"]["calories"] == 500.0
    assert body["exercise"]["active_calories"] == 100.0


# ---------------------------------------------------------------------------
# Empty day
# ---------------------------------------------------------------------------


def test_empty_day_returns_zeroed_intake_and_burn(client: TestClient, db_engine: Engine) -> None:
    """An empty day returns zeroed totals + burn, with the stored target."""

    user_id, auth = _register(client, "empty@example.com")
    empty_day = date(2025, 1, 1)
    _seed_daily_target(db_engine, user_id, for_date=empty_day, daily_calorie_target_kcal=2000)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(empty_day)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["intake"] == {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    # No finalized food item → has_intake is False even though intake is zeroed,
    # so a consumer can tell this unlogged day from a genuine 0-kcal day.
    assert body["has_intake"] is False
    assert body["exercise"] == {"active_calories": 0.0}
    assert body["target"]["calories"]["effective"] == 2000
    assert body["target"]["calories"]["source"] == "derived"


def test_empty_day_with_no_target_returns_null_target(
    client: TestClient, db_engine: Engine
) -> None:
    """An empty day with no active goal returns null target, not a zero."""

    user_id, auth = _register(client, "notarget@example.com")
    empty_day = date(2025, 1, 2)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(empty_day)},
    )

    assert resp.status_code == 200
    body = resp.json()
    # target is null: no active goal, not zero
    assert body["target"] is None
    assert body["intake"]["calories"] == 0.0


def test_overridden_calorie_target_surfaces_as_user_source(
    client: TestClient, db_engine: Engine
) -> None:
    """A calorie override is the effective value with source ``user``; derived holds."""

    user_id, auth = _register(client, "override-summary@example.com")
    day = date(2025, 3, 1)
    _seed_daily_target(
        db_engine,
        user_id,
        for_date=day,
        daily_calorie_target_kcal=2000,
        override_calorie_target_kcal=1700,
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(day)},
    )

    assert resp.status_code == 200
    calories = resp.json()["target"]["calories"]
    assert calories == {"effective": 1700, "derived": 2000, "source": "user"}


def test_macro_override_is_independent_per_target(client: TestClient, db_engine: Engine) -> None:
    """A protein override surfaces ``source: user`` for protein only; others derived.

    Per-macro (and calorie) provenance is independent — overriding one target must
    not flip another's ``source`` (FTY-105, matching FTY-095's independent
    override/reset).
    """

    user_id, auth = _register(client, "macro-override@example.com")
    day = date(2025, 3, 2)
    _seed_daily_target(
        db_engine,
        user_id,
        for_date=day,
        override_protein_target_g=150,
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(day)},
    )

    assert resp.status_code == 200
    target = resp.json()["target"]
    # The overridden macro: effective is the override, derived holds, source ``user``.
    assert target["protein_g"] == {"effective": 150, "derived": 128, "source": "user"}
    # Every other target is untouched: effective == derived, source ``derived``.
    assert target["calories"]["source"] == "derived"
    assert target["carbs_g"] == {"effective": 200, "derived": 200, "source": "derived"}
    assert target["fat_g"] == {"effective": 67, "derived": 67, "source": "derived"}


def test_target_macros_are_int_grams_distinct_from_float_intake_macros(
    client: TestClient, db_engine: Engine
) -> None:
    """Target macros are int grams; consumed intake macros are floats — not conflated.

    The target read-model carries whole-gram ints (FTY-094/FTY-095) while intake
    sums are 0.1-rounded floats; both must be present and read as separate
    components (FTY-105).
    """

    user_id, auth = _register(client, "int-vs-float@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)
    _seed_food_item(db_engine, user_id, event_id, calories=300.0, protein_g=20.5)
    _seed_daily_target(db_engine, user_id, for_date=today)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    consumed = body["intake"]["protein_g"]
    target_effective = body["target"]["protein_g"]["effective"]
    # Both present, and the JSON types stay distinct: consumed is a 0.1-rounded
    # float, the target is a whole-gram int (a bool is not an int here).
    assert consumed == 20.5
    assert isinstance(consumed, float)
    assert target_effective == 128
    assert isinstance(target_effective, int) and not isinstance(target_effective, bool)


# ---------------------------------------------------------------------------
# Finalized-state filtering
# ---------------------------------------------------------------------------


def test_non_completed_events_are_excluded(client: TestClient, db_engine: Engine) -> None:
    """Items on pending/failed/needs_clarification events are not counted.

    Even a stray ``resolved`` item on one of these non-finalized statuses never
    inflates a total — the finalized-event gate only ever admits ``completed`` /
    ``partially_resolved``, plus the scoped-re-estimate ``processing`` case covered
    separately (FTY-349). ``processing`` is exercised in its own tests because the
    new rule discriminates a first-pass from a scoped re-estimate by committed
    resolved siblings.
    """

    user_id, auth = _register(client, "statuses@example.com")
    today = datetime.now(UTC).date()

    for non_final_status in (
        LogEventStatus.PENDING,
        LogEventStatus.FAILED,
        LogEventStatus.NEEDS_CLARIFICATION,
    ):
        evt_id = _seed_completed_event(db_engine, user_id, status=non_final_status)
        _seed_food_item(db_engine, user_id, evt_id, calories=999.0)
        _seed_exercise_item(db_engine, user_id, evt_id, active_calories=999.0)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    # No finalized events, so totals are zero
    assert body["intake"]["calories"] == 0.0
    assert body["exercise"]["active_calories"] == 0.0


# ---------------------------------------------------------------------------
# FTY-349: the day total is stable while an item-scoped answer re-estimates
# ---------------------------------------------------------------------------


def _seed_partial_like_event(
    db_engine: Engine,
    user_id: str,
    *,
    status: str,
    created_at: datetime | None = None,
    answered: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed a mixed log at ``status`` with a committed ``resolved`` sibling
    (180 kcal), a still-``unresolved`` component, and one open item-scoped question
    on it. Returns ``(event_id, sibling_id, unresolved_id)``.

    At ``partially_resolved`` this is the FTY-278 pinned partial state; at
    ``processing`` with ``answered=True`` it is the exact DB state mid
    answer-triggered scoped re-estimate: the real answer flow persists the
    ``ClarificationAnswer`` in the same transaction that flips the event
    ``partially_resolved → processing``, so the in-flight window has the question
    answered but its component still ``unresolved`` (FTY-349).
    """

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(
            user_id=uuid.UUID(user_id),
            raw_text="peanut butter toast and milk amount pending",
            status=status,
            **({"created_at": created_at} if created_at is not None else {}),
        )
        session.add(event)
        session.flush()
        sibling = DerivedFoodItem(
            log_event_id=event.id,
            user_id=uuid.UUID(user_id),
            name="peanut butter toast",
            quantity_text="1 slice",
            status=DerivedItemStatus.RESOLVED,
            calories=180.0,
            protein_g=7.0,
            carbs_g=22.0,
            fat_g=8.0,
            calories_estimated=180.0,
        )
        unresolved = DerivedFoodItem(
            log_event_id=event.id,
            user_id=uuid.UUID(user_id),
            name="milk",
            quantity_text="",
            status=DerivedItemStatus.UNRESOLVED,
        )
        session.add_all([sibling, unresolved])
        session.flush()
        question = ClarificationQuestion(
            log_event_id=event.id,
            user_id=uuid.UUID(user_id),
            question_text="How much milk?",
            options=["a splash", "1/2 cup", "1 cup"],
            derived_food_item_id=unresolved.id,
            position=0,
        )
        session.add(question)
        session.flush()
        if answered:
            session.add(
                ClarificationAnswer(
                    question_id=question.id,
                    log_event_id=event.id,
                    user_id=uuid.UUID(user_id),
                    answer_text="1 cup",
                )
            )
        session.commit()
        return event.id, sibling.id, unresolved.id


def test_committed_sibling_stays_counted_during_scoped_reestimate(
    client: TestClient, db_engine: Engine
) -> None:
    """A committed resolved sibling keeps counting while the event re-estimates.

    The event has flipped ``partially_resolved → processing`` to re-cost its open
    component, and — as in the real answer flow — the question's
    ``ClarificationAnswer`` row is already committed while the component is still
    ``unresolved``. The already-committed sibling must stay in ``intake`` and the
    answered-but-not-yet-resolved question in ``uncounted_entries`` — no surface
    dips and reappears (FTY-349, calm-by-default).
    """

    user_id, auth = _register(client, "scoped-reestimate@example.com")
    today = datetime.now(UTC).date()
    _seed_partial_like_event(db_engine, user_id, status=LogEventStatus.PROCESSING, answered=True)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    # The sibling is still counted while the event is ``processing``; the open
    # component (unresolved, no calories) is not — the total is exactly the sibling,
    # and its still-open question stays counted for the whole window.
    assert body["intake"]["calories"] == 180.0
    assert body["has_intake"] is True
    assert body["uncounted_entries"] == 1


def test_first_pass_processing_event_contributes_nothing(
    client: TestClient, db_engine: Engine
) -> None:
    """A first-pass ``processing`` event (no committed resolved item) is excluded.

    The estimator is still working its initial pass — nothing counts early. The
    scoped-re-estimate clause is discriminated by a committed resolved sibling,
    which a first-pass event never has (FTY-349).
    """

    user_id, auth = _register(client, "first-pass-processing@example.com")
    today = datetime.now(UTC).date()

    evt_id = _seed_completed_event(db_engine, user_id, status=LogEventStatus.PROCESSING)
    # First-pass processing: only uncommitted, unresolved items exist.
    _seed_food_item(
        db_engine, user_id, evt_id, calories=None, item_status=DerivedItemStatus.UNRESOLVED
    )
    _seed_exercise_item(
        db_engine, user_id, evt_id, active_calories=None, item_status=DerivedItemStatus.UNRESOLVED
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["intake"]["calories"] == 0.0
    assert body["exercise"]["active_calories"] == 0.0
    assert body["has_intake"] is False
    assert body["uncounted_entries"] == 0


def test_day_total_is_flat_before_during_and_after_scoped_reestimate(
    client: TestClient, db_engine: Engine
) -> None:
    """The day total is identical before, during, and after a scoped re-estimate.

    The DURING state is produced by the **real answer flow** (the clarification
    answers endpoint), which commits the ``ClarificationAnswer`` row in the same
    transaction that flips the event to ``processing`` — the exact in-flight state
    a scoped re-estimate leaves in the DB. The sibling's calories hold flat across
    all three moments and resolving the open component raises the total by exactly
    the new item — never re-adding or double-counting the sibling.
    """

    user_id, auth = _register(client, "flat-total@example.com")
    day = date(2026, 7, 10)
    at = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    _set_timezone(client, user_id, auth, "UTC")

    def _intake_and_uncounted() -> tuple[float, int]:
        resp = client.get(
            f"/api/users/{user_id}/daily-summary",
            headers={"Authorization": auth},
            params={"day": str(day)},
        )
        assert resp.status_code == 200
        body = resp.json()
        return body["intake"]["calories"], body["uncounted_entries"]

    # BEFORE: partially_resolved with a committed sibling + one open question.
    event_id, _sibling_id, unresolved_id = _seed_partial_like_event(
        db_engine, user_id, status=LogEventStatus.PARTIALLY_RESOLVED, created_at=at
    )
    assert _intake_and_uncounted() == (180.0, 1)

    # DURING: answer the open question through the real endpoint. The answer row
    # commits in the same transaction that flips the event to ``processing``, so
    # the question is answered while its component is still unresolved — the state
    # the read model must not let dip.
    questions = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )
    assert questions.status_code == 200
    question_id = questions.json()["questions"][0]["id"]
    answered = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/clarification/answers",
        headers={"Authorization": auth},
        json={"question_id": question_id, "answer": "1 cup"},
    )
    assert answered.status_code == 201
    assert answered.json()["status"] == "processing"
    assert _intake_and_uncounted() == (180.0, 1)

    # AFTER: the open component resolves and the event completes; the total rises
    # by exactly the newly-resolved item and the sibling is unchanged.
    factory = create_session_factory(db_engine)
    with factory() as session:
        event = session.get(LogEvent, event_id)
        item = session.get(DerivedFoodItem, unresolved_id)
        assert event is not None and item is not None
        item.status = DerivedItemStatus.RESOLVED
        item.calories = 120.0
        item.calories_estimated = 120.0
        event.status = LogEventStatus.COMPLETED
        session.commit()
    assert _intake_and_uncounted() == (300.0, 0)


def test_range_and_has_intake_match_single_day_during_scoped_reestimate(
    client: TestClient, db_engine: Engine
) -> None:
    """The by-date/range read and ``has_intake`` match the single-day rule mid re-estimate.

    Every intake surface keys on committed resolved items, so the range read and
    ``has_intake`` keep the sibling counted during the scoped re-estimate exactly
    like the single-day path — no surface dips (FTY-349). The seed carries the
    committed answer row the real answer flow leaves in place mid-window.
    """

    user_id, auth = _register(client, "scoped-range-parity@example.com")
    _set_timezone(client, user_id, auth, "UTC")
    _seed_partial_like_event(
        db_engine,
        user_id,
        status=LogEventStatus.PROCESSING,
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        answered=True,
    )

    single = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-07-10"},
    )
    ranged = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-07-10", "to": "2026-07-10"},
    )

    assert single.status_code == 200
    assert ranged.status_code == 200
    # The range read is the same read-model over a window: identical DTO per day.
    assert ranged.json() == [single.json()]
    day_row = ranged.json()[0]
    assert day_row["intake"]["calories"] == 180.0
    assert day_row["has_intake"] is True
    assert day_row["uncounted_entries"] == 1


def test_unresolved_items_are_excluded(client: TestClient, db_engine: Engine) -> None:
    """Items with status='unresolved' and NULL calories are not counted."""

    user_id, auth = _register(client, "unresolved@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)

    # Unresolved food item (status=unresolved, calories=None)
    _seed_food_item(
        db_engine,
        user_id,
        event_id,
        calories=None,
        protein_g=None,
        carbs_g=None,
        fat_g=None,
        item_status=DerivedItemStatus.UNRESOLVED,
    )
    # Unresolved exercise item
    _seed_exercise_item(
        db_engine,
        user_id,
        event_id,
        active_calories=None,
        item_status=DerivedItemStatus.UNRESOLVED,
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["intake"]["calories"] == 0.0
    assert body["exercise"]["active_calories"] == 0.0


def test_only_completed_events_contribute(client: TestClient, db_engine: Engine) -> None:
    """Completed events' items are included; other statuses are excluded."""

    user_id, auth = _register(client, "mixed@example.com")
    today = datetime.now(UTC).date()

    # One completed event with a food item
    good_event_id = _seed_completed_event(db_engine, user_id)
    _seed_food_item(db_engine, user_id, good_event_id, calories=400.0)

    # One pending event with a food item that must NOT be counted
    bad_event_id = _seed_completed_event(db_engine, user_id, status=LogEventStatus.PENDING)
    _seed_food_item(db_engine, user_id, bad_event_id, calories=600.0)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    # Only the 400.0 from the completed event should be included
    assert body["intake"]["calories"] == 400.0


# ---------------------------------------------------------------------------
# Post-correction: current value is reflected
# ---------------------------------------------------------------------------


def test_post_correction_current_value_is_reflected(client: TestClient, db_engine: Engine) -> None:
    """After a food item correction, the summary reflects the current value."""

    user_id, auth = _register(client, "correction@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)
    item_id = _seed_food_item(
        db_engine,
        user_id,
        event_id,
        calories=200.0,
        protein_g=10.0,
        carbs_g=30.0,
        fat_g=5.0,
    )

    # Simulate a FTY-051 correction by directly updating the current value
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        item.calories = 180.0  # user corrected the calorie value
        session.commit()

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    # Must reflect 180.0 (corrected), not 200.0 (estimated)
    assert body["intake"]["calories"] == 180.0


def test_exercise_post_correction_reflected(client: TestClient, db_engine: Engine) -> None:
    """After an exercise item correction, the summary reflects the current burn."""

    user_id, auth = _register(client, "exr-correction@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)
    item_id = _seed_exercise_item(db_engine, user_id, event_id, active_calories=200.0)

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedExerciseItem, item_id)
        assert item is not None
        item.active_calories = 175.0
        session.commit()

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    assert resp.json()["exercise"]["active_calories"] == 175.0


# ---------------------------------------------------------------------------
# Timezone boundary and day resolution
# ---------------------------------------------------------------------------


def test_day_defaults_to_current_local_day(client: TestClient) -> None:
    """``day`` defaults to the current day in the user's profile timezone."""

    user_id, auth = _register(client, "tz-default@example.com")

    # No ``day`` param: should return a 200 for the current local day
    resp = client.get(f"/api/users/{user_id}/daily-summary", headers={"Authorization": auth})

    assert resp.status_code == 200
    body = resp.json()
    # The returned date must be today in UTC (default timezone is UTC)
    today_utc = datetime.now(UTC).date()
    assert body["date"] == str(today_utc)


def test_malformed_day_returns_422(client: TestClient) -> None:
    """A malformed ``day`` query parameter returns 422."""

    user_id, auth = _register(client, "badday@example.com")

    for bad_day in ("not-a-date", "2025-13-01", "20250101", "2025/01/01"):
        resp = client.get(
            f"/api/users/{user_id}/daily-summary",
            headers={"Authorization": auth},
            params={"day": bad_day},
        )
        assert resp.status_code == 422, f"expected 422 for day={bad_day!r}, got {resp.status_code}"


def test_timezone_boundary_attribution(client: TestClient, db_engine: Engine) -> None:
    """Items near local midnight are attributed to the correct profile-timezone day.

    Scenario: user timezone is "America/New_York" (UTC-5 standard time). Two
    events are created:
    - Event A: UTC 2026-01-02 04:59 → local 2026-01-01 23:59 → NY day 2026-01-01
    - Event B: UTC 2026-01-02 05:00 → local 2026-01-02 00:00 → NY day 2026-01-02

    Querying for NY day 2026-01-01 must include only event A's item.
    Querying for NY day 2026-01-02 must include only event B's item.
    """

    user_id, auth = _register(client, "tz-boundary@example.com")
    _set_timezone(client, user_id, auth, "America/New_York")

    # 04:59 UTC on 2026-01-02 → 23:59 EST (2026-01-01) in America/New_York
    event_a_id = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 1, 2, 4, 59, 0, tzinfo=UTC)
    )
    # 05:00 UTC on 2026-01-02 → 00:00 EST (2026-01-02) in America/New_York
    event_b_id = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 1, 2, 5, 0, 0, tzinfo=UTC)
    )

    _seed_food_item(db_engine, user_id, event_a_id, calories=100.0)
    _seed_food_item(db_engine, user_id, event_b_id, calories=200.0)

    resp_day1 = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-01-01"},
    )
    resp_day2 = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-01-02"},
    )

    assert resp_day1.status_code == 200
    assert resp_day2.status_code == 200
    # Event A (100 kcal) → NY day 2026-01-01
    assert resp_day1.json()["intake"]["calories"] == 100.0
    # Event B (200 kcal) → NY day 2026-01-02
    assert resp_day2.json()["intake"]["calories"] == 200.0


# ---------------------------------------------------------------------------
# Authentication: 401 for missing/invalid token
# ---------------------------------------------------------------------------


def test_missing_token_returns_401(client: TestClient) -> None:
    """A request without a bearer token returns 401."""

    user_id, _auth = _register(client, "noauth@example.com")

    resp = client.get(f"/api/users/{user_id}/daily-summary")

    assert resp.status_code == 401


def test_invalid_token_returns_401(client: TestClient) -> None:
    """A request with a bad bearer token returns 401."""

    user_id, _auth = _register(client, "badtoken@example.com")

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Object-level authorization: cross-user access fails closed (404)
# ---------------------------------------------------------------------------


def test_cross_user_access_fails_closed(client: TestClient, db_engine: Engine) -> None:
    """A cross-user daily-summary request fails closed as 404 (negative authz test).

    Alice presents a valid token but targets Bob's account. The response must be
    404 — indistinguishable from a missing account — and must not reveal Bob's data.
    """

    _alice_id, alice_auth = _register(client, "alice-summary@example.com")
    bob_id, bob_auth = _register(client, "bob-summary@example.com")
    today = datetime.now(UTC).date()

    # Seed Bob's data so there is something to not-reveal
    event_id = _seed_completed_event(db_engine, bob_id)
    _seed_food_item(db_engine, bob_id, event_id, calories=999.0)

    # Alice's valid token targeting Bob's endpoint
    resp = client.get(
        f"/api/users/{bob_id}/daily-summary",
        headers={"Authorization": alice_auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 404

    # Bob can still read his own data
    bob_resp = client.get(
        f"/api/users/{bob_id}/daily-summary",
        headers={"Authorization": bob_auth},
        params={"day": str(today)},
    )
    assert bob_resp.status_code == 200
    assert bob_resp.json()["intake"]["calories"] == 999.0


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def test_aggregation_rounding_to_one_decimal(client: TestClient, db_engine: Engine) -> None:
    """Final sums are rounded to 0.1, matching the FTY-043/044 precision."""

    user_id, auth = _register(client, "rounding@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)

    # Three items with values that produce a repeating decimal when summed
    for cal in (100.1, 100.1, 100.1):
        _seed_food_item(
            db_engine,
            user_id,
            event_id,
            calories=cal,
            protein_g=0.0,
            carbs_g=0.0,
            fat_g=0.0,
        )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    # 100.1 + 100.1 + 100.1 = 300.3 (exact in Python floats at this scale)
    assert resp.json()["intake"]["calories"] == pytest.approx(300.3, abs=0.05)


# ---------------------------------------------------------------------------
# Target: inactive goal is not resolved
# ---------------------------------------------------------------------------


def test_inactive_goal_yields_null_target(client: TestClient, db_engine: Engine) -> None:
    """A daily_targets row for an inactive goal is not returned as the day's target."""

    user_id, auth = _register(client, "inactive-goal@example.com")
    today = datetime.now(UTC).date()
    _seed_daily_target(
        db_engine, user_id, for_date=today, daily_calorie_target_kcal=1500, is_active=False
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    # Inactive goal: target must be null, not 1500
    assert resp.json()["target"] is None


# ---------------------------------------------------------------------------
# Range read-model: GET /daily-summary/range?from&to
# ---------------------------------------------------------------------------


def test_range_returns_one_summary_per_day_oldest_first(
    client: TestClient, db_engine: Engine
) -> None:
    """A range read returns every calendar day in ``[from, to]``, oldest-first.

    Each day's intake is attributed to that day; days without finalized data come
    back zeroed (never absent), so the client renders the strip from one request.
    """

    user_id, auth = _register(client, "range-series@example.com")
    _set_timezone(client, user_id, auth, "UTC")

    # Finalized food on 2026-03-02 (100 kcal) and 2026-03-04 (250 kcal); the days
    # in between have no data.
    event_d2 = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, user_id, event_d2, calories=100.0)
    event_d4 = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, user_id, event_d4, calories=250.0)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-03-01", "to": "2026-03-05"},
    )

    assert resp.status_code == 200
    body = resp.json()
    # One entry per day, inclusive, oldest-first.
    assert [row["date"] for row in body] == [
        "2026-03-01",
        "2026-03-02",
        "2026-03-03",
        "2026-03-04",
        "2026-03-05",
    ]
    by_date = {row["date"]: row for row in body}
    assert by_date["2026-03-02"]["intake"]["calories"] == 100.0
    assert by_date["2026-03-04"]["intake"]["calories"] == 250.0
    # Empty days are present and zeroed (not omitted, not netted).
    assert by_date["2026-03-01"]["intake"]["calories"] == 0.0
    assert by_date["2026-03-03"]["intake"]["calories"] == 0.0
    assert by_date["2026-03-03"]["exercise"]["active_calories"] == 0.0


def test_range_has_intake_distinguishes_unlogged_from_zero_kcal_days(
    client: TestClient, db_engine: Engine
) -> None:
    """``has_intake`` separates an unlogged range day from a genuine 0-kcal day.

    The range path returns every calendar day with a zeroed ``intake`` for days the
    user never logged. Without a signal a consumer cannot tell that zero from a day
    whose only logged food is genuinely zero-kcal (e.g. water). ``has_intake`` is
    that signal — ``False`` only for the unlogged day — so the Trends adherence
    average excludes unlogged days instead of counting them as real 0-kcal days.
    """

    user_id, auth = _register(client, "range-has-intake@example.com")
    _set_timezone(client, user_id, auth, "UTC")

    # 2026-07-01: a real meal (300 kcal). 2026-07-02: never logged. 2026-07-03: a
    # genuinely logged zero-kcal item (water).
    event_logged = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, user_id, event_logged, calories=300.0)
    event_zero = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 7, 3, 12, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(
        db_engine, user_id, event_zero, calories=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-07-01", "to": "2026-07-03"},
    )

    assert resp.status_code == 200
    by_date = {row["date"]: row for row in resp.json()}
    # Both the logged meal and the logged-zero day carry has_intake True; only the
    # unlogged day in between is False — yet all three serialize intake as a number.
    assert by_date["2026-07-01"]["intake"]["calories"] == 300.0
    assert by_date["2026-07-01"]["has_intake"] is True
    assert by_date["2026-07-02"]["intake"]["calories"] == 0.0
    assert by_date["2026-07-02"]["has_intake"] is False
    assert by_date["2026-07-03"]["intake"]["calories"] == 0.0
    assert by_date["2026-07-03"]["has_intake"] is True


def test_range_matches_single_day_endpoint_per_day(client: TestClient, db_engine: Engine) -> None:
    """Each day in a range read carries the same DTO the single-day route returns."""

    user_id, auth = _register(client, "range-parity@example.com")
    _set_timezone(client, user_id, auth, "UTC")

    event_id = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 4, 10, 9, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, user_id, event_id, calories=300.0, protein_g=20.0)
    _seed_exercise_item(db_engine, user_id, event_id, active_calories=180.0)
    _seed_daily_target(
        db_engine, user_id, for_date=date(2026, 4, 10), daily_calorie_target_kcal=1900
    )

    single = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-04-10"},
    )
    ranged = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-04-10", "to": "2026-04-10"},
    )

    assert single.status_code == 200
    assert ranged.status_code == 200
    assert ranged.json() == [single.json()]


def test_range_target_carries_forward_within_horizon(client: TestClient, db_engine: Engine) -> None:
    """The target carries forward across the range within the goal's horizon.

    A row is stored only on goal-creation day, but the daily target is constant
    across the goal horizon (start 2026-01-01 → target 2026-12-31 per the seed), so
    every in-horizon day at or after the first stored row reports that target.
    Days *before* the first stored row remain an explicit null (not zero).
    """

    user_id, auth = _register(client, "range-carry-target@example.com")
    _set_timezone(client, user_id, auth, "UTC")
    _seed_daily_target(
        db_engine, user_id, for_date=date(2026, 5, 2), daily_calorie_target_kcal=2100
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-05-01", "to": "2026-05-04"},
    )

    assert resp.status_code == 200
    by_date = {row["date"]: row for row in resp.json()}
    # Day before the first stored row: still an explicit null.
    assert by_date["2026-05-01"]["target"] is None
    # The stored day and every later in-horizon day carry the same target.
    assert by_date["2026-05-02"]["target"]["calories"]["effective"] == 2100
    assert by_date["2026-05-03"]["target"]["calories"]["effective"] == 2100
    assert by_date["2026-05-04"]["target"]["calories"]["effective"] == 2100


def test_single_day_target_carries_forward_to_a_later_in_horizon_day(
    client: TestClient, db_engine: Engine
) -> None:
    """The Today daily-summary shows the carried target on a day after creation.

    A target row is stored only on goal-creation day, but a later in-horizon day
    must still report it (the constant-across-horizon daily target) — otherwise the
    Today screen's calories-vs-target headline goes blank the day after onboarding.
    """

    user_id, auth = _register(client, "single-carry-target@example.com")
    _set_timezone(client, user_id, auth, "UTC")
    _seed_daily_target(
        db_engine, user_id, for_date=date(2026, 5, 2), daily_calorie_target_kcal=2100
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-06-15"},  # weeks later, still within the seed's horizon
    )

    assert resp.status_code == 200
    assert resp.json()["target"]["calories"]["effective"] == 2100


def test_range_with_from_after_to_returns_422_with_ordering_message(client: TestClient) -> None:
    """``from`` after ``to`` is rejected with 422 and an ordering-specific message."""

    user_id, auth = _register(client, "range-inverted@example.com")
    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-06-10", "to": "2026-06-01"},
    )
    assert resp.status_code == 422
    # The message must reflect the ordering error, not the span error
    assert "on or before" in resp.json()["detail"]


def test_range_exceeding_max_span_returns_422_with_span_message(client: TestClient) -> None:
    """A range wider than the bounded maximum is rejected with 422 (no unbounded scan)."""

    user_id, auth = _register(client, "range-too-wide@example.com")
    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        # > 366 days
        params={"from": "2025-01-01", "to": "2026-06-01"},
    )
    assert resp.status_code == 422
    # The message must reflect the span error, not the ordering error
    assert "may not exceed" in resp.json()["detail"]


def test_range_cross_user_access_fails_closed(client: TestClient, db_engine: Engine) -> None:
    """A cross-user range request fails closed as 404, never revealing the owner's data."""

    _alice_id, alice_auth = _register(client, "alice-range@example.com")
    bob_id, bob_auth = _register(client, "bob-range@example.com")

    event_id = _seed_completed_event(
        db_engine, bob_id, created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, bob_id, event_id, calories=777.0)

    resp = client.get(
        f"/api/users/{bob_id}/daily-summary/range",
        headers={"Authorization": alice_auth},
        params={"from": "2026-06-01", "to": "2026-06-02"},
    )
    assert resp.status_code == 404

    # Bob can still read his own range.
    bob_resp = client.get(
        f"/api/users/{bob_id}/daily-summary/range",
        headers={"Authorization": bob_auth},
        params={"from": "2026-06-01", "to": "2026-06-02"},
    )
    assert bob_resp.status_code == 200
    by_date = {row["date"]: row for row in bob_resp.json()}
    assert by_date["2026-06-01"]["intake"]["calories"] == 777.0


def test_range_missing_token_returns_401(client: TestClient) -> None:
    """A range request without a bearer token is rejected with 401."""

    user_id = "11111111-1111-1111-1111-111111111111"
    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        params={"from": "2026-06-01", "to": "2026-06-02"},
    )
    assert resp.status_code == 401


def test_range_malformed_date_params_return_422(client: TestClient) -> None:
    """Malformed ``from`` or ``to`` date strings are rejected with 422."""

    user_id, auth = _register(client, "range-malformed@example.com")

    for bad in ("not-a-date", "2025-13-01", "20260101", "2026/01/01"):
        resp = client.get(
            f"/api/users/{user_id}/daily-summary/range",
            headers={"Authorization": auth},
            params={"from": bad, "to": "2026-01-31"},
        )
        assert resp.status_code == 422, f"expected 422 for from={bad!r}, got {resp.status_code}"

        resp = client.get(
            f"/api/users/{user_id}/daily-summary/range",
            headers={"Authorization": auth},
            params={"from": "2026-01-01", "to": bad},
        )
        assert resp.status_code == 422, f"expected 422 for to={bad!r}, got {resp.status_code}"


def test_range_missing_required_params_return_422(client: TestClient) -> None:
    """Missing ``from`` or ``to`` query parameters are rejected with 422."""

    user_id, auth = _register(client, "range-missing-params@example.com")

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-01-01"},
    )
    assert resp.status_code == 422

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"to": "2026-01-31"},
    )
    assert resp.status_code == 422

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Uncounted entries: logged-but-not-yet-counted count (FTY-223)
# ---------------------------------------------------------------------------


def test_uncounted_only_day_single_and_range(client: TestClient, db_engine: Engine) -> None:
    """A day whose only entries await a user action reports the count, not "empty".

    A ``needs_clarification`` event and a ``proposed`` (costed-but-unconfirmed) food
    item on the same day → ``uncounted_entries == 2`` with ``has_intake == false``
    and zeroed ``intake`` — the entries exist but count toward nothing. The
    single-day and range reads report the same value.
    """

    user_id, auth = _register(client, "uncounted-only@example.com")
    _set_timezone(client, user_id, auth, "UTC")
    at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

    # A needs_clarification event (counted as an event; it has no committed items).
    _seed_completed_event(
        db_engine, user_id, created_at=at, status=LogEventStatus.NEEDS_CLARIFICATION
    )
    # A proposed food item on a completed event (excluded from intake by construction).
    completed_event = _seed_completed_event(db_engine, user_id, created_at=at)
    _seed_food_item(
        db_engine,
        user_id,
        completed_event,
        calories=250.0,
        item_status=DerivedItemStatus.PROPOSED,
    )

    single = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-03-10"},
    )
    assert single.status_code == 200
    body = single.json()
    assert body["uncounted_entries"] == 2
    assert body["has_intake"] is False
    assert body["intake"] == {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}

    ranged = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-03-09", "to": "2026-03-11"},
    )
    assert ranged.status_code == 200
    by_date = {row["date"]: row for row in ranged.json()}
    assert by_date["2026-03-10"]["uncounted_entries"] == 2
    assert by_date["2026-03-10"]["has_intake"] is False
    # Surrounding days with nothing logged report 0.
    assert by_date["2026-03-09"]["uncounted_entries"] == 0
    assert by_date["2026-03-11"]["uncounted_entries"] == 0


def test_finalized_only_day_reports_zero_uncounted(client: TestClient, db_engine: Engine) -> None:
    """A day with only finalized entries reports ``uncounted_entries == 0``."""

    user_id, auth = _register(client, "finalized-uncounted@example.com")
    today = datetime.now(UTC).date()
    event_id = _seed_completed_event(db_engine, user_id)
    _seed_food_item(db_engine, user_id, event_id, calories=300.0)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["uncounted_entries"] == 0
    assert body["has_intake"] is True


def test_empty_day_reports_zero_uncounted(client: TestClient, db_engine: Engine) -> None:
    """A genuinely empty day reports ``uncounted_entries == 0`` and ``has_intake == false``.

    Still distinguishable from an uncounted-only day: both zero ``intake`` and read
    ``has_intake == false``, but the empty day's count is ``0`` where the
    uncounted-only day's is non-zero.
    """

    user_id, auth = _register(client, "empty-uncounted@example.com")
    empty_day = date(2025, 8, 1)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(empty_day)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["uncounted_entries"] == 0
    assert body["has_intake"] is False


def test_pending_processing_failed_events_do_not_increment_uncounted(
    client: TestClient, db_engine: Engine
) -> None:
    """In-flight (``pending`` / ``processing``) and ``failed`` events never count.

    Only entries the user must act on to make them count (``needs_clarification`` /
    ``proposed``) increment the total; the estimator's in-flight and retry states do
    not.
    """

    user_id, auth = _register(client, "excluded-uncounted@example.com")
    today = datetime.now(UTC).date()

    for excluded_status in (
        LogEventStatus.PENDING,
        LogEventStatus.PROCESSING,
        LogEventStatus.FAILED,
    ):
        evt_id = _seed_completed_event(db_engine, user_id, status=excluded_status)
        # Even an item on the excluded event must not leak into the count.
        _seed_food_item(db_engine, user_id, evt_id, calories=500.0)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )

    assert resp.status_code == 200
    assert resp.json()["uncounted_entries"] == 0


def test_range_uncounted_per_day_density(client: TestClient, db_engine: Engine) -> None:
    """A multi-day range returns ``uncounted_entries`` on every day with per-day values."""

    user_id, auth = _register(client, "range-uncounted@example.com")
    _set_timezone(client, user_id, auth, "UTC")

    # 2026-09-01: one needs_clarification event. 2026-09-02: nothing. 2026-09-03: two
    # proposed food items on one completed event + one needs_clarification event = 3.
    _seed_completed_event(
        db_engine,
        user_id,
        created_at=datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC),
        status=LogEventStatus.NEEDS_CLARIFICATION,
    )
    d3_completed = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 9, 3, 8, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, user_id, d3_completed, item_status=DerivedItemStatus.PROPOSED)
    _seed_food_item(db_engine, user_id, d3_completed, item_status=DerivedItemStatus.PROPOSED)
    _seed_completed_event(
        db_engine,
        user_id,
        created_at=datetime(2026, 9, 3, 9, 0, 0, tzinfo=UTC),
        status=LogEventStatus.NEEDS_CLARIFICATION,
    )

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-09-01", "to": "2026-09-03"},
    )

    assert resp.status_code == 200
    by_date = {row["date"]: row for row in resp.json()}
    # The field is present (dense) on every calendar day.
    assert all("uncounted_entries" in row for row in resp.json())
    assert by_date["2026-09-01"]["uncounted_entries"] == 1
    assert by_date["2026-09-02"]["uncounted_entries"] == 0
    assert by_date["2026-09-03"]["uncounted_entries"] == 3


def test_uncounted_entries_are_owner_scoped(client: TestClient, db_engine: Engine) -> None:
    """Another user's uncounted entries never leak into the count."""

    alice_id, alice_auth = _register(client, "alice-uncounted@example.com")
    bob_id, _bob_auth = _register(client, "bob-uncounted@example.com")
    at = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)

    # Bob has uncounted entries on the day; Alice has none.
    _seed_completed_event(
        db_engine, bob_id, created_at=at, status=LogEventStatus.NEEDS_CLARIFICATION
    )
    bob_completed = _seed_completed_event(db_engine, bob_id, created_at=at)
    _seed_food_item(db_engine, bob_id, bob_completed, item_status=DerivedItemStatus.PROPOSED)

    resp = client.get(
        f"/api/users/{alice_id}/daily-summary",
        headers={"Authorization": alice_auth},
        params={"day": "2026-10-05"},
    )

    assert resp.status_code == 200
    # Alice sees zero — Bob's uncounted entries do not cross the owner boundary.
    assert resp.json()["uncounted_entries"] == 0


def test_range_timezone_boundary_attribution(client: TestClient, db_engine: Engine) -> None:
    """Items near local midnight land in the correct calendar day within the range.

    Scenario: user timezone is "America/New_York" (UTC-5 standard time).
    - Event A: UTC 2026-02-10 04:59 → local 2026-02-09 23:59 → NY day 2026-02-09
    - Event B: UTC 2026-02-10 05:00 → local 2026-02-10 00:00 → NY day 2026-02-10

    A range request for NY days 2026-02-08 through 2026-02-11 must bucket event A's
    item into 2026-02-09 and event B's item into 2026-02-10 — identical attribution to
    the single-day endpoint for the same days.
    """

    user_id, auth = _register(client, "range-tz-boundary@example.com")
    _set_timezone(client, user_id, auth, "America/New_York")

    event_a_id = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 2, 10, 4, 59, 0, tzinfo=UTC)
    )
    event_b_id = _seed_completed_event(
        db_engine, user_id, created_at=datetime(2026, 2, 10, 5, 0, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, user_id, event_a_id, calories=111.0)
    _seed_food_item(db_engine, user_id, event_b_id, calories=222.0)

    resp = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        headers={"Authorization": auth},
        params={"from": "2026-02-08", "to": "2026-02-11"},
    )

    assert resp.status_code == 200
    by_date = {row["date"]: row for row in resp.json()}

    # Event A (04:59 UTC = 23:59 EST) → NY day 2026-02-09
    assert by_date["2026-02-09"]["intake"]["calories"] == 111.0
    # Event B (05:00 UTC = 00:00 EST) → NY day 2026-02-10
    assert by_date["2026-02-10"]["intake"]["calories"] == 222.0
    # Surrounding empty days are present and zeroed
    assert by_date["2026-02-08"]["intake"]["calories"] == 0.0
    assert by_date["2026-02-11"]["intake"]["calories"] == 0.0

    # Verify attribution is consistent with the single-day endpoint for the same days
    single_09 = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-02-09"},
    )
    single_10 = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-02-10"},
    )
    assert single_09.json()["intake"]["calories"] == by_date["2026-02-09"]["intake"]["calories"]
    assert single_10.json()["intake"]["calories"] == by_date["2026-02-10"]["intake"]["calories"]
