"""Label-parse confirmation gate: uncounted proposal, read, confirm (FTY-196).

A legible nutrition-label upload now lands as an **uncounted proposal** — a
``proposed`` ``derived_food_items`` row that does **not** count toward the day's
totals until the user confirms it, because "OCR is fallible — Fatty never silently
trusts a fallible parse" (``docs/design-philosophy.md``). These tests exercise the
backend half of that gate across the trust boundary:

- **Uncounted proposal.** A legible upload's item is ``proposed`` and is excluded
  from ``daily-summary`` intake (single-day *and* range) until confirmed.
- **Proposed-values read.** ``GET .../label-proposal`` returns the parsed values +
  the ``user_label`` provenance for the owner, and fails closed (``404``)
  cross-user / nonexistent.
- **Confirm counts.** ``POST .../label-proposal/confirm`` flips ``proposed →
  resolved``; the item then counts; a second confirm does not double-count.
- **Confirm with adjusted values.** An override commits the user's number with
  honest provenance / ``is_edited`` state; a serving adjust rescales, preserving
  provenance.
- **Authorization.** Read and confirm both fail closed ``404`` cross-user.

The label processor seam is a double backed by a network-free ``FakeProvider`` (no
live model), mirroring ``test_label_upload_endpoint.py``. A Postgres-parity test
exercises the same proposal → confirm → counted flow against the production
datastore when ``FATTY_TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus
from app.estimator.label_step import USER_LABEL_SOURCE_TYPE, LabelInput, LabelResolveStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.identity import User
from app.models.log_events import LogEvent
from app.services.daily_summary import get_daily_summary
from app.services.label_proposal import confirm_label_proposal
from tests.conftest import upgrade

#: A minimal payload whose leading signature is a real PNG (matches the validator's
#: magic-number gate without being a full image).
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

#: The panel the scripted provider returns: 200 kcal / 10 P / 20 C / 8 F per 40 g.
_PANEL: dict[str, Any] = {
    "disposition": "extracted",
    "confidence": 0.95,
    "facts": {
        "product_name": "Trail Mix",
        "serving_size_amount": 40.0,
        "serving_size_unit": "g",
        "servings_per_container": 5.0,
        "energy_kcal_per_serving": 200.0,
        "protein_g_per_serving": 10.0,
        "carbs_g_per_serving": 20.0,
        "fat_g_per_serving": 8.0,
    },
}


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _install_scripted_processor(client: TestClient) -> None:
    """Replace the app's label processor with one backed by a scripted provider."""

    def processor(
        db_session: Session,
        *,
        log_event_id: uuid.UUID,
        user_id: uuid.UUID,
        label_upload: LabelInput,
    ) -> None:
        provider = FakeProvider(responses=[dict(_PANEL)], supports_vision=True)
        process_estimation(
            db_session,
            log_event_id=log_event_id,
            user_id=user_id,
            label_upload=label_upload,
            pipeline=Pipeline([LabelResolveStep(provider)]),
        )

    client.app.state.label_processor = processor  # type: ignore[attr-defined]


def _register(client: TestClient, email: str) -> tuple[uuid.UUID, str]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    return user_id, auth


def _upload_label(client: TestClient, user_id: uuid.UUID, auth: str) -> uuid.UUID:
    """Upload a legible label and return the resulting (proposal-bearing) event id."""

    response = client.post(
        f"/api/users/{user_id}/log-events/label",
        headers={"Authorization": auth, "Content-Type": "image/png"},
        content=_PNG_BYTES,
    )
    assert response.status_code == 201
    assert response.json()["status"] == LogEventStatus.COMPLETED.value
    return uuid.UUID(response.json()["id"])


def _intake_calories(client: TestClient, user_id: uuid.UUID, auth: str) -> float:
    """Today's daily-summary intake calories via the API (default day)."""

    response = client.get(f"/api/users/{user_id}/daily-summary", headers={"Authorization": auth})
    assert response.status_code == 200
    return float(response.json()["intake"]["calories"])


# ── Uncounted proposal ─────────────────────────────────────────────────────────


