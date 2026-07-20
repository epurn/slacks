"""Prior-correction candidate surface + apply path (FTY-411).

FTY-406 made the user's own corrections a *resolution source* at estimate time but
deliberately deferred every client surface: no queryable candidate list, no apply
path. These tests pin the surface FTY-407/FTY-408 consume:

- **Candidate surface.** A user with a confident, stable prior correction for an
  item's normalized name gets it back as a bounded, top-ranked candidate carrying the
  corrected values and a ``prior_correction:<content_hash>`` reference; a user with
  none gets nothing (the ordinary USDA candidates and estimate-time resolution are
  unaffected — no regression).
- **Apply path.** Picking a prior-correction candidate re-derives the value from the
  corrections trail (never the ``products`` cache), reproducing FTY-406's direct-match
  vs. per-gram-rescale result with ``prior_correction`` provenance and ``is_edited ==
  false``.
- **Per-user isolation** on both read and apply — another user's correction is never
  surfaced or applied, and a stale/foreign reference is rejected with no mutation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import (
    CandidateType,
    CorrectionSource,
    DerivedItemStatus,
    LogEventStatus,
    SourceType,
)
from app.estimator.prior_correction_candidates import MAX_PRIOR_CORRECTION_CANDIDATES
from app.estimator.re_match import (
    ItemForbidden,
    ReMatchCapability,
    SourceNotResolvable,
)
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.identity import User
from app.models.log_events import LogEvent
from app.services import item_read_model
from tests.corrections_helpers import register, seed_evidence

# ---------------------------------------------------------------------------
# Fixtures + seeding
# ---------------------------------------------------------------------------

#: The estimator's wrong first guess snapshotted into ``calories_estimated`` — the
#: value the operator's "black coffee" re-guessed before the correction.
_WRONG_GUESS = 148.8

_NO_MACROS: tuple[float | None, float | None, float | None] = (None, None, None)
_UNPORTIONED: tuple[str | None, float | None, str] = (None, None, "")


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _new_user(session: Session) -> User:
    user = User()
    session.add(user)
    session.flush()
    return user


def _seed_corrected_food(
    session: Session,
    user_id: uuid.UUID,
    *,
    name: str,
    calories: float,
    macros: tuple[float | None, float | None, float | None] = _NO_MACROS,
    grams: float | None = None,
    portion: tuple[str | None, float | None, str] = _UNPORTIONED,
) -> uuid.UUID:
    """Seed a food item the user has hand-corrected (a ``user_edit`` on calories)."""

    protein_g, carbs_g, fat_g = macros
    unit, amount, quantity_text = portion
    event = LogEvent(user_id=user_id, raw_text="seed", status=LogEventStatus.COMPLETED)
    session.add(event)
    session.flush()

    item = DerivedFoodItem(
        log_event_id=event.id,
        user_id=user_id,
        name=name,
        quantity_text=quantity_text,
        unit=unit,
        amount=amount,
        status=DerivedItemStatus.RESOLVED,
        grams=grams,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        calories_estimated=_WRONG_GUESS,
        protein_g_estimated=protein_g,
        carbs_g_estimated=carbs_g,
        fat_g_estimated=fat_g,
    )
    session.add(item)
    session.flush()
    session.add(
        Correction(
            user_id=user_id,
            item_type=CandidateType.FOOD,
            derived_food_item_id=item.id,
            field="calories",
            old_value=_WRONG_GUESS,
            new_value=calories,
            source=CorrectionSource.USER_EDIT,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()
    return item.id


def _seed_target(
    session: Session,
    user_id: uuid.UUID,
    *,
    name: str,
    portion: tuple[str | None, float | None, str] = _UNPORTIONED,
    grams: float | None = 999.0,
    calories: float = _WRONG_GUESS,
) -> uuid.UUID:
    """Seed a fresh resolved item (no correction of its own) to be re-matched.

    This is the item whose correction sheet lists candidates — a new log of the same
    food, currently carrying the wrong source-matched guess.
    """

    unit, amount, quantity_text = portion
    event = LogEvent(user_id=user_id, raw_text="log", status=LogEventStatus.COMPLETED)
    session.add(event)
    session.flush()
    item = DerivedFoodItem(
        log_event_id=event.id,
        user_id=user_id,
        name=name,
        quantity_text=quantity_text,
        unit=unit,
        amount=amount,
        status=DerivedItemStatus.RESOLVED,
        grams=grams,
        calories=calories,
        protein_g=1.0,
        carbs_g=2.0,
        fat_g=3.0,
        calories_estimated=calories,
        protein_g_estimated=1.0,
        carbs_g_estimated=2.0,
        fat_g_estimated=3.0,
    )
    session.add(item)
    session.commit()
    return item.id


def _capability(session: Session) -> ReMatchCapability:
    # Prior-correction listing/apply never touches the provider fan-out.
    return ReMatchCapability(session=session, providers=())


# ---------------------------------------------------------------------------
# (a) Candidate surface
# ---------------------------------------------------------------------------


def test_prior_correction_is_surfaced_as_a_candidate(session: Session) -> None:
    user = _new_user(session)
    _seed_corrected_food(session, user.id, name="black coffee", calories=3.0)
    target = _seed_target(session, user.id, name="black coffee")

    candidates = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.calories == pytest.approx(3.0)
    assert candidate.basis == "as_logged"
    assert candidate.rescaled is False
    # A re-derivable reference (mirrors FTY-406's prior_correction:<content_hash>).
    assert candidate.source_ref.startswith("prior_correction:")
    # Macros the correction never supplied are honestly unknown, never a fabricated 0.
    assert candidate.protein_g is None


def test_prior_correction_candidate_carries_corrected_macros(session: Session) -> None:
    user = _new_user(session)
    _seed_corrected_food(
        session, user.id, name="protein shake", calories=180.0, macros=(30.0, 5.0, 2.0)
    )
    target = _seed_target(session, user.id, name="Protein Shake")  # case-folded match

    candidates = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )

    assert len(candidates) == 1
    assert candidates[0].calories == pytest.approx(180.0)
    assert candidates[0].protein_g == pytest.approx(30.0)
    assert candidates[0].carbs_g == pytest.approx(5.0)
    assert candidates[0].fat_g == pytest.approx(2.0)


def test_no_prior_correction_yields_no_candidate(session: Session) -> None:
    """No regression: a name the user never corrected surfaces nothing."""

    user = _new_user(session)
    _seed_corrected_food(session, user.id, name="black coffee", calories=3.0)
    # The item being re-matched is a different food the user has never corrected.
    target = _seed_target(session, user.id, name="white rice")

    candidates = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )

    assert candidates == []


def test_conflicting_priors_surface_no_candidate(session: Session) -> None:
    """Ambiguous priors fall through (FTY-406) — nothing confident to offer."""

    user = _new_user(session)
    _seed_corrected_food(session, user.id, name="black coffee", calories=3.0)
    _seed_corrected_food(session, user.id, name="black coffee", calories=9.0)
    target = _seed_target(session, user.id, name="black coffee")

    candidates = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )

    assert candidates == []


def test_candidate_list_is_bounded(session: Session) -> None:
    """Several agreeing priors collapse to one authoritative candidate (bounded cap)."""

    user = _new_user(session)
    for _ in range(5):
        _seed_corrected_food(session, user.id, name="black coffee", calories=3.0)
    target = _seed_target(session, user.id, name="black coffee")

    candidates = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )

    assert len(candidates) <= MAX_PRIOR_CORRECTION_CANDIDATES == 1


def test_candidate_read_is_per_user(session: Session) -> None:
    """Alice's correction is never surfaced for Bob's identically-named item."""

    alice = _new_user(session)
    bob = _new_user(session)
    _seed_corrected_food(session, alice.id, name="black coffee", calories=3.0)
    bob_target = _seed_target(session, bob.id, name="black coffee")

    candidates = _capability(session).list_prior_correction_candidates(
        owner_id=bob.id, current_user=bob, item_id=bob_target
    )

    assert candidates == []


def test_candidate_read_cross_user_fails_closed(session: Session) -> None:
    alice = _new_user(session)
    bob = _new_user(session)
    bob_target = _seed_target(session, bob.id, name="black coffee")

    # Alice (authorized as herself) targets Bob's owner_id: authorization fails closed.
    with pytest.raises(ItemForbidden):
        _capability(session).list_prior_correction_candidates(
            owner_id=bob.id, current_user=alice, item_id=bob_target
        )


# ---------------------------------------------------------------------------
# (b) Apply path — re-derived from the corrections trail, not the products cache
# ---------------------------------------------------------------------------


def test_apply_direct_match_reproduces_corrected_value(session: Session) -> None:
    user = _new_user(session)
    _seed_corrected_food(session, user.id, name="black coffee", calories=3.0)
    target = _seed_target(session, user.id, name="black coffee", calories=_WRONG_GUESS)

    candidate = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )[0]

    item = _capability(session).re_resolve(
        owner_id=user.id, current_user=user, item_id=target, source_ref=candidate.source_ref
    )

    # Reproduces FTY-406's direct-match result: the corrected total, as-logged.
    assert item.calories == pytest.approx(3.0)
    assert item.status == DerivedItemStatus.RESOLVED
    # Re-snapshots *_estimated to the applied value (re-resolution semantics).
    assert item.calories_estimated == pytest.approx(3.0)

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == target)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].source_type == SourceType.PRIOR_CORRECTION.value
    assert evidence[0].source_ref == candidate.source_ref
    assert evidence[0].basis == "as_logged"
    assert evidence[0].assumptions is None
    # No products cache row is written for a prior-correction apply.
    assert evidence[0].product_id is None

    # Honest provenance: the item reads un-edited (its truth is the curated value).
    assert item_read_model.item_is_edited(session, CandidateType.FOOD, target) is False
    assert (
        session.scalars(
            select(Correction).where(
                Correction.derived_food_item_id == target,
                Correction.source == CorrectionSource.USER_EDIT,
            )
        ).all()
        == []
    )


def test_apply_rewrites_evidence_in_place(session: Session) -> None:
    """A re-matched item keeps a single evidence row, now prior-correction sourced."""

    user = _new_user(session)
    _seed_corrected_food(session, user.id, name="black coffee", calories=3.0)
    target = _seed_target(session, user.id, name="black coffee")
    # Seed a pre-existing USDA evidence row so the rewrite is proven in place.
    seed_evidence(
        session.get_bind(),  # type: ignore[arg-type]
        str(user.id),
        target,
        source_type="trusted_nutrition_database",
        source_ref="usda_fdc:OLD",
    )

    candidate = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )[0]
    _capability(session).re_resolve(
        owner_id=user.id, current_user=user, item_id=target, source_ref=candidate.source_ref
    )

    session.expire_all()
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == target)
    ).all()
    assert len(evidence) == 1  # rewritten in place, not appended
    assert evidence[0].source_ref == candidate.source_ref
    assert evidence[0].source_type == SourceType.PRIOR_CORRECTION.value


def test_apply_rescale_reproduces_per_gram_rescale(session: Session) -> None:
    user = _new_user(session)
    # Prior: "latte 240ml = 120 kcal, 6g protein" (0.5 kcal/g at 240 g).
    _seed_corrected_food(
        session,
        user.id,
        name="latte",
        calories=120.0,
        macros=(6.0, None, None),
        grams=240.0,
        portion=("ml", 240.0, "240ml"),
    )
    # The item being re-matched is a larger 480 ml latte.
    target = _seed_target(
        session, user.id, name="latte", portion=("ml", 480.0, "480ml"), grams=None
    )

    candidate = _capability(session).list_prior_correction_candidates(
        owner_id=user.id, current_user=user, item_id=target
    )[0]
    assert candidate.rescaled is True
    assert candidate.calories == pytest.approx(240.0)

    item = _capability(session).re_resolve(
        owner_id=user.id, current_user=user, item_id=target, source_ref=candidate.source_ref
    )

    # Reproduces FTY-406's rescale: per-gram × the new grams, with the rescale assumption.
    assert item.calories == pytest.approx(240.0)
    assert item.protein_g == pytest.approx(12.0)
    assert item.grams == pytest.approx(480.0)
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == target)
    ).one()
    assert evidence.assumptions == ["prior_correction_rescaled"]
    assert evidence.basis == "as_logged"


def test_apply_rejects_a_stale_or_foreign_reference(session: Session) -> None:
    """The trust anchor: a reference the server cannot re-derive is rejected, no mutation."""

    user = _new_user(session)
    _seed_corrected_food(session, user.id, name="black coffee", calories=3.0)
    target = _seed_target(session, user.id, name="black coffee", calories=_WRONG_GUESS)

    with pytest.raises(SourceNotResolvable):
        _capability(session).re_resolve(
            owner_id=user.id,
            current_user=user,
            item_id=target,
            source_ref="prior_correction:deadbeef",  # not the current projection's hash
        )

    session.expire_all()
    item = session.get(DerivedFoodItem, target)
    assert item is not None
    assert item.calories == pytest.approx(_WRONG_GUESS)  # nothing mutated


def test_apply_is_per_user_no_cross_user_value(session: Session) -> None:
    """Bob cannot apply Alice's correction to his own identically-named item.

    Bob echoes back the exact ``prior_correction:<hash>`` reference Alice's correction
    produces, but the apply re-derives from *Bob's* trail (empty), so it fails closed —
    no cross-user value is ever applied.
    """

    alice = _new_user(session)
    bob = _new_user(session)
    alice_target = _seed_target(session, alice.id, name="black coffee")
    _seed_corrected_food(session, alice.id, name="black coffee", calories=3.0)
    bob_target = _seed_target(session, bob.id, name="black coffee", calories=_WRONG_GUESS)

    alice_ref = (
        _capability(session)
        .list_prior_correction_candidates(
            owner_id=alice.id, current_user=alice, item_id=alice_target
        )[0]
        .source_ref
    )

    with pytest.raises(SourceNotResolvable):
        _capability(session).re_resolve(
            owner_id=bob.id, current_user=bob, item_id=bob_target, source_ref=alice_ref
        )

    session.expire_all()
    bob_item = session.get(DerivedFoodItem, bob_target)
    assert bob_item is not None
    assert bob_item.calories == pytest.approx(_WRONG_GUESS)


def test_apply_cross_user_fails_closed(session: Session) -> None:
    alice = _new_user(session)
    bob = _new_user(session)
    _seed_corrected_food(session, bob.id, name="black coffee", calories=3.0)
    bob_target = _seed_target(session, bob.id, name="black coffee")
    bob_ref = (
        _capability(session)
        .list_prior_correction_candidates(owner_id=bob.id, current_user=bob, item_id=bob_target)[0]
        .source_ref
    )

    with pytest.raises(ItemForbidden):
        _capability(session).re_resolve(
            owner_id=bob.id, current_user=alice, item_id=bob_target, source_ref=bob_ref
        )


# ---------------------------------------------------------------------------
# (c) API — thin pass-through end-to-end
# ---------------------------------------------------------------------------


def _candidates_url(user_id: str, item_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/derived-items/food/{item_id}/source-candidates"


def _re_resolve_url(user_id: str, item_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/derived-items/food/{item_id}/re-resolve"


def _seed_via_factory(db_engine: Engine, user_id: str) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as s:
        _seed_corrected_food(s, uuid.UUID(user_id), name="black coffee", calories=3.0)
        return _seed_target(s, uuid.UUID(user_id), name="black coffee", calories=_WRONG_GUESS)


def test_source_candidates_api_returns_prior_correction(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "fty411-list@example.com")
    target = _seed_via_factory(db_engine, user_id)

    resp = client.post(_candidates_url(user_id, target), headers={"Authorization": auth}, json={})

    assert resp.status_code == 200
    body = resp.json()
    # No FDC key in tests → the guessed-source list is empty; the prior correction is not.
    assert body["candidates"] == []
    assert len(body["prior_corrections"]) == 1
    candidate = body["prior_corrections"][0]
    assert candidate["source_type"] == "prior_correction"
    assert candidate["calories"] == pytest.approx(3.0)
    assert candidate["basis"] == "as_logged"
    assert candidate["source_ref"].startswith("prior_correction:")


def test_re_resolve_api_applies_prior_correction_end_to_end(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "fty411-apply@example.com")
    target = _seed_via_factory(db_engine, user_id)

    listing = client.post(
        _candidates_url(user_id, target), headers={"Authorization": auth}, json={}
    )
    source_ref = listing.json()["prior_corrections"][0]["source_ref"]

    resp = client.post(
        _re_resolve_url(user_id, target),
        headers={"Authorization": auth},
        json={"source_ref": source_ref},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["calories"] == pytest.approx(3.0)
    assert body["is_edited"] is False
    # FTY-092 read-model surfaces the prior-correction provenance ("Your correction").
    assert body["source"]["source_type"] == "prior_correction"
    assert body["source"]["ref"] == source_ref


def test_re_resolve_api_cross_user_prior_correction_is_404(
    client: TestClient, db_engine: Engine
) -> None:
    _alice_id, alice_auth = register(client, "fty411-alice@example.com")
    bob_id, _bob_auth = register(client, "fty411-bob@example.com")
    bob_target = _seed_via_factory(db_engine, bob_id)
    listing = client.post(
        _candidates_url(bob_id, bob_target), headers={"Authorization": _bob_auth}, json={}
    )
    bob_ref = listing.json()["prior_corrections"][0]["source_ref"]

    # Alice targets Bob's item with his own prior-correction reference.
    resp = client.post(
        _re_resolve_url(bob_id, bob_target),
        headers={"Authorization": alice_auth},
        json={"source_ref": bob_ref},
    )

    assert resp.status_code == 404
