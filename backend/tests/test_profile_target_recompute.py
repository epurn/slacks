"""A body-metric profile edit recomputes the active goal's daily target (FTY-467).

The contract already documented "editing goal/pace/metrics recomputes the derived
columns in place"; the profile write never did it, so a corrected height or a switched
formula variant left the Today hero numbers — and the settings read-back that reveals
them — on the goal-creation-day snapshot. These tests pin the closed gap:

- a ``height_m`` / ``birth_year`` / ``metabolic_formula`` edit refreshes the current
  day's derived columns in place, and the target read returns the fresh numbers;
- an in-force user override survives that recompute untouched (``source: user``);
- a ``weight_kg`` / ``timezone`` / ``units_preference`` edit — and a re-submission of an
  unchanged metric — is a recompute **no-op**;
- no active goal covering today, and an edit that leaves the profile un-derivable, are
  silent no-ops: the profile write still succeeds (never ``409`` / ``500``);
- only the current day is touched — no past-day backfill;
- target numbers stay out of the logs.

The current-day resolution the recompute and the read share is frozen (``frozen_day``),
so "today" is deterministic: no real clock, no midnight-rollover flake. A Postgres-parity
guard exercises the same write path on the production engine.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import MetabolicFormula
from app.models.identity import User, UserProfile
from app.models.targets import DailyTarget, Goal
from app.schemas.profile import ProfileUpdateRequest
from app.schemas.targets import TargetOverrideRequest
from app.services import goals
from app.services.profile import update_profile
from app.services.targets import (
    build_target_read_model,
    compute_daily_target,
    get_active_target,
    resolution,
    set_target_override,
)
from tests.conftest import upgrade

#: The frozen "today". Inside the goal horizon below, and after the goal's creation day
#: so the past-day-immutability case has a real earlier row to protect.
FROZEN_DAY = date(2026, 2, 1)
GOAL_START = date(2026, 1, 1)
GOAL_END = date(2026, 4, 1)

#: A sentinel derived value poked onto a stored row: any recompute overwrites it with
#: the real derivation, so "still the sentinel" is proof that no recompute ran.
SENTINEL_RMR = 1.0


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    db_session = factory()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture(autouse=True)
def frozen_day(monkeypatch: pytest.MonkeyPatch) -> date:
    """Pin the current day the recompute, the target read, and goal creation resolve.

    Each reads the clock through its module's ``current_day`` binding, so freezing both
    makes "today" deterministic for the whole module: the recompute lands on exactly the
    row the read returns, with no dependence on the wall clock and no midnight flake.
    """

    def _frozen(session: Session, owner_id: uuid.UUID) -> date:
        return FROZEN_DAY

    monkeypatch.setattr(resolution, "current_day", _frozen)
    monkeypatch.setattr(goals, "current_day", _frozen)
    return FROZEN_DAY


def _make_user_with_profile(
    session: Session,
    *,
    height_m: float | None = 1.60,
    birth_year: int | None = 1996,
    formula: MetabolicFormula = MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5,
) -> User:
    user = User()
    session.add(user)
    session.flush()
    session.add(
        UserProfile(
            user_id=user.id,
            height_m=height_m,
            weight_kg=80.0,
            birth_year=birth_year,
            metabolic_formula=formula,
            timezone="UTC",
        )
    )
    session.commit()
    return user


def _make_goal(
    session: Session,
    user: User,
    *,
    start_date: date = GOAL_START,
    target_date: date = GOAL_END,
) -> Goal:
    goal = Goal(
        user_id=user.id,
        start_weight_kg=80.0,
        start_date=start_date,
        target_weight_kg=75.0,
        target_date=target_date,
    )
    session.add(goal)
    session.commit()
    return goal


def _rows(session: Session, user: User) -> list[DailyTarget]:
    return list(
        session.scalars(
            select(DailyTarget).where(DailyTarget.user_id == user.id).order_by(DailyTarget.for_date)
        ).all()
    )


def _poke_sentinel(session: Session, row: DailyTarget) -> None:
    """Mark a stored row so a recompute would be visible as an overwrite."""

    row.rmr_kcal = SENTINEL_RMR
    session.commit()


# ---------------------------------------------------------------------------
# A calculator-affecting metric edit refreshes the current day's derived columns
# ---------------------------------------------------------------------------


def test_height_edit_refreshes_the_current_day_derived_columns(session: Session) -> None:
    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user)
    before = compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    row_id, created_at = before.id, before.created_at
    stale = (
        before.rmr_kcal,
        before.tdee_kcal,
        before.daily_calorie_target_kcal,
        before.carbs_target_g,
    )

    update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    after = session.get(DailyTarget, row_id)
    assert after is not None
    # Refreshed *in place*: same row, not a second row for the same day.
    assert after.created_at == created_at
    assert len(_rows(session, user)) == 1
    # Mifflin-St Jeor: +0.15 m = +6.25 kcal/cm × 15 cm = +93.75 kcal RMR, ×1.2 TDEE.
    # RMR/TDEE persist rounded to 0.1 kcal, hence the 0.1 tolerance on the delta.
    assert after.rmr_kcal == pytest.approx(stale[0] + 93.75, abs=0.1)
    assert after.tdee_kcal == pytest.approx(stale[1] + 93.75 * 1.2, abs=0.1)
    assert after.daily_calorie_target_kcal > stale[2]
    assert after.carbs_target_g != stale[3]
    # The numbers are exactly what the calculator derives for the edited profile.
    fresh = compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    assert fresh.id == row_id
    assert after.daily_calorie_target_kcal == fresh.daily_calorie_target_kcal


def test_birth_year_edit_refreshes_the_current_day_derived_columns(session: Session) -> None:
    user = _make_user_with_profile(session, birth_year=1996)
    goal = _make_goal(session, user)
    before = compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    stale_rmr = before.rmr_kcal

    update_profile(session, user.id, user, ProfileUpdateRequest(birth_year=1976))

    session.refresh(before)
    # 20 years older: −5 kcal/yr of RMR.
    assert before.rmr_kcal == pytest.approx(stale_rmr - 100.0)


def test_formula_variant_edit_refreshes_the_current_day_derived_columns(
    session: Session,
) -> None:
    user = _make_user_with_profile(session, formula=MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5)
    goal = _make_goal(session, user)
    before = compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    stale_rmr = before.rmr_kcal
    stale_floor = before.assumptions["safety_floor_kcal"]

    update_profile(
        session,
        user.id,
        user,
        ProfileUpdateRequest(metabolic_formula=MetabolicFormula.MIFFLIN_ST_JEOR_MINUS_161),
    )

    session.refresh(before)
    # The variant swaps the sex-dependent additive constant: +5 → −161.
    assert before.rmr_kcal == pytest.approx(stale_rmr - 166.0)
    # The assumptions snapshot is refreshed too, so a later override validates against
    # the band the row was actually derived under (1500 → 1200 kcal floor).
    assert before.assumptions["safety_floor_kcal"] != stale_floor


def test_metric_edit_materialises_a_missing_current_day_row(session: Session) -> None:
    """The common case: the only stored row is the goal-creation day's."""

    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user)
    creation_day = compute_daily_target(session, user.id, goal.id, user, for_date=GOAL_START)

    update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    rows = _rows(session, user)
    assert [row.for_date for row in rows] == [GOAL_START, FROZEN_DAY]
    today = rows[1]
    assert today.rmr_kcal > creation_day.rmr_kcal