def test_legible_upload_is_proposed_and_uncounted_single_day(
    client: TestClient, session: Session
) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-uncounted@example.com")

    event_id = _upload_label(client, user_id, auth)

    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).one()
    assert food.status == DerivedItemStatus.PROPOSED
    # By construction: the daily-summary filter requires ``resolved``, so a
    # ``proposed`` item never inflates intake (and has_intake stays false).
    summary = client.get(
        f"/api/users/{user_id}/daily-summary", headers={"Authorization": auth}
    ).json()
    assert summary["intake"]["calories"] == 0
    assert summary["has_intake"] is False


def test_proposed_item_excluded_from_range_intake(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-range@example.com")

    _upload_label(client, user_id, auth)

    today = datetime.now(UTC).date().isoformat()
    response = client.get(
        f"/api/users/{user_id}/daily-summary/range",
        params={"from": today, "to": today},
        headers={"Authorization": auth},
    )
    assert response.status_code == 200
    days = response.json()
    assert all(day["intake"]["calories"] == 0 for day in days)
    assert all(day["has_intake"] is False for day in days)


# ── Proposed-values read ─────────────────────────────────────────────────────────


def test_read_returns_proposed_values_and_user_label_provenance(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-read@example.com")
    event_id = _upload_label(client, user_id, auth)

    response = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal",
        headers={"Authorization": auth},
    )

    assert response.status_code == 200
    proposal = response.json()["proposal"]
    assert proposal is not None
    assert proposal["name"] == "Trail Mix"
    assert proposal["status"] == DerivedItemStatus.PROPOSED.value
    # Default consumed quantity is one 40 g serving → the printed per-serving values.
    assert proposal["calories"] == 200.0
    assert proposal["grams"] == 40.0
    # Provenance: an accepted parse carries the user_label source, un-edited.
    assert proposal["source"]["source_type"] == USER_LABEL_SOURCE_TYPE
    assert proposal["source"]["label"] == "Label scan"
    assert proposal["is_edited"] is False


def test_read_after_confirm_returns_no_proposal(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-read-confirmed@example.com")
    event_id = _upload_label(client, user_id, auth)

    confirm = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
    )
    assert confirm.status_code == 200

    # Once confirmed the item is ``resolved``: it is no longer a pending proposal.
    response = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal",
        headers={"Authorization": auth},
    )
    assert response.status_code == 200
    assert response.json()["proposal"] is None


def test_read_for_event_without_proposal_returns_null(client: TestClient) -> None:
    """An owned non-label event returns 200 with a null proposal (no status oracle)."""

    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-read-nonlabel@example.com")
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "two eggs and toast"},
    )
    assert created.status_code == 201
    event_id = created.json()["id"]

    response = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal",
        headers={"Authorization": auth},
    )
    assert response.status_code == 200
    assert response.json()["proposal"] is None


def test_read_cross_user_is_not_found(client: TestClient) -> None:
    _install_scripted_processor(client)
    owner_id, owner_auth = _register(client, "proposal-read-owner@example.com")
    event_id = _upload_label(client, owner_id, owner_auth)
    _, attacker_auth = _register(client, "proposal-read-attacker@example.com")

    # Cross-user: the attacker addresses the owner's event id → fail closed.
    response = client.get(
        f"/api/users/{owner_id}/log-events/{event_id}/label-proposal",
        headers={"Authorization": attacker_auth},
    )
    assert response.status_code == 404


def test_read_nonexistent_event_is_not_found(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-read-missing@example.com")

    response = client.get(
        f"/api/users/{user_id}/log-events/{uuid.uuid4()}/label-proposal",
        headers={"Authorization": auth},
    )
    assert response.status_code == 404


# ── Confirm counts ───────────────────────────────────────────────────────────────


def test_confirm_flips_to_resolved_and_counts(client: TestClient, session: Session) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-confirm@example.com")
    event_id = _upload_label(client, user_id, auth)
    assert _intake_calories(client, user_id, auth) == 0  # uncounted while proposed

    response = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == DerivedItemStatus.RESOLVED.value
    assert body["calories"] == 200.0
    assert body["source"]["source_type"] == USER_LABEL_SOURCE_TYPE
    assert body["is_edited"] is False  # an accepted parse is not a user edit

    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).one()
    assert food.status == DerivedItemStatus.RESOLVED
    # Now it counts toward the day's totals.
    assert _intake_calories(client, user_id, auth) == 200.0


