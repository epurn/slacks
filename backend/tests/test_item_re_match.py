"""Item re-match tests: list alternatives + re-resolve (FTY-093).

Exercise the estimator capability and the thin backend operation across the trust
boundary, proving the acceptance criteria:

- listing surfaces a **bounded** set of energy-bearing USDA candidates beyond the
  resolver's first pick, with an optional query override for a corrected term, and
  caches each candidate so the write half can re-derive it;
- listing egresses **no personal context** — provider queries carry item identity
  only, through the FTY-079 ``sanitize_query`` chokepoint;
- re-resolve recomputes calories/macros from the chosen source at the item's current
  portion, rewrites its ``evidence_sources`` provenance, re-snapshots ``*_estimated``
  to the new values, writes **no** ``user_edit`` row, and is deterministic for the same
  reference;
- re-resolve appends one immutable ``re_match`` audit row that **supersedes** any prior
  ``user_edit`` — so an edited-then-rematched item honestly reads ``is_edited == false``,
  while a genuine edit made *after* a re-match marks it edited again;
- the re-matched item keeps its ``id`` / ``log_event_id`` / portion / timeline slot;
- a reference the server cannot re-derive (and any attempt to pass facts directly) is
  rejected with no mutation, and re-resolve issues no network egress;
- a re-match the new source cannot cost routes to clarification, not a fabricated
  number;
- cross-user / unknown item on either operation fails closed as ``404``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import CandidateType, CorrectionSource, DerivedItemStatus, SourceType
from app.estimator.fdc import (
    FDC_SOURCE,
    FdcClient,
    FdcResponseError,
    FdcSettings,
    FdcTransientError,
    ProductFacts,
)
from app.estimator.food_serving import NutritionFacts
from app.estimator.re_match import (
    AlternativesUnavailable,
    ReMatchCapability,
    ReMatchNeedsClarification,
    SourceNotResolvable,
    UsdaCandidateProvider,
)
from app.estimator.search import sanitize_query
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product
from app.models.identity import User
from app.services import item_read_model
from tests.corrections_helpers import register, seed_evidence, seed_food_item

# ---------------------------------------------------------------------------
# Fixtures + fakes
# ---------------------------------------------------------------------------


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


class FakeListSource:
    """A scripted, network-free :class:`FoodListSource` recording its queries."""

    def __init__(self, matches: list[ProductFacts], *, enabled: bool = True) -> None:
        self._matches = matches
        self._enabled = enabled
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def list_matches(self, query: str) -> list[ProductFacts]:
        self.queries.append(query)
        if not self._enabled:
            return []
        return list(self._matches)


class FailingListSource:
    """A network-free :class:`FoodListSource` whose ``list_matches`` always raises.

    Models a USDA transient hiccup / unusable response during listing (the same
    exceptions ``FdcClient.list_matches`` raises) so the listing degrade-path can be
    exercised without a network.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error

    @property
    def enabled(self) -> bool:
        return True

    def list_matches(self, query: str) -> list[ProductFacts]:
        raise self._error


def _facts(source_ref: str, *, calories: float, name: str = "candidate") -> ProductFacts:
    """A USDA candidate fact sheet with clean per-100g values for exact assertions."""

    return ProductFacts(
        source=FDC_SOURCE,
        source_ref=source_ref,
        query_key="ignored",
        description=name,
        facts=NutritionFacts(calories=calories, protein_g=5.0, carbs_g=10.0, fat_g=2.0),
        default_serving_g=150.0,
        content_hash=f"hash-{source_ref}",
    )


def _capability(session: Session, source: FakeListSource) -> ReMatchCapability:
    return ReMatchCapability(session=session, providers=(UsdaCandidateProvider(source),))


def _user(session: Session, user_id: str) -> User:
    user = session.get(User, uuid.UUID(user_id))
    assert user is not None
    return user