def test_metric_edit_is_visible_to_the_target_read(session: Session) -> None:
    """The read-back the mobile settings flow already performs now returns fresh numbers."""

    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user)
    compute_daily_target(session, user.id, goal.id, user, for_date=GOAL_START)
    stale = get_active_target(session, user.id, user).daily_calorie_target_kcal

    update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    read = get_active_target(session, user.id, user)
    assert read.for_date == FROZEN_DAY
    assert read.daily_calorie_target_kcal > stale
    assert build_target_read_model(read).calories.effective == read.daily_calorie_target_kcal
    assert goal.id == read.goal_id


# ---------------------------------------------------------------------------
# An in-force override survives the recompute
# ---------------------------------------------------------------------------


def test_in_force_override_survives_a_metric_edit(session: Session) -> None:
    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user)
    compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    overridden = set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1900, protein_target_g=140),
    )
    stale_derived = overridden.daily_calorie_target_kcal
    override_set_at = overridden.override_set_at

    update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    session.refresh(overridden)
    # Derived columns refreshed — a reset would now restore the *current* derivation.
    assert overridden.daily_calorie_target_kcal != stale_derived
    # The explicit user choice is untouched, stamp included.
    assert overridden.override_calorie_target_kcal == 1900
    assert overridden.override_protein_target_g == 140
    assert overridden.override_set_at == override_set_at
    # The read-model still reports the user's number as effective, with `user` source.
    read_model = build_target_read_model(overridden)
    assert read_model.calories.effective == 1900
    assert read_model.calories.source == "user"
    assert read_model.calories.derived == overridden.daily_calorie_target_kcal
    assert read_model.protein_g.effective == 140
    assert read_model.protein_g.source == "user"
    # Untouched macros stay derived, and were refreshed by the recompute.
    assert read_model.fat_g.source == "derived"