def test_double_confirm_does_not_double_count(client: TestClient, session: Session) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-double@example.com")
    event_id = _upload_label(client, user_id, auth)

    first = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
    )
    second = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    # Idempotent: the same committed item id, counted exactly once.
    assert first.json()["id"] == second.json()["id"]
    assert _intake_calories(client, user_id, auth) == 200.0
    items = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).all()
    assert len(items) == 1


# ── Confirm with adjusted values ─────────────────────────────────────────────────


def test_confirm_with_value_override_commits_user_number(
    client: TestClient, session: Session
) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-adjust-value@example.com")
    event_id = _upload_label(client, user_id, auth)

    response = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
        json={"calories": 150.0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == DerivedItemStatus.RESOLVED.value
    assert body["calories"] == 150.0  # the user's number, not the parsed 200
    # A changed value is a user edit; provenance stays user_label (honest).
    assert body["is_edited"] is True
    assert body["source"]["source_type"] == USER_LABEL_SOURCE_TYPE
    # The estimator's original is preserved for the audit trail.
    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).one()
    assert food.calories_estimated == 200.0
    assert _intake_calories(client, user_id, auth) == 150.0


def test_confirm_with_serving_adjust_rescales_and_preserves_provenance(
    client: TestClient,
) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-adjust-serving@example.com")
    event_id = _upload_label(client, user_id, auth)

    # Default amount is 1 serving; confirming with amount=2 rescales × 2.
    response = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
        json={"amount": 2.0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["amount"] == 2.0
    assert body["calories"] == 400.0  # 200 × (2 / 1)
    # A serving adjust is provenance-preserving: the item is NOT marked edited.
    assert body["is_edited"] is False
    assert body["source"]["source_type"] == USER_LABEL_SOURCE_TYPE
    assert _intake_calories(client, user_id, auth) == 400.0


def test_confirm_rejecting_one_field_rolls_back_the_whole_confirm(
    client: TestClient, session: Session
) -> None:
    """A valid amount + an invalid value fails atomically: nothing commits (one txn)."""

    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-adjust-atomic@example.com")
    event_id = _upload_label(client, user_id, auth)

    response = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
        # amount=2 is valid (would rescale), but calories is above the sanity bound;
        # the whole confirm must roll back — no partial rescale, no status flip.
        json={"amount": 2.0, "calories": 1_000_000.0},
    )

    assert response.status_code == 422
    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).one()
    assert food.status == DerivedItemStatus.PROPOSED
    assert food.amount == 1.0  # the valid amount rescale was rolled back too
    assert food.calories == 200.0
    assert _intake_calories(client, user_id, auth) == 0


def test_confirm_with_out_of_range_value_is_rejected(client: TestClient, session: Session) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-adjust-badval@example.com")
    event_id = _upload_label(client, user_id, auth)

    response = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
        json={"calories": 1_000_000.0},  # above the canonical sanity bound
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "out_of_range"
    # Fail closed: the item is untouched — still an uncounted proposal.
    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).one()
    assert food.status == DerivedItemStatus.PROPOSED
    assert _intake_calories(client, user_id, auth) == 0


def test_confirm_with_negative_value_is_rejected_at_boundary(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-adjust-neg@example.com")
    event_id = _upload_label(client, user_id, auth)

    response = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": auth},
        json={"protein_g": -5.0},
    )

    assert response.status_code == 422  # DTO boundary: non-negative required


# ── Authorization (confirm) ──────────────────────────────────────────────────────


def test_confirm_cross_user_is_not_found(client: TestClient, session: Session) -> None:
    _install_scripted_processor(client)
    owner_id, owner_auth = _register(client, "proposal-confirm-owner@example.com")
    event_id = _upload_label(client, owner_id, owner_auth)
    _, attacker_auth = _register(client, "proposal-confirm-attacker@example.com")

    response = client.post(
        f"/api/users/{owner_id}/log-events/{event_id}/label-proposal/confirm",
        headers={"Authorization": attacker_auth},
    )

    assert response.status_code == 404
    # Fail closed: the attacker's request never mutated the owner's proposal.
    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).one()
    assert food.status == DerivedItemStatus.PROPOSED