def _add_candidate_product(
    session: Session,
    *,
    source_ref: str,
    calories_per_100g: float,
    protein: float = 6.0,
    carbs: float = 12.0,
    fat: float = 3.0,
    default_serving_g: float | None = 150.0,
    source: str = FDC_SOURCE,
) -> Product:
    """Seed a global ``products`` candidate row addressable by ``source_ref``."""

    product = Product(
        source=source,
        source_ref=source_ref,
        query_key=source_ref,
        barcode=None,
        description="re-matched food",
        calories_per_100g=calories_per_100g,
        protein_per_100g=protein,
        carbs_per_100g=carbs,
        fat_per_100g=fat,
        default_serving_g=default_serving_g,
        content_hash=f"hash-{source_ref}",
    )
    session.add(product)
    session.commit()
    return product


# ---------------------------------------------------------------------------
# (a) List alternatives
# ---------------------------------------------------------------------------


def test_list_alternatives_surfaces_multiple_usda_candidates(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "rematch-list@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)
    source = FakeListSource(
        [
            _facts("usda_fdc:1", calories=110.0, name="turkey breast"),
            _facts("usda_fdc:2", calories=150.0, name="ground turkey"),
            _facts("usda_fdc:3", calories=170.0, name="turkey bacon"),
        ]
    )

    candidates = _capability(session, source).list_alternatives(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        query_override="turkey",
    )

    # Multiple candidates beyond the resolver's first energy-bearing match.
    assert [c.source_ref for c in candidates] == ["usda_fdc:1", "usda_fdc:2", "usda_fdc:3"]
    first = candidates[0]
    assert first.source_type == SourceType.TRUSTED_NUTRITION_DATABASE.value
    assert first.basis == "per_100g"
    assert first.name == "turkey breast"
    assert first.facts.calories == pytest.approx(110.0)

    # Each surfaced candidate is cached server-side, addressable by source_ref.
    cached = session.scalars(select(Product).where(Product.source == FDC_SOURCE)).all()
    assert {p.source_ref for p in cached} == {"usda_fdc:1", "usda_fdc:2", "usda_fdc:3"}


def test_list_alternatives_is_bounded(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "rematch-bound@example.com")
    item_id = seed_food_item(db_engine, user_id)
    many = [_facts(f"usda_fdc:{i}", calories=100.0 + i) for i in range(25)]
    capability = ReMatchCapability(
        session=session,
        providers=(UsdaCandidateProvider(FakeListSource(many)),),
        max_alternatives=10,
    )

    candidates = capability.list_alternatives(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
    )

    assert len(candidates) == 10


def test_list_alternatives_egresses_only_sanitized_item_identity(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "rematch-egress@example.com")
    # The seeded item's name is the only identity that may egress without an override.
    item_id = seed_food_item(db_engine, user_id)
    source = FakeListSource([_facts("usda_fdc:1", calories=130.0)])
    capability = _capability(session, source)
    current_user = _user(session, user_id)

    capability.list_alternatives(
        owner_id=uuid.UUID(user_id), current_user=current_user, item_id=item_id
    )
    # An override that tries to smuggle multi-line / structured personal context.
    smuggled = "turkey\nprofile: 90kg\tgoal: lose"
    capability.list_alternatives(
        owner_id=uuid.UUID(user_id),
        current_user=current_user,
        item_id=item_id,
        query_override=smuggled,
    )

    # Without an override only the item's own name reaches the provider.
    assert source.queries[0] == "white rice"
    # The override passes through the FTY-079 chokepoint: control chars stripped, so no
    # multi-line structured context survives; the egressed string is exactly sanitized.
    assert "\n" not in source.queries[1]
    assert "\t" not in source.queries[1]
    assert source.queries[1] == sanitize_query(smuggled)


def test_fdc_list_matches_excludes_energy_less_results() -> None:
    # The list-candidates path classifies foods exactly like the first-match resolver:
    # an energy-less food is not an offerable match.
    reply = {
        "foods": [
            {
                "fdcId": 1,
                "description": "turkey breast",
                "foodNutrients": [{"nutrientId": 1008, "value": 135.0}],
            },
            {
                "fdcId": 2,
                "description": "mystery (no energy)",
                "foodNutrients": [{"nutrientId": 1003, "value": 9.0}],
            },
            {
                "fdcId": 3,
                "description": "ground turkey",
                "foodNutrients": [{"nutrientId": 1008, "value": 200.0}],
            },
        ]
    }

    def _transport(url: str, **_kwargs: Any) -> dict[str, Any]:
        return reply

    client = FdcClient(FdcSettings(api_key=SecretStr("k")), transport=_transport)
    matches = client.list_matches("turkey")

    assert [m.source_ref for m in matches] == ["usda_fdc:1", "usda_fdc:3"]


@pytest.mark.parametrize(
    "error",
    [FdcTransientError("fdc_transient_error"), FdcResponseError("fdc_response_error")],
)
def test_list_alternatives_source_failure_raises_unavailable(
    client: TestClient, db_engine: Engine, session: Session, error: Exception
) -> None:
    # A transient/unusable candidate-source failure during listing is surfaced as a
    # dedicated unavailable signal (router → 503), never swallowed into an empty list
    # that would falsely read as "no alternatives exist".
    user_id, _auth = register(client, "rematch-source-down@example.com")
    item_id = seed_food_item(db_engine, user_id)

    capability = ReMatchCapability(
        session=session, providers=(UsdaCandidateProvider(FailingListSource(error)),)
    )
    with pytest.raises(AlternativesUnavailable):
        capability.list_alternatives(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
        )


# ---------------------------------------------------------------------------
# (b) Re-resolve
# ---------------------------------------------------------------------------


def test_re_resolve_recomputes_rewrites_provenance_and_resnapshots(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "rematch-rr@example.com")
    # An item resolved to the WRONG source at 2 servings, with old provenance.
    item_id = seed_food_item(
        db_engine,
        user_id,
        amount=2.0,
        calories=300.0,
        protein_g=10.0,
        carbs_g=40.0,
        fat_g=5.0,
    )
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type="trusted_nutrition_database",
        source_ref="usda_fdc:OLD",
    )
    # The chosen candidate: 120 kcal / 6 P / 12 C / 3 F per 100 g, 150 g default serving.
    _add_candidate_product(session, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    item = _capability(session, FakeListSource([])).re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        source_ref="usda_fdc:NEW",
    )

    # Recomputed at the current portion: 2 × 150 g = 300 g → ×1.2 of per-100g facts.
    assert item.grams == pytest.approx(300.0)
    assert item.calories == pytest.approx(360.0)
    assert item.protein_g == pytest.approx(18.0)
    assert item.carbs_g == pytest.approx(36.0)
    assert item.fat_g == pytest.approx(9.0)
    # *_estimated is RE-SNAPSHOTTED to the new computed values (not the captured-once rule).
    assert item.calories_estimated == pytest.approx(360.0)
    assert item.protein_g_estimated == pytest.approx(18.0)
    # Identity + portion + timeline slot preserved.
    assert item.id == item_id
    assert item.amount == pytest.approx(2.0)
    assert item.status == DerivedItemStatus.RESOLVED

    # Provenance rewritten to the new source (in place: still one evidence row).
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].source_ref == "usda_fdc:NEW"
    assert evidence[0].source_type == "trusted_nutrition_database"
    assert evidence[0].calories_per_100g == pytest.approx(120.0)
    assert evidence[0].content_hash == "hash-usda_fdc:NEW"

    # Honest provenance: NOT user_edited, and no user_edit correction row written.
    assert (
        session.scalars(
            select(Correction).where(
                Correction.derived_food_item_id == item_id,
                Correction.source == CorrectionSource.USER_EDIT,
            )
        ).all()
        == []
    )