def test_override_carries_forward_when_the_recompute_materialises_today(
    session: Session,
) -> None:
    """A metric edit that creates today's row inherits the goal's in-force override."""

    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user)
    compute_daily_target(session, user.id, goal.id, user, for_date=GOAL_START)
    set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1900),
        for_date=GOAL_START,
    )

    update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    today = get_active_target(session, user.id, user)
    assert today.for_date == FROZEN_DAY
    assert today.override_calorie_target_kcal == 1900
    assert build_target_read_model(today).calories.source == "user"


# ---------------------------------------------------------------------------
# Non-triggering edits are recompute no-ops
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("weight_kg", 71.5),
        ("timezone", "America/New_York"),
        ("units_preference", "imperial"),
    ],
)
def test_non_calculator_field_edit_does_not_recompute(
    session: Session, field: str, value: object
) -> None:
    """Weight is a goal-snapshot input, not a calculator input; the rest are display."""

    user = _make_user_with_profile(session)
    goal = _make_goal(session, user)
    row = compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    row_id, created_at = row.id, row.created_at
    _poke_sentinel(session, row)

    profile = update_profile(
        session, user.id, user, ProfileUpdateRequest.model_validate({field: value})
    )

    assert getattr(profile, field) == value
    rows = _rows(session, user)
    assert [(r.id, r.created_at) for r in rows] == [(row_id, created_at)]
    # The sentinel survives: no recompute overwrote the derived columns.
    assert rows[0].rmr_kcal == SENTINEL_RMR


def test_unchanged_metric_resubmission_does_not_recompute(session: Session) -> None:
    """A settings form re-submitting the height it just read costs no pointless write."""

    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user)
    row = compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    _poke_sentinel(session, row)

    update_profile(
        session,
        user.id,
        user,
        ProfileUpdateRequest(
            height_m=1.60,
            birth_year=1996,
            metabolic_formula=MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5,
        ),
    )

    session.refresh(row)
    assert row.rmr_kcal == SENTINEL_RMR


# ---------------------------------------------------------------------------
# Silent no-ops: no goal, and an edit that leaves the profile un-derivable
# ---------------------------------------------------------------------------


def test_metric_edit_without_an_active_goal_succeeds_and_stores_no_target(
    session: Session,
) -> None:
    user = _make_user_with_profile(session, height_m=1.60)

    profile = update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    assert profile.height_m == 1.75
    assert _rows(session, user) == []


def test_metric_edit_with_a_goal_outside_its_horizon_is_a_no_op(session: Session) -> None:
    """The goal's planned trajectory ended before today: nothing to recompute."""

    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user, start_date=date(2025, 10, 1), target_date=date(2025, 12, 31))
    row = compute_daily_target(session, user.id, goal.id, user, for_date=date(2025, 10, 1))
    _poke_sentinel(session, row)

    update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    rows = _rows(session, user)
    assert [r.for_date for r in rows] == [date(2025, 10, 1)]
    assert rows[0].rmr_kcal == SENTINEL_RMR


@pytest.mark.parametrize(
    "update",
    [
        ProfileUpdateRequest(height_m=None),
        ProfileUpdateRequest(birth_year=None),
        ProfileUpdateRequest(metabolic_formula=MetabolicFormula.MIFFLIN_ST_JEOR),
        # The profile DTO admits birth years the calculator's [13, 120] age band
        # refuses; an un-derivable age is the same silent no-op, never a 500.
        ProfileUpdateRequest(birth_year=1900),
    ],
)
def test_edit_that_leaves_the_profile_underivable_still_writes_the_profile(
    session: Session, update: ProfileUpdateRequest
) -> None:
    user = _make_user_with_profile(session)
    goal = _make_goal(session, user)
    row = compute_daily_target(session, user.id, goal.id, user, for_date=FROZEN_DAY)
    _poke_sentinel(session, row)

    # No IncompleteProfileError / ValidationError escapes to the caller.
    profile = update_profile(session, user.id, user, update)

    changed = update.model_dump(exclude_unset=True)
    for field, value in changed.items():
        assert getattr(profile, field) == value
    session.refresh(row)
    assert row.rmr_kcal == SENTINEL_RMR


# ---------------------------------------------------------------------------
# No past-day backfill
# ---------------------------------------------------------------------------


def test_past_day_rows_are_not_backfilled(session: Session) -> None:
    user = _make_user_with_profile(session, height_m=1.60)
    goal = _make_goal(session, user)
    past = compute_daily_target(session, user.id, goal.id, user, for_date=GOAL_START)
    mid = compute_daily_target(session, user.id, goal.id, user, for_date=date(2026, 1, 15))
    past_rmr, mid_rmr = past.rmr_kcal, mid.rmr_kcal

    update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

    session.refresh(past)
    session.refresh(mid)
    assert past.rmr_kcal == past_rmr
    assert mid.rmr_kcal == mid_rmr
    today = get_active_target(session, user.id, user)
    assert today.for_date == FROZEN_DAY
    assert today.rmr_kcal > past_rmr


