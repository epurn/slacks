"""Target manual-override tests (FTY-095).

Covers the override lifecycle end to end:

- set persists the override and the read-model reports ``source: user`` while still
  reporting the derived value (calorie + macros, independently);
- reset clears the targeted override(s) back to ``NULL`` → ``source: derived``;
- a derived recompute updates the derived columns but leaves the override in force,
  and a later reset restores the *newly* derived value;
- an out-of-band override is rejected (no clamp) and nothing is persisted;
- every set/reset path is object-level authorized and fails closed.

Both the service surface and the owner-scoped HTTP endpoint are exercised. Target
numbers are sensitive body data — the tests assert behaviour, never log values.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import MetabolicFormula, OverridableTarget
from app.models.identity import User, UserProfile
from app.models.targets import DailyTarget, Goal
from app.schemas.targets import TargetOverrideRequest
from app.services.targets import (
    GoalForbidden,
    OverrideOutOfBand,
    TargetNotFound,
    _resolve_active_target_row,
    build_target_read_model,
    compute_daily_target,
    get_active_target,
    reset_target_override,
    set_target_override,
)

_FOR_DATE = date(2026, 1, 1)


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
) -> User:
    user = User()
    session.add(user)
    session.flush()
    session.add(
        UserProfile(
            user_id=user.id,
            height_m=1.80,
            weight_kg=80.0,
            birth_year=1996,
            metabolic_formula=formula,
        )
    )
    session.commit()
    return user


def _make_goal(session: Session, user: User, *, target_weight_kg: float = 75.0) -> Goal:
    goal = Goal(
        user_id=user.id,
        start_weight_kg=80.0,
        start_date=date(2026, 1, 1),
        target_weight_kg=target_weight_kg,
        target_date=date(2026, 4, 1),
    )
    session.add(goal)
    session.commit()
    return goal


def _seed_target(session: Session, user: User) -> tuple[Goal, DailyTarget]:
    goal = _make_goal(session, user)
    target = compute_daily_target(session, user.id, goal.id, user, for_date=_FOR_DATE)
    return goal, target


# ---------------------------------------------------------------------------
# Set / read-model provenance
# ---------------------------------------------------------------------------


def test_set_calorie_override_is_effective_with_user_source(session: Session) -> None:
    user = _make_user_with_profile(session)
    _, target = _seed_target(session, user)
    derived = target.daily_calorie_target_kcal  # 1678

    updated = set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1800),
        for_date=_FOR_DATE,
    )

    assert updated.override_calorie_target_kcal == 1800
    assert updated.override_set_at is not None
    rm = build_target_read_model(updated)
    assert rm.calories.effective == 1800
    assert rm.calories.derived == derived
    assert rm.calories.source == "user"
    # Untouched macros stay derived.
    assert rm.protein_g.source == "derived"


def test_set_macro_override_is_independent_of_calories(session: Session) -> None:
    user = _make_user_with_profile(session)
    _, target = _seed_target(session, user)
    derived_protein = target.protein_target_g  # 128

    updated = set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(protein_target_g=180),
        for_date=_FOR_DATE,
    )

    rm = build_target_read_model(updated)
    assert rm.protein_g.effective == 180
    assert rm.protein_g.derived == derived_protein
    assert rm.protein_g.source == "user"
    # The calorie target is untouched and still derived.
    assert rm.calories.source == "derived"
    assert updated.override_calorie_target_kcal is None


def test_calorie_and_macro_overrides_set_and_reset_independently(session: Session) -> None:
    user = _make_user_with_profile(session)
    _seed_target(session, user)

    set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1900, fat_target_g=70),
        for_date=_FOR_DATE,
    )
    # Reset only the calorie override; the fat override survives.
    updated = reset_target_override(
        session, user.id, user, [OverridableTarget.CALORIES], for_date=_FOR_DATE
    )

    rm = build_target_read_model(updated)
    assert rm.calories.source == "derived"
    assert rm.fat_g.source == "user"
    assert rm.fat_g.effective == 70
    # An override is still in force, so the audit stamp remains.
    assert updated.override_set_at is not None


def test_reset_all_clears_every_override_and_stamp(session: Session) -> None:
    user = _make_user_with_profile(session)
    _seed_target(session, user)
    set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1900, protein_target_g=170),
        for_date=_FOR_DATE,
    )

    updated = reset_target_override(session, user.id, user, None, for_date=_FOR_DATE)

    rm = build_target_read_model(updated)
    assert rm.calories.source == "derived"
    assert rm.protein_g.source == "derived"
    assert updated.override_set_at is None


# ---------------------------------------------------------------------------
# Recompute preserves the in-force override
# ---------------------------------------------------------------------------


def test_recompute_updates_derived_but_preserves_override(session: Session) -> None:
    user = _make_user_with_profile(session)
    goal, target = _seed_target(session, user)
    original_derived = target.daily_calorie_target_kcal

    set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1800),
        for_date=_FOR_DATE,
    )

    # Edit the goal (gentler target) and recompute the derived target in place.
    goal.target_weight_kg = 78.0
    session.commit()
    recomputed = compute_daily_target(session, user.id, goal.id, user, for_date=_FOR_DATE)

    # Derived moved; the override held and is still effective; source stays user.
    assert recomputed.daily_calorie_target_kcal != original_derived
    assert recomputed.override_calorie_target_kcal == 1800
    rm = build_target_read_model(recomputed)
    assert rm.calories.effective == 1800
    assert rm.calories.source == "user"

    # A subsequent reset restores the NEWLY derived value, not the stale one.
    after_reset = reset_target_override(session, user.id, user, None, for_date=_FOR_DATE)
    assert after_reset.effective_calorie_target_kcal == recomputed.daily_calorie_target_kcal
    assert after_reset.calorie_source == "derived"


def test_recompute_for_new_date_carries_override_forward(session: Session) -> None:
    """A row materialised for a new date inherits the goal's in-force override."""

    user = _make_user_with_profile(session)
    goal, _ = _seed_target(session, user)
    set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1750),
        for_date=_FOR_DATE,
    )

    next_day = date(2026, 1, 2)
    rolled = compute_daily_target(session, user.id, goal.id, user, for_date=next_day)

    assert rolled.for_date == next_day
    assert rolled.override_calorie_target_kcal == 1750
    assert build_target_read_model(rolled).calories.source == "user"