def test_re_resolve_resets_a_stale_as_logged_basis_to_per_100g(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    """FTY-316: a re-match to a database Product always resets basis + field_provenance.

    The prior evidence row is a FTY-279/301 ``as_logged`` user-text/model-prior row with
    a heterogeneous per-field origin map. A re-match target is always a per-100g
    ``Product``, so the rewritten row must honestly read ``per_100g`` over the new
    snapshot, not carry the stale ``as_logged`` label and origin map over it.
    """

    user_id, _auth = register(client, "rematch-basis-reset@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type="user_text",
        source_ref="user_text:stale",
        basis="as_logged",
        field_provenance={"calories": "user_stated", "protein_g": "estimated"},
    )
    _add_candidate_product(session, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    item = _capability(session, FakeListSource([])).re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        source_ref="usda_fdc:NEW",
    )

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].basis == "per_100g"
    assert evidence[0].field_provenance is None
    assert evidence[0].source_ref == "usda_fdc:NEW"
    assert evidence[0].calories_per_100g == pytest.approx(120.0)
    assert evidence[0].assumptions is None
    # Recompute/headline behaviour is unaffected by the basis reset.
    assert item.calories == pytest.approx(360.0)


def test_re_resolve_leaves_an_already_per_100g_basis_unchanged(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    """Regression: a re-match of an already-``per_100g`` item is unaffected by FTY-316."""

    user_id, _auth = register(client, "rematch-basis-noop@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type="trusted_nutrition_database",
        source_ref="usda_fdc:OLD",
        basis="per_100g",
        field_provenance=None,
    )
    _add_candidate_product(session, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    _capability(session, FakeListSource([])).re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        source_ref="usda_fdc:NEW",
    )

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].basis == "per_100g"
    assert evidence[0].field_provenance is None
    assert evidence[0].source_ref == "usda_fdc:NEW"
    assert evidence[0].calories_per_100g == pytest.approx(120.0)


