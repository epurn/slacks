"""Log-event API integration tests, including object-level authorization (FTY-030).

The cross-user negative tests are the security control this story must prove: one
user must not be able to create, list, or read another user's log events, and the
API must fail closed. The transition test proves the ``pending → completed`` path
is exercisable end-to-end before the estimator exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import CandidateType, CorrectionSource, DerivedItemStatus, LogEventStatus, SourceType
from app.models.corrections import Correction
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services import log_events as log_event_service


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
    """Set the user's profile timezone (the day-bucketing zone)."""

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"timezone": tz},
    )
    assert resp.status_code == 200


def _seed_event_at(
    db_engine: Engine,
    user_id: str,
    created_at: datetime,
    *,
    raw_text: str = "seed event",
    status: LogEventStatus = LogEventStatus.PENDING,
) -> uuid.UUID:
    """Insert a pending log event stamped at a fixed ``created_at`` and return its id.

    The create API never lets a client set ``created_at``, so bucketing tests seed
    the timestamp directly to place an event at a precise instant near a local-day
    boundary.
    """

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(
            user_id=uuid.UUID(user_id),
            raw_text=raw_text,
            status=status,
            created_at=created_at,
        )
        session.add(event)
        session.commit()
        return event.id


def _seed_food_item(
    db_engine: Engine,
    user_id: str,
    event_id: uuid.UUID,
    *,
    name: str = "white rice",
    status: DerivedItemStatus = DerivedItemStatus.RESOLVED,
    calories: float | None = 205.0,
) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedFoodItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name=name,
            quantity_text="1 serving",
            unit=None,
            amount=1.0,
            status=status,
            grams=150.0,
            calories=calories,
            protein_g=4.3 if calories is not None else None,
            carbs_g=44.5 if calories is not None else None,
            fat_g=0.4 if calories is not None else None,
            calories_estimated=calories,
            protein_g_estimated=4.3 if calories is not None else None,
            carbs_g_estimated=44.5 if calories is not None else None,
            fat_g_estimated=0.4 if calories is not None else None,
        )
        session.add(item)
        session.commit()
        return item.id


def _seed_exercise_item(
    db_engine: Engine,
    user_id: str,
    event_id: uuid.UUID,
    *,
    active_calories: float = 120.0,
) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedExerciseItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name="walking",
            quantity_text="30 minutes",
            unit="minutes",
            amount=30.0,
            status=DerivedItemStatus.RESOLVED,
            active_calories=active_calories,
            active_calories_estimated=active_calories,
        )
        session.add(item)
        session.commit()
        return item.id


def _seed_usda_evidence(
    db_engine: Engine, user_id: str, event_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    factory = create_session_factory(db_engine)
    with factory() as session:
        evidence = EvidenceSource(
            user_id=uuid.UUID(user_id),
            log_event_id=event_id,
            derived_food_item_id=item_id,
            product_id=None,
            source_type=SourceType.TRUSTED_NUTRITION_DATABASE,
            source_ref="usda_fdc:168880",
            content_hash="0" * 64,
            fetched_at=datetime.now(UTC),
            calories_per_100g=130.0,
            protein_per_100g=2.7,
            carbs_per_100g=28.0,
            fat_per_100g=0.3,
        )
        session.add(evidence)
        session.commit()


def _seed_user_edit(db_engine: Engine, user_id: str, item_id: uuid.UUID) -> None:
    factory = create_session_factory(db_engine)
    with factory() as session:
        correction = Correction(
            user_id=uuid.UUID(user_id),
            item_type=CandidateType.FOOD,
            derived_food_item_id=item_id,
            field="calories",
            old_value=205.0,
            new_value=210.0,
            source=CorrectionSource.USER_EDIT,
        )
        session.add(correction)
        session.commit()


def test_create_returns_pending_event(client: TestClient) -> None:
    user_id, auth = _register(client, "logger@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "  two eggs and toast  "},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == user_id
    assert body["status"] == "pending"
    # Surrounding whitespace is trimmed before storage.
    assert body["raw_text"] == "two eggs and toast"
    assert uuid.UUID(body["id"])


def test_list_today_returns_only_requested_day(client: TestClient) -> None:
    user_id, auth = _register(client, "today@example.com")
    create = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a banana"},
    )
    event_id = create.json()["id"]
    created_day = create.json()["created_at"][:10]

    today = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": created_day},
    )
    other_day = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "1999-01-01"},
    )

    assert today.status_code == 200
    assert [e["id"] for e in today.json()] == [event_id]
    assert other_day.status_code == 200
    assert other_day.json() == []