# ---------------------------------------------------------------------------
# Override on a later in-horizon day: materialise the row on demand (FTY-127)
# ---------------------------------------------------------------------------


def test_set_override_on_later_in_horizon_day_materialises_row(session: Session) -> None:
    """An override on a day with no stored row materialises it, then succeeds."""

    user = _make_user_with_profile(session)
    _seed_target(session, user)  # only the _FOR_DATE row exists; goal runs to 2026-04-01
    later = date(2026, 1, 6)  # D+5, in horizon
    assert _resolve_active_target_row(session, user.id, later) is None

    updated = set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1800, protein_target_g=170),
        for_date=later,
    )

    # The row was materialised on the requested day and carries the override.
    assert updated.for_date == later
    rm = build_target_read_model(updated)
    assert rm.calories.effective == 1800
    assert rm.calories.source == "user"
    assert rm.protein_g.effective == 170
    assert rm.protein_g.source == "user"

    # The read surface reports the override for that day.
    via_get = get_active_target(session, user.id, user, for_date=later)
    assert via_get.effective_calorie_target_kcal == 1800
    assert via_get.calorie_source == "user"

    # Reset on the (now concrete) later-day row falls back to derived.
    after_reset = reset_target_override(session, user.id, user, None, for_date=later)
    assert after_reset.calorie_source == "derived"
    assert after_reset.protein_source == "derived"


def test_set_override_on_later_day_carries_prior_override_forward(session: Session) -> None:
    """Materialising a later-day row carries the goal's in-force override forward."""

    user = _make_user_with_profile(session)
    _seed_target(session, user)
    set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1750),
        for_date=_FOR_DATE,
    )

    later = date(2026, 1, 6)
    # Set a *protein* override on the later day; the calorie override carries forward.
    updated = set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(protein_target_g=170),
        for_date=later,
    )

    assert updated.for_date == later
    assert updated.override_calorie_target_kcal == 1750  # carried forward
    assert updated.override_protein_target_g == 170
    rm = build_target_read_model(updated)
    assert rm.calories.source == "user"
    assert rm.protein_g.source == "user"


def test_reset_on_later_day_materialises_and_carries_override(session: Session) -> None:
    """Reset on a later day materialises the row (carrying the override) then clears it."""

    user = _make_user_with_profile(session)
    _seed_target(session, user)
    set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=1750),
        for_date=_FOR_DATE,
    )

    later = date(2026, 1, 6)
    # Reset only the protein override: nothing to clear, but the calorie override
    # carried onto the materialised row survives.
    updated = reset_target_override(
        session, user.id, user, [OverridableTarget.PROTEIN], for_date=later
    )

    assert updated.for_date == later
    assert build_target_read_model(updated).calories.source == "user"
    assert updated.override_calorie_target_kcal == 1750