def test_re_resolve_appends_a_re_match_audit_row(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "rematch-audit@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    _add_candidate_product(session, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    _capability(session, FakeListSource([])).re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        source_ref="usda_fdc:NEW",
    )

    # The re-match is recorded as exactly one immutable `re_match` audit row (keyed on the
    # headline calories value), never a `user_edit` — so the item is not marked edited.
    rows = session.scalars(
        select(Correction).where(Correction.derived_food_item_id == item_id)
    ).all()
    assert len(rows) == 1
    assert rows[0].source == CorrectionSource.RE_MATCH
    assert rows[0].field == "calories"
    assert rows[0].old_value == pytest.approx(300.0)
    assert rows[0].new_value == pytest.approx(360.0)
    assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is False


def test_re_resolve_supersedes_a_pre_existing_user_edit(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    """Edit-then-rematch: the re-match reconciles the stale edit, clearing ``is_edited``."""

    user_id, _auth = register(client, "rematch-supersede@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    _add_candidate_product(session, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    # A pre-existing manual value override marks the item edited.
    session.add(
        Correction(
            user_id=uuid.UUID(user_id),
            item_type=CandidateType.FOOD,
            derived_food_item_id=item_id,
            field="calories",
            old_value=300.0,
            new_value=250.0,
            source=CorrectionSource.USER_EDIT,
        )
    )
    session.commit()
    assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is True

    _capability(session, FakeListSource([])).re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        source_ref="usda_fdc:NEW",
    )

    # The new source is the latest word: the stale edit is superseded, is_edited is false.
    session.expire_all()
    assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is False


def test_user_edit_after_re_match_marks_item_edited_again(
    client: TestClient, db_engine: Engine
) -> None:
    """A genuine edit *after* a re-match still counts — re-match is not a permanent latch."""

    user_id, auth = register(client, "rematch-then-edit@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    factory = create_session_factory(db_engine)
    with factory() as s:
        _add_candidate_product(s, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    re_resolve = client.post(
        _re_resolve_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"source_ref": "usda_fdc:NEW"},
    )
    assert re_resolve.status_code == 200
    assert re_resolve.json()["is_edited"] is False

    edit = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}",
        headers={"Authorization": auth},
        json={"field": "calories", "value": 250.0},
    )
    assert edit.status_code == 200
    assert edit.json()["is_edited"] is True