def test_list_defaults_to_today(client: TestClient) -> None:
    user_id, auth = _register(client, "default-day@example.com")
    create = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a coffee"},
    )

    resp = client.get(f"/api/users/{user_id}/log-events", headers={"Authorization": auth})

    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [create.json()["id"]]


def test_get_by_id_returns_owned_event(client: TestClient) -> None:
    user_id, auth = _register(client, "getbyid@example.com")
    event_id = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "grilled chicken salad"},
    ).json()["id"]

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == event_id
    assert resp.json()["raw_text"] == "grilled chicken salad"


def test_get_unknown_id_is_not_found(client: TestClient) -> None:
    user_id, auth = _register(client, "unknown@example.com")

    resp = client.get(
        f"/api/users/{user_id}/log-events/{uuid.uuid4()}", headers={"Authorization": auth}
    )

    assert resp.status_code == 404


def test_create_rejects_empty_text(client: TestClient) -> None:
    user_id, auth = _register(client, "empty@example.com")

    blank = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": ""},
    )
    whitespace = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "   "},
    )

    assert blank.status_code == 422
    assert whitespace.status_code == 422


def test_create_rejects_oversized_text(client: TestClient) -> None:
    user_id, auth = _register(client, "oversized@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "x" * 2001},
    )

    assert resp.status_code == 422


def test_create_rejects_unknown_field(client: TestClient) -> None:
    user_id, auth = _register(client, "extra@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "an apple", "status": "completed"},
    )

    assert resp.status_code == 422


def test_endpoints_require_authentication(client: TestClient) -> None:
    user_id, _auth = _register(client, "noauth@example.com")

    missing_create = client.post(f"/api/users/{user_id}/log-events", json={"raw_text": "an apple"})
    missing_list = client.get(f"/api/users/{user_id}/log-events")
    bad_token = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert missing_create.status_code == 401
    assert missing_list.status_code == 401
    assert bad_token.status_code == 401


def test_cross_user_create_fails_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "alice-log@example.com")
    bob_id, bob_auth = _register(client, "bob-log@example.com")

    # Alice presents a valid token but targets Bob's account.
    resp = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": alice_auth},
        json={"raw_text": "not my event"},
    )

    assert resp.status_code == 404
    # Bob has no events created on his behalf.
    bob_list = client.get(f"/api/users/{bob_id}/log-events", headers={"Authorization": bob_auth})
    assert bob_list.json() == []


def test_cross_user_list_fails_closed(client: TestClient) -> None:
    alice_id, alice_auth = _register(client, "alice-list@example.com")
    bob_id, bob_auth = _register(client, "bob-list@example.com")
    client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": bob_auth},
        json={"raw_text": "bob's private log"},
    )

    resp = client.get(f"/api/users/{bob_id}/log-events", headers={"Authorization": alice_auth})

    assert resp.status_code == 404
    # Sanity: each owner still reads their own list.
    assert (
        client.get(
            f"/api/users/{alice_id}/log-events", headers={"Authorization": alice_auth}
        ).status_code
        == 200
    )


def test_cross_user_get_by_id_fails_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "alice-get@example.com")
    bob_id, bob_auth = _register(client, "bob-get@example.com")
    bob_event_id = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": bob_auth},
        json={"raw_text": "bob's private log"},
    ).json()["id"]

    # Alice cannot read Bob's event by id even via her own path, and the API
    # does not confirm the event exists under Bob's path either.
    via_bob_path = client.get(
        f"/api/users/{bob_id}/log-events/{bob_event_id}", headers={"Authorization": alice_auth}
    )
    via_alice_path = client.get(
        f"/api/users/{_alice_id}/log-events/{bob_event_id}",
        headers={"Authorization": alice_auth},
    )

    assert via_bob_path.status_code == 404
    assert via_alice_path.status_code == 404


def test_pending_to_completed_transition_end_to_end(client: TestClient, db_engine: Engine) -> None:
    """Exercise the pending → completed transition before the estimator exists."""

    user_id, auth = _register(client, "transition@example.com")
    event_id = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a sandwich"},
    ).json()["id"]

    # Drive the transition through the service contract (the test/admin path),
    # sharing the same database the API reads from.
    factory = create_session_factory(db_engine)
    with factory() as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        event = log_event_service.get_event(session, user.id, user, uuid.UUID(event_id))
        log_event_service.transition_event(session, event, LogEventStatus.COMPLETED)

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_raw_text_is_stored_verbatim_after_trim(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "verbatim@example.com")
    event_id = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "150g rice and dal"},
    ).json()["id"]

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = session.get(LogEvent, uuid.UUID(event_id))
        assert event is not None
        assert event.raw_text == "150g rice and dal"
        assert event.status == LogEventStatus.PENDING