def test_override_past_horizon_fails_closed(session: Session) -> None:
    """A day past ``target_date`` has no active goal covering it → 404 (no oracle)."""

    user = _make_user_with_profile(session)
    _seed_target(session, user)  # target_date 2026-04-01
    past_horizon = date(2026, 4, 2)

    with pytest.raises(TargetNotFound):
        set_target_override(
            session,
            user.id,
            user,
            TargetOverrideRequest(calorie_target_kcal=1800),
            for_date=past_horizon,
        )
    with pytest.raises(TargetNotFound):
        reset_target_override(session, user.id, user, None, for_date=past_horizon)


# ---------------------------------------------------------------------------
# Out-of-band validation: reject, do not clamp
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [1500, 4000])
def test_calorie_override_accepts_band_boundaries(session: Session, value: int) -> None:
    user = _make_user_with_profile(session)  # +5 variant: floor 1500, ceiling 4000
    _seed_target(session, user)

    updated = set_target_override(
        session,
        user.id,
        user,
        TargetOverrideRequest(calorie_target_kcal=value),
        for_date=_FOR_DATE,
    )
    assert updated.override_calorie_target_kcal == value


@pytest.mark.parametrize("value", [1499, 4001])
def test_out_of_band_calorie_override_is_rejected_and_not_persisted(
    session: Session, value: int
) -> None:
    user = _make_user_with_profile(session)
    _seed_target(session, user)

    with pytest.raises(OverrideOutOfBand):
        set_target_override(
            session,
            user.id,
            user,
            TargetOverrideRequest(calorie_target_kcal=value),
            for_date=_FOR_DATE,
        )

    # Nothing persisted: the target is still derived.
    target = get_active_target(session, user.id, user, for_date=_FOR_DATE)
    assert target.override_calorie_target_kcal is None
    assert target.override_set_at is None


def test_out_of_band_macro_override_is_rejected(session: Session) -> None:
    user = _make_user_with_profile(session)
    _seed_target(session, user)

    # Fat ceiling = 4000 // 9 = 444 g; one above is refused.
    with pytest.raises(OverrideOutOfBand):
        set_target_override(
            session,
            user.id,
            user,
            TargetOverrideRequest(fat_target_g=445),
            for_date=_FOR_DATE,
        )


# ---------------------------------------------------------------------------
# Object-level authorization (fail closed, no existence oracle)
# ---------------------------------------------------------------------------


def test_cross_user_set_fails_closed(session: Session) -> None:
    owner = _make_user_with_profile(session)
    _seed_target(session, owner)
    attacker = _make_user_with_profile(session)

    with pytest.raises(GoalForbidden):
        set_target_override(
            session,
            owner.id,
            attacker,
            TargetOverrideRequest(calorie_target_kcal=1800),
            for_date=_FOR_DATE,
        )


def test_cross_user_reset_fails_closed(session: Session) -> None:
    owner = _make_user_with_profile(session)
    _seed_target(session, owner)
    attacker = _make_user_with_profile(session)

    with pytest.raises(GoalForbidden):
        reset_target_override(session, owner.id, attacker, None, for_date=_FOR_DATE)