def test_re_resolve_is_deterministic(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "rematch-determ@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    _add_candidate_product(session, source_ref="usda_fdc:NEW", calories_per_100g=120.0)
    capability = _capability(session, FakeListSource([]))
    current_user = _user(session, user_id)

    first = capability.re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=current_user,
        item_id=item_id,
        source_ref="usda_fdc:NEW",
    )
    first_values = (first.calories, first.protein_g, first.carbs_g, first.fat_g, first.grams)
    second = capability.re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=current_user,
        item_id=item_id,
        source_ref="usda_fdc:NEW",
    )

    assert (
        second.calories,
        second.protein_g,
        second.carbs_g,
        second.fat_g,
        second.grams,
    ) == first_values


def test_re_resolve_rejects_unre_derivable_reference(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "rematch-unknown-ref@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)

    with pytest.raises(SourceNotResolvable):
        _capability(session, FakeListSource([])).re_resolve(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            source_ref="usda_fdc:NOT_CACHED",
        )

    # Nothing mutated: the item still carries its original value.
    session.expire_all()
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == pytest.approx(300.0)


def test_re_resolve_costs_serving_less_source_via_carried_grams(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    """FTY-386: a count item re-matched to a serving-less source costs via carried grams.

    A ``1 sandwich`` item whose prior resolution already estimated a 180 g portion is
    re-aimed at a USDA candidate with **no** ``default_serving_g``. Rather than dead-end
    on ``needs_clarification``, re-resolve carries the item's own ``grams`` forward and
    scales the new source's per-100g facts by it: the item completes, ``grams`` is
    unchanged, provenance is rewritten, ``*_estimated`` re-snapshots, the ``re_match``
    audit row is appended, and the rewritten evidence carries the content-free
    carried-grams assumption label.
    """

    user_id, _auth = register(client, "rematch-carried@example.com")
    # A count-quantity item (1 "sandwich") resolved to a 180 g portion by its prior source.
    item_id = seed_food_item(db_engine, user_id, amount=1.0, calories=300.0, grams=180.0)
    with create_session_factory(db_engine)() as setup:
        seeded = setup.get(DerivedFoodItem, item_id)
        assert seeded is not None
        seeded.unit = "sandwich"
        seeded.quantity_text = "1 sandwich"
        setup.commit()
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type="trusted_nutrition_database",
        source_ref="usda_fdc:OLD",
    )
    # The chosen candidate: 120 kcal / 6 P / 12 C / 3 F per 100 g, but NO serving size.
    _add_candidate_product(
        session, source_ref="usda_fdc:NOSERV", calories_per_100g=120.0, default_serving_g=None
    )

    source = FakeListSource([])
    item = _capability(session, source).re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        source_ref="usda_fdc:NOSERV",
    )

    # No network egress: the carried grams are read from the persisted item + cache,
    # never fetched (re-resolve issues no listing query).
    assert source.queries == []
    # Costed via the carried 180 g portion (×1.8 of the per-100g facts); grams unchanged.
    assert item.grams == pytest.approx(180.0)
    assert item.calories == pytest.approx(216.0)
    assert item.protein_g == pytest.approx(10.8)
    assert item.carbs_g == pytest.approx(21.6)
    assert item.fat_g == pytest.approx(5.4)
    # *_estimated re-snapshots to the new computed values (FTY-093 re-resolution rule).
    assert item.calories_estimated == pytest.approx(216.0)
    assert item.protein_g_estimated == pytest.approx(10.8)
    assert item.status == DerivedItemStatus.RESOLVED

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].source_ref == "usda_fdc:NOSERV"
    assert evidence[0].calories_per_100g == pytest.approx(120.0)
    # Honest provenance: the portion mass predates the new source, and FTY-316 resets hold.
    # The label is a fixed content-free token — no item name, quantity text, or value.
    assert evidence[0].assumptions == ["portion_grams_carried"]
    assert evidence[0].basis == "per_100g"
    assert evidence[0].field_provenance is None

    # One re_match audit row, no user_edit (unchanged re-resolution semantics).
    rows = session.scalars(
        select(Correction).where(Correction.derived_food_item_id == item_id)
    ).all()
    assert len(rows) == 1
    assert rows[0].source == CorrectionSource.RE_MATCH