# ---------------------------------------------------------------------------
# Timestamp / timezone correctness (FTY-173)
# ---------------------------------------------------------------------------


def test_created_at_serializes_timezone_aware(client: TestClient) -> None:
    """The event DTO serializes ``created_at``/``updated_at`` with an explicit UTC offset.

    A naive datetime on the wire is the A6 ambiguity: the client reads the instant
    as its own local time and an evening entry drifts to the wrong day. Every
    timestamp must carry an offset so the client converts unambiguously.
    """

    user_id, auth = _register(client, "tz-aware@example.com")
    body = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a banana"},
    ).json()

    for field in ("created_at", "updated_at"):
        raw = body[field]
        # Explicit UTC offset — ISO-8601 "Z" or "+00:00", never a bare naive string.
        assert raw.endswith("Z") or raw.endswith("+00:00"), f"{field} not tz-aware: {raw!r}"
        parsed = datetime.fromisoformat(raw)
        assert parsed.tzinfo is not None, f"{field} parsed naive: {raw!r}"
        assert parsed.utcoffset() == timedelta(0), f"{field} not UTC: {raw!r}"


def test_list_today_excludes_previous_local_evening(client: TestClient, db_engine: Engine) -> None:
    """An entry logged the previous local evening never appears under "Today".

    User in America/New_York. An event at 2026-06-16 01:00 UTC is 2026-06-15 21:00
    EDT — 9pm the *previous* local day. It must bucket under 2026-06-15, not the
    2026-06-16 local day that shares its UTC date.
    """

    user_id, auth = _register(client, "prev-evening@example.com")
    _set_timezone(client, user_id, auth, "America/New_York")

    # 2026-06-16 01:00 UTC → 2026-06-15 21:00 EDT (UTC-4).
    event_id = _seed_event_at(db_engine, user_id, datetime(2026, 6, 16, 1, 0, tzinfo=UTC))

    today = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "2026-06-16"},
    )
    prior = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "2026-06-15"},
    )

    assert today.status_code == 200
    assert [e["id"] for e in today.json()] == [], "prior-evening entry leaked into Today"
    assert prior.status_code == 200
    assert [e["id"] for e in prior.json()] == [str(event_id)]


def test_list_today_buckets_in_half_hour_offset_zone(client: TestClient, db_engine: Engine) -> None:
    """A half-hour-offset zone (Asia/Kolkata, UTC+5:30) buckets by local midnight.

    Two events straddle local midnight:
    - 2026-06-15 18:15 UTC → 2026-06-15 23:45 IST → local day 2026-06-15
    - 2026-06-15 18:45 UTC → 2026-06-16 00:15 IST → local day 2026-06-16
    """

    user_id, auth = _register(client, "kolkata@example.com")
    _set_timezone(client, user_id, auth, "Asia/Kolkata")

    before = _seed_event_at(db_engine, user_id, datetime(2026, 6, 15, 18, 15, tzinfo=UTC))
    after = _seed_event_at(db_engine, user_id, datetime(2026, 6, 15, 18, 45, tzinfo=UTC))

    day15 = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "2026-06-15"},
    )
    day16 = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "2026-06-16"},
    )

    assert [e["id"] for e in day15.json()] == [str(before)]
    assert [e["id"] for e in day16.json()] == [str(after)]


# ---------------------------------------------------------------------------
# Entries-by-date read API (FTY-198)
# ---------------------------------------------------------------------------


def test_entries_by_date_returns_events_with_today_item_read_model(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "entries-shape@example.com")
    event_id = _seed_event_at(
        db_engine,
        user_id,
        datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        raw_text="rice and a walk",
        status=LogEventStatus.COMPLETED,
    )
    food_id = _seed_food_item(db_engine, user_id, event_id)
    _seed_usda_evidence(db_engine, user_id, event_id, food_id)
    _seed_user_edit(db_engine, user_id, food_id)
    exercise_id = _seed_exercise_item(db_engine, user_id, event_id)

    resp = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": "2026-06-20"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["event"]["id"] == str(event_id)
    assert body[0]["event"]["user_id"] == user_id
    assert body[0]["event"]["raw_text"] == "rice and a walk"
    assert body[0]["event"]["status"] == "completed"
    assert body[0]["event"]["created_at"] == "2026-06-20T12:00:00Z"

    food, exercise = body[0]["items"]
    assert food["item_type"] == "food"
    assert food["id"] == str(food_id)
    assert food["name"] == "white rice"
    assert food["log_event_id"] == str(event_id)
    assert food["status"] == "resolved"
    assert food["calories"] == 205.0
    assert food["protein_g"] == 4.3
    assert food["source"] == {
        "source_type": "trusted_nutrition_database",
        "label": "USDA",
        "ref": "usda_fdc:168880",
    }
    assert food["is_edited"] is True

    assert exercise["item_type"] == "exercise"
    assert exercise["id"] == str(exercise_id)
    assert exercise["name"] == "walking"
    assert exercise["active_calories"] == 120.0
    assert exercise["source"] is None
    assert exercise["is_edited"] is False