def test_no_active_target_is_not_found(session: Session) -> None:
    user = _make_user_with_profile(session)  # no goal/target seeded
    with pytest.raises(TargetNotFound):
        get_active_target(session, user.id, user, for_date=_FOR_DATE)
    with pytest.raises(TargetNotFound):
        set_target_override(
            session,
            user.id,
            user,
            TargetOverrideRequest(calorie_target_kcal=1800),
            for_date=_FOR_DATE,
        )


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str) -> tuple[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _seed_api_target(
    db_engine: Engine,
    user_id: str,
    *,
    daily_calorie_target_kcal: int = 1678,
) -> None:
    """Seed an active goal + derived target (with a real safety-band snapshot)."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        goal = Goal(
            user_id=uuid.UUID(user_id),
            start_weight_kg=80.0,
            start_date=date(2026, 1, 1),
            target_weight_kg=75.0,
            target_date=date(2026, 4, 1),
            is_active=True,
        )
        session.add(goal)
        session.flush()
        session.add(
            DailyTarget(
                user_id=uuid.UUID(user_id),
                goal_id=goal.id,
                for_date=_FOR_DATE,
                rmr_kcal=1780.0,
                tdee_kcal=2136.0,
                daily_calorie_target_kcal=daily_calorie_target_kcal,
                clamped=False,
                protein_target_g=128,
                carbs_target_g=148,
                fat_target_g=64,
                macros_clamped=False,
                inputs={},
                assumptions={"safety_floor_kcal": 1500, "safety_ceiling_kcal": 4000},
            )
        )
        session.commit()


def test_api_set_get_and_reset_round_trip(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "target-api@example.com")
    _seed_api_target(db_engine, user_id)
    params = {"day": str(_FOR_DATE)}
    headers = {"Authorization": auth}

    # Set a calorie override.
    resp = client.put(
        f"/api/users/{user_id}/target/override",
        headers=headers,
        params=params,
        json={"calorie_target_kcal": 1800},
    )
    assert resp.status_code == 200
    assert resp.json()["calories"] == {
        "effective": 1800,
        "derived": 1678,
        "source": "user",
    }

    # Read it back.
    resp = client.get(f"/api/users/{user_id}/target", headers=headers, params=params)
    assert resp.status_code == 200
    assert resp.json()["calories"]["source"] == "user"

    # Reset it.
    resp = client.post(
        f"/api/users/{user_id}/target/override/reset",
        headers=headers,
        params=params,
        json={},
    )
    assert resp.status_code == 200
    assert resp.json()["calories"] == {
        "effective": 1678,
        "derived": 1678,
        "source": "derived",
    }


def test_api_set_override_on_later_in_horizon_day_materialises(
    client: TestClient, db_engine: Engine
) -> None:
    """Over HTTP, an override on a later in-horizon day materialises the row + succeeds."""

    user_id, auth = _register(client, "target-later@example.com")
    # The materialise-on-write path recomputes via the calculator, so the user needs a
    # complete profile. Registration creates a bare profile row; fill in the body
    # metrics the calculator requires.
    factory = create_session_factory(db_engine)
    with factory() as session:
        profile = session.scalars(
            select(UserProfile).where(UserProfile.user_id == uuid.UUID(user_id))
        ).one()
        profile.height_m = 1.80
        profile.weight_kg = 80.0
        profile.birth_year = 1996
        profile.metabolic_formula = MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5
        session.commit()
    _seed_api_target(db_engine, user_id)
    headers = {"Authorization": auth}
    later = date(2026, 2, 1)  # in horizon (goal runs to 2026-04-01), no stored row

    resp = client.put(
        f"/api/users/{user_id}/target/override",
        headers=headers,
        params={"day": str(later)},
        json={"calorie_target_kcal": 1800},
    )
    assert resp.status_code == 200
    assert resp.json()["calories"]["source"] == "user"

    # The carried override is visible on the read surface for that day.
    resp = client.get(f"/api/users/{user_id}/target", headers=headers, params={"day": str(later)})
    assert resp.status_code == 200
    assert resp.json()["calories"] == {
        "effective": 1800,
        "derived": 1678,
        "source": "user",
    }


def test_api_out_of_band_override_returns_422(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "target-422@example.com")
    _seed_api_target(db_engine, user_id)

    resp = client.put(
        f"/api/users/{user_id}/target/override",
        headers={"Authorization": auth},
        params={"day": str(_FOR_DATE)},
        json={"calorie_target_kcal": 1000},
    )
    assert resp.status_code == 422


def test_api_empty_override_body_returns_422(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "target-empty@example.com")
    _seed_api_target(db_engine, user_id)

    resp = client.put(
        f"/api/users/{user_id}/target/override",
        headers={"Authorization": auth},
        params={"day": str(_FOR_DATE)},
        json={},
    )
    assert resp.status_code == 422


def test_api_cross_user_override_fails_closed_404(client: TestClient, db_engine: Engine) -> None:
    owner_id, _ = _register(client, "target-owner@example.com")
    _seed_api_target(db_engine, owner_id)
    _, attacker_auth = _register(client, "target-attacker@example.com")

    # Attacker's valid token targeting the owner's endpoint.
    resp = client.put(
        f"/api/users/{owner_id}/target/override",
        headers={"Authorization": attacker_auth},
        params={"day": str(_FOR_DATE)},
        json={"calorie_target_kcal": 1800},
    )
    assert resp.status_code == 404

    resp = client.post(
        f"/api/users/{owner_id}/target/override/reset",
        headers={"Authorization": attacker_auth},
        params={"day": str(_FOR_DATE)},
        json={},
    )
    assert resp.status_code == 404


def test_api_no_active_target_returns_404(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "target-none@example.com")
    # No goal/target seeded.
    resp = client.get(
        f"/api/users/{user_id}/target",
        headers={"Authorization": auth},
        params={"day": str(_FOR_DATE)},
    )
    assert resp.status_code == 404