def test_confirm_nonexistent_event_is_not_found(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-confirm-missing@example.com")

    response = client.post(
        f"/api/users/{user_id}/log-events/{uuid.uuid4()}/label-proposal/confirm",
        headers={"Authorization": auth},
    )
    assert response.status_code == 404


def test_confirm_owned_event_without_proposal_is_not_found(client: TestClient) -> None:
    """An owned event that carries no label proposal fails closed as 404."""

    _install_scripted_processor(client)
    user_id, auth = _register(client, "proposal-confirm-nonlabel@example.com")
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "two eggs and toast"},
    )
    assert created.status_code == 201

    response = client.post(
        f"/api/users/{user_id}/log-events/{created.json()['id']}/label-proposal/confirm",
        headers={"Authorization": auth},
    )
    assert response.status_code == 404


# ── Postgres parity ──────────────────────────────────────────────────────────────


def _seed_proposed_label_item(
    session: Session, user_id: uuid.UUID, created_at: datetime
) -> uuid.UUID:
    """Insert a completed label event + a proposed label item with user_label evidence."""

    event = LogEvent(
        user_id=user_id,
        raw_text="Nutrition label photo",
        status=LogEventStatus.COMPLETED,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(event)
    session.flush()

    food = DerivedFoodItem(
        log_event_id=event.id,
        user_id=user_id,
        name="Trail Mix",
        quantity_text="",
        unit=None,
        amount=1.0,
        status=DerivedItemStatus.PROPOSED,
        grams=40.0,
        calories=200.0,
        protein_g=10.0,
        carbs_g=20.0,
        fat_g=8.0,
        calories_estimated=200.0,
        protein_g_estimated=10.0,
        carbs_g_estimated=20.0,
        fat_g_estimated=8.0,
    )
    session.add(food)
    session.flush()

    session.add(
        EvidenceSource(
            user_id=user_id,
            log_event_id=event.id,
            derived_food_item_id=food.id,
            product_id=None,
            source_type=USER_LABEL_SOURCE_TYPE,
            source_ref=f"{USER_LABEL_SOURCE_TYPE}:deadbeef",
            content_hash="deadbeef",
            fetched_at=created_at,
            calories_per_100g=500.0,
            protein_per_100g=25.0,
            carbs_per_100g=50.0,
            fat_per_100g=20.0,
        )
    )
    session.commit()
    return event.id


def test_proposed_then_confirmed_flow_on_postgres(pg_engine: Engine) -> None:
    """The proposed → confirm → counted flow round-trips on Postgres (real datastore).

    Verifies the DB-touching behaviour at the highest applicable level
    (``docs/design-philosophy.md``): the ``proposed`` status value persists on the
    production ``VARCHAR`` column (no schema migration — see :class:`DerivedItemStatus`),
    the finalized-state filter excludes it by construction, and confirming it flips
    ``proposed → resolved`` so it counts. Skips when ``FATTY_TEST_DATABASE_URL`` is unset.
    """

    upgrade(pg_engine, "head")
    day = date(2026, 7, 2)
    created_at = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.commit()

        event_id = _seed_proposed_label_item(session, user.id, created_at)

        # Excluded while proposed (the ``resolved``-only filter is not relaxed).
        before = get_daily_summary(session, user.id, user, day)
        assert before.intake.calories == 0
        assert before.has_intake is False

        # Confirm flips proposed → resolved on Postgres, in one transaction.
        item = confirm_label_proposal(session, user.id, user, event_id)
        assert item.status == DerivedItemStatus.RESOLVED

        after = get_daily_summary(session, user.id, user, day)
        assert after.intake.calories == 200.0
        assert after.has_intake is True

        # A second confirm is idempotent — no double count.
        confirm_label_proposal(session, user.id, user, event_id)
        again = get_daily_summary(session, user.id, user, day)
        assert again.intake.calories == 200.0
