"""Goal + target-reveal endpoint tests (FTY-106).

Covers the contract end to end:

- the pure, deterministic pace→trajectory derivation and the evidence-based pace
  bands (no preset above ~1%/wk loss; gain gentler; steady is the default);
- creating a goal from direction + pace persists the derived trajectory, computes
  the target via the existing calculator, and returns it with provenance + clamp;
- start-weight / start-date defaulting, active-goal replacement, the clamp case,
  fail-closed authorization, the incomplete-profile error, and the daily-summary
  round-trip;
- a log spy asserts no weight / RMR / TDEE / target value is ever logged.

Both the service surface and the owner-scoped HTTP endpoint are exercised.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import GoalDirection, MetabolicFormula, PacePreset
from app.models.identity import User, UserProfile
from app.models.targets import Goal
from app.schemas.goals import GoalTargetRequest
from app.services.goals import (
    DEFAULT_PACE,
    PACE_WEEKLY_FRACTION,
    PLANNING_HORIZON_WEEKS,
    InvalidPace,
    build_goal_target_response,
    create_goal_with_target,
    derive_trajectory,
    direction_of,
    read_active_goal,
)
from app.services.targets import (
    GoalForbidden,
    IncompleteProfileError,
    compute_daily_target,
)


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    db_session = factory()
    try:
        yield db_session
    finally:
        db_session.close()


def _make_user_with_profile(
    session: Session,
    *,
    formula: MetabolicFormula = MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5,
    height_m: float | None = 1.80,
    weight_kg: float | None = 80.0,
    birth_year: int | None = 1996,
) -> User:
    user = User()
    session.add(user)
    session.flush()
    session.add(
        UserProfile(
            user_id=user.id,
            height_m=height_m,
            weight_kg=weight_kg,
            birth_year=birth_year,
            metabolic_formula=formula,
            timezone="UTC",
        )
    )
    session.commit()
    return user


# ---------------------------------------------------------------------------
# Pure pace→trajectory derivation + evidence-based bands
# ---------------------------------------------------------------------------


def test_loss_steady_derives_expected_trajectory() -> None:
    start = date(2026, 1, 1)
    traj = derive_trajectory(GoalDirection.LOSS, PacePreset.STEADY, 80.0, start)

    # 0.5%/wk of 80 kg = 0.4 kg/wk × 12 wk = 4.8 kg lost.
    assert traj.start_weight_kg == 80.0
    assert traj.target_weight_kg == pytest.approx(75.2)
    assert traj.start_date == start
    assert traj.target_date == start + timedelta(weeks=PLANNING_HORIZON_WEEKS)
    assert traj.target_date > traj.start_date


def test_gain_steady_adds_weight_over_horizon() -> None:
    traj = derive_trajectory(GoalDirection.GAIN, PacePreset.STEADY, 80.0, date(2026, 1, 1))
    # 0.25%/wk of 80 = 0.2 kg/wk × 12 = 2.4 kg gained.
    assert traj.target_weight_kg == pytest.approx(82.4)


def test_maintain_ignores_pace_and_holds_weight() -> None:
    # Even with a pace supplied, maintain yields target == start.
    traj = derive_trajectory(GoalDirection.MAINTAIN, PacePreset.FASTER, 80.0, date(2026, 1, 1))
    assert traj.target_weight_kg == traj.start_weight_kg == 80.0


def test_derivation_is_deterministic() -> None:
    args = (GoalDirection.LOSS, PacePreset.GENTLE, 73.5, date(2026, 3, 4))
    assert derive_trajectory(*args) == derive_trajectory(*args)


def test_faster_is_loss_only() -> None:
    with pytest.raises(InvalidPace):
        derive_trajectory(GoalDirection.GAIN, PacePreset.FASTER, 80.0, date(2026, 1, 1))


def test_pace_bands_are_evidence_based() -> None:
    loss = PACE_WEEKLY_FRACTION[GoalDirection.LOSS]
    gain = PACE_WEEKLY_FRACTION[GoalDirection.GAIN]

    # Steady (~0.5%/wk) is the documented default for loss.
    assert DEFAULT_PACE is PacePreset.STEADY
    assert loss[PacePreset.STEADY] == pytest.approx(0.005)
    # No loss preset exceeds ~1%/wk.
    assert max(loss.values()) <= 0.01
    # Gain is gentler than loss at every shared preset, and has no "faster".
    assert PacePreset.FASTER not in gain
    for preset, fraction in gain.items():
        assert fraction < loss[preset]


# ---------------------------------------------------------------------------
# Service: create goal → compute + persist target
# ---------------------------------------------------------------------------


def test_create_goal_persists_trajectory_and_computes_target(session: Session) -> None:
    user = _make_user_with_profile(session)
    request = GoalTargetRequest(
        direction=GoalDirection.LOSS, pace=PacePreset.STEADY, start_date=date(2026, 1, 1)
    )

    goal, target = create_goal_with_target(session, user.id, user, request)

    # Trajectory matches the pure derivation and defaults start weight from profile.
    assert goal.is_active is True
    assert goal.start_weight_kg == 80.0
    assert goal.target_weight_kg == pytest.approx(75.2)
    assert goal.target_date == date(2026, 1, 1) + timedelta(weeks=12)
    # The target is the calculator's output for this exact goal (no re-derivation).
    direct = compute_daily_target(session, user.id, goal.id, user, for_date=target.for_date)
    assert target.daily_calorie_target_kcal == direct.daily_calorie_target_kcal
    assert target.rmr_kcal == direct.rmr_kcal
    assert target.tdee_kcal == direct.tdee_kcal


def test_maintain_target_equals_tdee(session: Session) -> None:
    user = _make_user_with_profile(session)
    request = GoalTargetRequest(direction=GoalDirection.MAINTAIN)

    goal, target = create_goal_with_target(session, user.id, user, request)

    assert goal.target_weight_kg == goal.start_weight_kg
    # wT == w0 → the daily target is exactly TDEE (rounded), per the calculator.
    assert target.daily_calorie_target_kcal == round(target.tdee_kcal)
    assert target.clamped is False


def test_start_weight_defaults_to_profile_weight(session: Session) -> None:
    user = _make_user_with_profile(session, weight_kg=90.0)
    goal, _ = create_goal_with_target(
        session, user.id, user, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
    )
    assert goal.start_weight_kg == 90.0


def test_explicit_start_weight_pins_the_plan(session: Session) -> None:
    user = _make_user_with_profile(session, weight_kg=90.0)
    goal, _ = create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(
            direction=GoalDirection.LOSS, pace=PacePreset.STEADY, start_weight_kg=100.0
        ),
    )
    assert goal.start_weight_kg == 100.0
    assert goal.target_weight_kg == pytest.approx(94.0)  # 100 - 0.005*100*12


def test_start_date_defaults_to_today_in_profile_timezone(session: Session) -> None:
    user = _make_user_with_profile(session)  # timezone UTC
    goal, target = create_goal_with_target(
        session, user.id, user, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
    )
    today = datetime.now(ZoneInfo("UTC")).date()
    assert goal.start_date == today
    assert target.for_date == today


def test_create_replaces_prior_active_goal(session: Session) -> None:
    user = _make_user_with_profile(session)
    first, _ = create_goal_with_target(
        session, user.id, user, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
    )
    second, _ = create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(direction=GoalDirection.LOSS, pace=PacePreset.GENTLE),
    )

    session.refresh(first)
    assert first.is_active is False
    assert second.is_active is True
    active = session.scalars(
        select(Goal).where(Goal.user_id == user.id, Goal.is_active.is_(True))
    ).all()
    assert len(active) == 1


def test_create_is_deterministic_across_calls(session: Session) -> None:
    user = _make_user_with_profile(session)
    request = GoalTargetRequest(
        direction=GoalDirection.LOSS, pace=PacePreset.STEADY, start_date=date(2026, 1, 1)
    )

    goal_a, target_a = create_goal_with_target(session, user.id, user, request)
    goal_b, target_b = create_goal_with_target(session, user.id, user, request)

    # Same inputs → identical persisted trajectory + target (modulo ids/timestamps).
    assert goal_a.start_weight_kg == goal_b.start_weight_kg
    assert goal_a.target_weight_kg == goal_b.target_weight_kg
    assert goal_a.target_date == goal_b.target_date
    assert target_a.daily_calorie_target_kcal == target_b.daily_calorie_target_kcal


# ---------------------------------------------------------------------------
# Active-goal direction read (FTY-189)
# ---------------------------------------------------------------------------


def test_direction_of_recovers_direction_from_trajectory(session: Session) -> None:
    user = _make_user_with_profile(session)
    loss, _ = create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(direction=GoalDirection.LOSS, pace=PacePreset.STEADY),
    )
    assert direction_of(loss) is GoalDirection.LOSS

    gain, _ = create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(direction=GoalDirection.GAIN, pace=PacePreset.STEADY),
    )
    assert direction_of(gain) is GoalDirection.GAIN

    maintain, _ = create_goal_with_target(
        session, user.id, user, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
    )
    assert direction_of(maintain) is GoalDirection.MAINTAIN


def test_read_active_goal_returns_the_active_goal(session: Session) -> None:
    user = _make_user_with_profile(session)
    created, _ = create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(direction=GoalDirection.GAIN, pace=PacePreset.GENTLE),
    )
    active = read_active_goal(session, user.id, user)
    assert active is not None
    assert active.id == created.id
    assert direction_of(active) is GoalDirection.GAIN


def test_read_active_goal_is_none_when_no_goal(session: Session) -> None:
    user = _make_user_with_profile(session)
    assert read_active_goal(session, user.id, user) is None


def test_read_active_goal_follows_the_latest_replacement(session: Session) -> None:
    # After a replace, the read reflects the *new* active goal's direction only.
    user = _make_user_with_profile(session)
    create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(direction=GoalDirection.LOSS, pace=PacePreset.STEADY),
    )
    create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(direction=GoalDirection.GAIN, pace=PacePreset.STEADY),
    )
    active = read_active_goal(session, user.id, user)
    assert active is not None
    assert direction_of(active) is GoalDirection.GAIN


def test_read_active_goal_cross_user_fails_closed(session: Session) -> None:
    owner = _make_user_with_profile(session)
    attacker = _make_user_with_profile(session)
    create_goal_with_target(
        session, owner.id, owner, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
    )
    with pytest.raises(GoalForbidden):
        read_active_goal(session, owner.id, attacker)


# ---------------------------------------------------------------------------
# Clamp surfacing
# ---------------------------------------------------------------------------


def test_over_aggressive_plan_is_clamped_to_floor(session: Session) -> None:
    # A small person on the faster (1%/wk) loss preset demands a sub-floor target.
    user = _make_user_with_profile(
        session, height_m=1.55, weight_kg=50.0, formula=MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5
    )
    goal, target = create_goal_with_target(
        session,
        user.id,
        user,
        GoalTargetRequest(direction=GoalDirection.LOSS, pace=PacePreset.FASTER),
    )

    assert target.clamped is True
    response = build_goal_target_response(goal, target, GoalDirection.LOSS)
    assert response.clamp.clamped is True
    assert response.clamp.reason == "clamped_to_floor"
    # The returned number is the safe floor (1500 for the +5 variant), not lower.
    assert response.target.calories == 1500


def test_provenance_marks_target_derived(session: Session) -> None:
    user = _make_user_with_profile(session)
    goal, target = create_goal_with_target(
        session, user.id, user, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
    )
    response = build_goal_target_response(goal, target, GoalDirection.MAINTAIN)
    assert response.provenance.source == "derived"
    assert response.provenance.basis == "goal_and_metrics"
    assert response.clamp.reason is None


# ---------------------------------------------------------------------------
# Authorization + incomplete profile (fail closed)
# ---------------------------------------------------------------------------


def test_cross_user_create_fails_closed(session: Session) -> None:
    owner = _make_user_with_profile(session)
    attacker = _make_user_with_profile(session)
    with pytest.raises(GoalForbidden):
        create_goal_with_target(
            session, owner.id, attacker, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
        )


def test_incomplete_profile_is_rejected_without_creating_a_goal(session: Session) -> None:
    # Missing height/birth_year/formula variant: target cannot be computed.
    user = _make_user_with_profile(
        session, height_m=None, birth_year=None, formula=MetabolicFormula.MIFFLIN_ST_JEOR
    )
    with pytest.raises(IncompleteProfileError):
        create_goal_with_target(
            session, user.id, user, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
        )
    # No goal was persisted by the failed attempt.
    goals = session.scalars(select(Goal).where(Goal.user_id == user.id)).all()
    assert goals == []


def test_no_resolvable_weight_is_rejected(session: Session) -> None:
    user = _make_user_with_profile(session, weight_kg=None)
    with pytest.raises(IncompleteProfileError):
        # No profile weight and none supplied.
        create_goal_with_target(
            session, user.id, user, GoalTargetRequest(direction=GoalDirection.MAINTAIN)
        )


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str) -> tuple[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _complete_profile(client: TestClient, user_id: str, auth: str) -> None:
    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={
            "height_m": 1.80,
            "weight_kg": 80.0,
            "birth_year": 1996,
            "metabolic_formula": "mifflin_st_jeor_plus5",
            "timezone": "UTC",
        },
    )
    assert resp.status_code == 200


def test_api_create_goal_reveals_target(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-api@example.com")
    _complete_profile(client, user_id, auth)

    resp = client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "loss", "pace": "steady", "start_date": "2026-01-01"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["goal"]["start_weight_kg"] == 80.0
    assert body["goal"]["target_weight_kg"] == pytest.approx(75.2)
    assert body["goal"]["is_active"] is True
    assert body["target"]["calories"] > 0
    assert body["target"]["direction"] == "loss"
    assert body["provenance"] == {"source": "derived", "basis": "goal_and_metrics"}
    assert body["clamp"]["clamped"] is False
    assert body["clamp"]["reason"] is None


def test_api_create_goal_populates_daily_summary_target(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-summary@example.com")
    _complete_profile(client, user_id, auth)
    today = datetime.now(ZoneInfo("UTC")).date()

    # Before: daily-summary has no stored target for today.
    before = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )
    assert before.status_code == 200
    assert before.json()["target"] is None

    created = client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "loss", "pace": "steady"},
    )
    revealed = created.json()["target"]["calories"]

    # After: the same day's summary now returns the revealed number.
    after = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": str(today)},
    )
    assert after.json()["target"]["calories"]["effective"] == revealed


def test_api_missing_pace_for_loss_is_422(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-nopace@example.com")
    _complete_profile(client, user_id, auth)
    resp = client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "loss"},
    )
    assert resp.status_code == 422


def test_api_faster_gain_is_422(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-fastergain@example.com")
    _complete_profile(client, user_id, auth)
    resp = client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "gain", "pace": "faster"},
    )
    assert resp.status_code == 422


def test_api_free_form_rate_is_rejected(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-freeform@example.com")
    _complete_profile(client, user_id, auth)
    resp = client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "loss", "pace": 0.02},
    )
    assert resp.status_code == 422


def test_api_incomplete_profile_is_409(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-incomplete@example.com")
    # Profile created at registration but not yet captured (no height/weight/variant).
    resp = client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "maintain"},
    )
    assert resp.status_code == 409


def test_api_cross_user_create_fails_closed_404(client: TestClient) -> None:
    owner_id, owner_auth = _register(client, "goal-owner@example.com")
    _complete_profile(client, owner_id, owner_auth)
    _, attacker_auth = _register(client, "goal-attacker@example.com")

    resp = client.post(
        f"/api/users/{owner_id}/goal",
        headers={"Authorization": attacker_auth},
        json={"direction": "maintain"},
    )
    assert resp.status_code == 404


def test_api_read_active_goal_direction(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-read@example.com")
    _complete_profile(client, user_id, auth)
    client.post(
        f"/api/users/{user_id}/goal",
        headers={"Authorization": auth},
        json={"direction": "gain", "pace": "steady"},
    )

    resp = client.get(f"/api/users/{user_id}/goal", headers={"Authorization": auth})
    assert resp.status_code == 200
    assert resp.json() == {"direction": "gain"}


def test_api_read_active_goal_direction_404_when_no_goal(client: TestClient) -> None:
    user_id, auth = _register(client, "goal-read-none@example.com")
    _complete_profile(client, user_id, auth)
    # Profile complete but no goal created yet — fail closed, no existence oracle.
    resp = client.get(f"/api/users/{user_id}/goal", headers={"Authorization": auth})
    assert resp.status_code == 404


def test_api_read_active_goal_direction_cross_user_404(client: TestClient) -> None:
    owner_id, owner_auth = _register(client, "goal-read-owner@example.com")
    _complete_profile(client, owner_id, owner_auth)
    client.post(
        f"/api/users/{owner_id}/goal",
        headers={"Authorization": owner_auth},
        json={"direction": "loss", "pace": "steady"},
    )
    _, attacker_auth = _register(client, "goal-read-attacker@example.com")

    resp = client.get(f"/api/users/{owner_id}/goal", headers={"Authorization": attacker_auth})
    assert resp.status_code == 404


def test_api_route_is_registered(client: TestClient) -> None:
    # The route exists: an unauthenticated/malformed call is rejected by auth (401)
    # or body validation (422) — never a 404-by-absence.
    resp = client.post("/api/users/00000000-0000-0000-0000-000000000000/goal", json={})
    assert resp.status_code in (401, 422)


def test_no_sensitive_numbers_are_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, auth = _register(client, "goal-nolog@example.com")
    _complete_profile(client, user_id, auth)

    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            f"/api/users/{user_id}/goal",
            headers={"Authorization": auth},
            json={"direction": "loss", "pace": "steady"},
        )
    assert resp.status_code == 201
    body = resp.json()
    sensitive = {
        str(body["target"]["calories"]),
        str(body["target"]["rmr_kcal"]),
        str(body["target"]["tdee_kcal"]),
        str(body["goal"]["start_weight_kg"]),
        str(body["goal"]["target_weight_kg"]),
    }
    logged = caplog.text
    for value in sensitive:
        assert value not in logged
