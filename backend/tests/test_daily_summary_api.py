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
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
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
) -> None:
    """Insert an active goal + daily_target for ``for_date``.

    Persists the derived macro columns (FTY-094/FTY-095) so the NOT NULL schema is
    satisfied; an optional calorie override exercises the read-model provenance.
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
            inputs={},
            assumptions={},
        )
        session.add(target)
        session.commit()


# ---------------------------------------------------------------------------
# Aggregation: correct separated totals
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Finalized-state filtering
# ---------------------------------------------------------------------------


def test_non_completed_events_are_excluded(client: TestClient, db_engine: Engine) -> None:
    """Items on pending/processing/failed/needs_clarification events are not counted."""

    user_id, auth = _register(client, "statuses@example.com")
    today = datetime.now(UTC).date()

    for non_final_status in (
        LogEventStatus.PENDING,
        LogEventStatus.PROCESSING,
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
    # No completed events, so totals are zero
    assert body["intake"]["calories"] == 0.0
    assert body["exercise"]["active_calories"] == 0.0


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