def test_re_resolve_mass_quantity_costs_via_resolve_grams_not_carried(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    """Regression (FTY-386): a mass-quantity item costs from its own quantity, unchanged.

    A ``200 g`` item is resolvable by ``resolve_grams`` regardless of the chosen source's
    serving size, so it takes the unchanged first-preference path even against a
    serving-less source: it costs at 200 g (its stated mass, **not** the carried 999 g),
    and the rewritten evidence clears ``assumptions`` — the carried-grams fallback never
    fires for a measured quantity.
    """

    user_id, _auth = register(client, "rematch-mass@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=200.0, calories=300.0, grams=999.0)
    with create_session_factory(db_engine)() as setup:
        seeded = setup.get(DerivedFoodItem, item_id)
        assert seeded is not None
        seeded.unit = "g"
        seeded.quantity_text = "200 g"
        setup.commit()
    _add_candidate_product(
        session, source_ref="usda_fdc:NOSERV", calories_per_100g=120.0, default_serving_g=None
    )

    item = _capability(session, FakeListSource([])).re_resolve(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        source_ref="usda_fdc:NOSERV",
    )

    # Costed from the stated 200 g (×2.0 of per-100g facts), never the carried 999 g.
    assert item.grams == pytest.approx(200.0)
    assert item.calories == pytest.approx(240.0)
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].assumptions is None  # measured path clears assumptions as before


def test_re_resolve_routes_to_clarification_when_uncostable(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    """Residual (FTY-386): a count item with **no** carried grams still clarifies.

    When the chosen source cannot cost the quantity **and** the item carries no usable
    portion mass (``grams`` is ``None`` — an unresolved / as-logged prior item), the
    genuine-indeterminate residual stays: re-resolve raises ``ReMatchNeedsClarification``
    deterministically and nothing mutates.
    """

    user_id, _auth = register(client, "rematch-clarify@example.com")
    # A count quantity (2 servings) with NO carried grams and a serving-less source.
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0, grams=None)
    _add_candidate_product(
        session, source_ref="usda_fdc:NOSERV", calories_per_100g=120.0, default_serving_g=None
    )

    with pytest.raises(ReMatchNeedsClarification):
        _capability(session, FakeListSource([])).re_resolve(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            source_ref="usda_fdc:NOSERV",
        )

    session.expire_all()
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == pytest.approx(300.0)  # no fabricated number
    assert item.grams is None  # nothing mutated


# ---------------------------------------------------------------------------
# Backend operation (thin pass-through) — authz + trust boundary
# ---------------------------------------------------------------------------


def _candidates_url(user_id: str, item_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/derived-items/food/{item_id}/source-candidates"


def _re_resolve_url(user_id: str, item_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/derived-items/food/{item_id}/re-resolve"


def test_re_resolve_api_happy_path(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rematch-api@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type="trusted_nutrition_database",
        source_ref="usda_fdc:OLD",
    )
    factory = create_session_factory(db_engine)
    with factory() as s:
        _add_candidate_product(s, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    resp = client.post(
        _re_resolve_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"source_ref": "usda_fdc:NEW"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["calories"] == pytest.approx(360.0)
    assert body["is_edited"] is False
    # FTY-092 read-model reports the NEW source through the existing item DTO.
    assert body["source"]["ref"] == "usda_fdc:NEW"
    assert body["source"]["source_type"] == "trusted_nutrition_database"


def test_re_resolve_api_clears_a_pre_existing_edit(client: TestClient, db_engine: Engine) -> None:
    """End-to-end: edit an item (is_edited true), re-match it, and is_edited reads false."""

    user_id, auth = register(client, "rematch-api-edit@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    factory = create_session_factory(db_engine)
    with factory() as s:
        _add_candidate_product(s, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    edit = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}",
        headers={"Authorization": auth},
        json={"field": "calories", "value": 250.0},
    )
    assert edit.status_code == 200
    assert edit.json()["is_edited"] is True

    resp = client.post(
        _re_resolve_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"source_ref": "usda_fdc:NEW"},
    )
    assert resp.status_code == 200
    # The contract guarantee: a re-matched item honestly reads un-edited, even after an edit.
    assert resp.json()["is_edited"] is False


def test_re_resolve_api_rejects_client_supplied_facts(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "rematch-inject@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)

    resp = client.post(
        _re_resolve_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"source_ref": "usda_fdc:NEW", "calories": 50.0},
    )

    # extra=forbid: a client cannot inject nutrition values through this path.
    assert resp.status_code == 422


def test_re_resolve_api_unknown_reference_is_422(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rematch-api-unknown@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)

    resp = client.post(
        _re_resolve_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"source_ref": "usda_fdc:NOPE"},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "source_not_resolvable"


def test_list_alternatives_api_empty_when_source_disabled(
    client: TestClient, db_engine: Engine
) -> None:
    # No FDC key in the test environment → the USDA provider is disabled → no candidates.
    user_id, auth = register(client, "rematch-api-empty@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = client.post(
        _candidates_url(user_id, item_id),
        headers={"Authorization": auth},
        json={},
    )

    assert resp.status_code == 200
    # No FDC key and no prior correction for this user → both surfaces are empty.
    assert resp.json() == {"candidates": [], "prior_corrections": []}


def test_list_alternatives_api_503_when_source_fails(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A transient/unusable candidate-source failure during listing routes to a clear,
    # retryable 503 (calm by default) rather than an undocumented 500 or a misleading
    # 200 empty list.
    user_id, auth = register(client, "rematch-api-503@example.com")
    item_id = seed_food_item(db_engine, user_id)

    def _failing_capability(session: Session) -> ReMatchCapability:
        return ReMatchCapability(
            session=session,
            providers=(UsdaCandidateProvider(FailingListSource(FdcTransientError("down"))),),
        )

    monkeypatch.setattr("app.routers.re_match.build_re_match_capability", _failing_capability)

    resp = client.post(
        _candidates_url(user_id, item_id),
        headers={"Authorization": auth},
        json={},
    )

    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "alternatives_unavailable"


def test_re_resolve_unknown_item_is_404(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rematch-missing@example.com")

    resp = client.post(
        _re_resolve_url(user_id, uuid.uuid4()),
        headers={"Authorization": auth},
        json={"source_ref": "usda_fdc:NEW"},
    )

    assert resp.status_code == 404


def test_cross_user_operations_fail_closed(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "rematch-alice@example.com")
    bob_id, _bob_auth = register(client, "rematch-bob@example.com")
    bob_item = seed_food_item(db_engine, bob_id, calories=200.0)
    factory = create_session_factory(db_engine)
    with factory() as s:
        _add_candidate_product(s, source_ref="usda_fdc:NEW", calories_per_100g=120.0)

    # Alice presents a valid token but targets Bob's item, via both her path and his.
    via_bob = client.post(
        _re_resolve_url(bob_id, bob_item),
        headers={"Authorization": alice_auth},
        json={"source_ref": "usda_fdc:NEW"},
    )
    via_alice = client.post(
        _re_resolve_url(alice_id, bob_item),
        headers={"Authorization": alice_auth},
        json={"source_ref": "usda_fdc:NEW"},
    )
    listing = client.post(
        _candidates_url(bob_id, bob_item),
        headers={"Authorization": alice_auth},
        json={},
    )

    assert via_bob.status_code == 404
    assert via_alice.status_code == 404
    assert listing.status_code == 404

    # No mutation to Bob's item.
    with factory() as s:
        item = s.get(DerivedFoodItem, bob_item)
        assert item is not None
        assert item.calories == pytest.approx(200.0)


def test_re_match_endpoints_require_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = register(client, "rematch-noauth@example.com")
    item_id = seed_food_item(db_engine, user_id)

    candidates = client.post(_candidates_url(user_id, item_id), json={})
    re_resolve = client.post(_re_resolve_url(user_id, item_id), json={"source_ref": "usda_fdc:NEW"})

    assert candidates.status_code == 401
    assert re_resolve.status_code == 401