def test_entries_by_date_uses_profile_timezone_and_matches_daily_summary(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "entries-tz@example.com")
    _set_timezone(client, user_id, auth, "America/New_York")
    prior_local_event = _seed_event_at(
        db_engine,
        user_id,
        datetime(2026, 6, 16, 1, 0, tzinfo=UTC),
        raw_text="late rice",
        status=LogEventStatus.COMPLETED,
    )
    today_local_event = _seed_event_at(
        db_engine,
        user_id,
        datetime(2026, 6, 16, 14, 0, tzinfo=UTC),
        raw_text="lunch rice",
        status=LogEventStatus.COMPLETED,
    )
    _seed_food_item(db_engine, user_id, prior_local_event, calories=100.0)
    _seed_food_item(db_engine, user_id, today_local_event, calories=200.0)

    prior_entries = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": "2026-06-15"},
    )
    today_entries = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": "2026-06-16"},
    )
    prior_summary = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-06-15"},
    )
    today_summary = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-06-16"},
    )

    assert [entry["event"]["id"] for entry in prior_entries.json()] == [str(prior_local_event)]
    assert [entry["event"]["id"] for entry in today_entries.json()] == [str(today_local_event)]
    assert prior_summary.json()["intake"]["calories"] == 100.0
    assert today_summary.json()["intake"]["calories"] == 200.0


def test_entries_by_date_is_owner_scoped_fail_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "entries-alice@example.com")
    bob_id, bob_auth = _register(client, "entries-bob@example.com")
    bob_create = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": bob_auth},
        json={"raw_text": "bob's private log"},
    )
    assert bob_create.status_code == 201

    resp = client.get(
        f"/api/users/{bob_id}/log-events/by-date",
        headers={"Authorization": alice_auth},
        params={"day": bob_create.json()["created_at"][:10]},
    )

    assert resp.status_code == 404


def test_entries_by_date_rejects_malformed_day(client: TestClient) -> None:
    user_id, auth = _register(client, "entries-badday@example.com")

    resp = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": "2026/06/20"},
    )

    assert resp.status_code == 422


def test_entries_by_date_round_trips_on_postgres(pg_engine: Engine) -> None:
    """Shape + timezone day bounds exercise the production datastore when configured."""

    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id, timezone="America/New_York"))
        event = LogEvent(
            user_id=user.id,
            raw_text="postgres rice",
            status=LogEventStatus.COMPLETED,
            created_at=datetime(2026, 6, 16, 1, 0, tzinfo=UTC),
        )
        session.add(event)
        session.flush()
        item = DerivedFoodItem(
            log_event_id=event.id,
            user_id=user.id,
            name="white rice",
            quantity_text="1 serving",
            amount=1.0,
            status=DerivedItemStatus.RESOLVED,
            grams=150.0,
            calories=100.0,
            protein_g=2.0,
            carbs_g=22.0,
            fat_g=0.2,
            calories_estimated=100.0,
            protein_g_estimated=2.0,
            carbs_g_estimated=22.0,
            fat_g_estimated=0.2,
        )
        session.add(item)
        session.flush()
        session.add(
            EvidenceSource(
                user_id=user.id,
                log_event_id=event.id,
                derived_food_item_id=item.id,
                product_id=None,
                source_type=SourceType.MODEL_PRIOR,
                source_ref="model_prior",
                content_hash="0" * 64,
                fetched_at=datetime.now(UTC),
                calories_per_100g=66.7,
                protein_per_100g=1.3,
                carbs_per_100g=14.7,
                fat_per_100g=0.1,
            )
        )
        session.commit()
        user_id = user.id

    with factory() as session:
        loaded_user = session.get(User, user_id)
        assert loaded_user is not None
        prior = log_event_service.list_entries_for_day(
            session, user_id, loaded_user, date(2026, 6, 15)
        )
        today = log_event_service.list_entries_for_day(
            session, user_id, loaded_user, date(2026, 6, 16)
        )

    assert len(prior) == 1
    assert prior[0].event.raw_text == "postgres rice"
    assert len(prior[0].items) == 1
    assert prior[0].items[0].source is not None
    assert prior[0].items[0].source.source_type == SourceType.MODEL_PRIOR
    assert today == []