# ---------------------------------------------------------------------------
# HTTP: the profile PUT + target read round-trip the mobile settings flow performs
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str) -> tuple[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _onboard(client: TestClient, user_id: str, auth: str, *, height_m: float) -> None:
    profile = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={
            "height_m": height_m,
            "weight_kg": 80.0,
            "birth_year": 1996,
            "metabolic_formula": "mifflin_st_jeor_plus5",
            "timezone": "UTC",
        },
    )
    assert profile.status_code == 200
    goal = client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "loss", "pace": "steady", "start_date": str(GOAL_START)},
    )
    assert goal.status_code == 201


def test_api_profile_put_then_target_get_reveals_fresh_numbers(client: TestClient) -> None:
    user_id, auth = _register(client, "recompute-api@example.com")
    _onboard(client, user_id, auth, height_m=1.60)

    stale = client.get(f"/api/users/{user_id}/target", headers={"Authorization": auth})
    assert stale.status_code == 200
    stale_calories = stale.json()["calories"]["effective"]

    written = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"height_m": 1.75},
    )
    assert written.status_code == 200

    fresh = client.get(f"/api/users/{user_id}/target", headers={"Authorization": auth})
    assert fresh.status_code == 200
    body = fresh.json()
    assert body["calories"]["effective"] > stale_calories
    assert body["calories"]["source"] == "derived"
    assert body["calories"]["derived"] == body["calories"]["effective"]


def test_api_metric_edit_that_leaves_the_profile_incomplete_is_still_200(
    client: TestClient,
) -> None:
    """The PUT must not become a 409/500 because the edit made the profile un-derivable."""

    user_id, auth = _register(client, "recompute-incomplete@example.com")
    _onboard(client, user_id, auth, height_m=1.60)

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"height_m": None},
    )

    assert resp.status_code == 200
    assert resp.json()["height_m"] is None


def test_api_cross_user_metric_edit_still_fails_closed(client: TestClient) -> None:
    """The recompute runs strictly for the authenticated owner: authorization unchanged."""

    owner_id, owner_auth = _register(client, "recompute-owner@example.com")
    _onboard(client, owner_id, owner_auth, height_m=1.60)
    before = client.get(f"/api/users/{owner_id}/target", headers={"Authorization": owner_auth})
    _, attacker_auth = _register(client, "recompute-attacker@example.com")

    resp = client.put(
        f"/api/users/{owner_id}/profile",
        headers={"Authorization": attacker_auth},
        json={"height_m": 1.75},
    )

    assert resp.status_code == 404
    after = client.get(f"/api/users/{owner_id}/target", headers={"Authorization": owner_auth})
    assert after.json() == before.json()


def test_recompute_logs_no_target_numbers(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, auth = _register(client, "recompute-nolog@example.com")
    _onboard(client, user_id, auth, height_m=1.60)

    with caplog.at_level(logging.DEBUG):
        resp = client.put(
            f"/api/users/{user_id}/profile",
            headers={"Authorization": auth},
            json={"height_m": 1.75},
        )
    assert resp.status_code == 200

    fresh = client.get(f"/api/users/{user_id}/target", headers={"Authorization": auth}).json()
    logged = caplog.text
    assert str(fresh["calories"]["derived"]) not in logged
    assert str(fresh["calories"]["effective"]) not in logged


# ---------------------------------------------------------------------------
# Postgres parity: the recompute is a real write reachable from the profile PUT
# ---------------------------------------------------------------------------


def test_metric_edit_recompute_round_trips_on_postgres(pg_engine: Engine) -> None:
    """Exercise the metric-edit → recompute write on the production engine.

    The upsert/commit ordering and the ``carry_forward_override`` lookup that the
    recompute inherits are DB behaviour, so per ``testing-standards.md`` they are proven
    against Postgres, not only SQLite. Skips when ``SLACKS_TEST_DATABASE_URL`` is unset.
    """

    upgrade(pg_engine, "head")
    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = _make_user_with_profile(session, height_m=1.60)
        goal = _make_goal(session, user)
        compute_daily_target(session, user.id, goal.id, user, for_date=GOAL_START)
        set_target_override(
            session,
            user.id,
            user,
            TargetOverrideRequest(calorie_target_kcal=1900),
            for_date=GOAL_START,
        )
        stale = get_active_target(session, user.id, user, for_date=GOAL_START)
        stale_derived = stale.daily_calorie_target_kcal

        update_profile(session, user.id, user, ProfileUpdateRequest(height_m=1.75))

        today = get_active_target(session, user.id, user)
        assert today.for_date == FROZEN_DAY
        assert today.daily_calorie_target_kcal > stale_derived
        # The in-force override was carried onto the newly materialised row.
        assert today.override_calorie_target_kcal == 1900
        assert build_target_read_model(today).calories.source == "user"
