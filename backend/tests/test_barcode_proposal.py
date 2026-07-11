"""Barcode exact-evidence proposal generation tests (FTY-308).

Exercise the barcode ``Make it exact`` propose path with **stubbed** OFF / fallback
providers, proving the acceptance criteria:

- a confident OFF match yields an ``exact`` ``product_database`` proposal with a stable
  ``proposal_ref``, costed at the item's current amount when possible;
- a repeat barcode uses the ``products`` cache and makes no external OFF call;
- the OFF request carries only the normalized barcode + configured headers — no
  personal context egresses; the identity fallback receives item identity only;
- no-match / disabled-source / unusable-facts cases yield a ``fallback`` proposal with a
  content-free ``failure_reason`` and honest low-trust provenance when the fallback
  resolves;
- no exact match and no fallback yields a ``none`` no-proposal response with no mutation;
- an uncostable current amount yields a proposal requiring an amount (no guess);
- cross-user / unknown / non-food / voided-parent items fail closed as ``404``;
- the propose route never mutates the item — applying the returned proposal through
  FTY-307 is what updates it in place.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import ExactEvidenceKind, ExactEvidenceQuality, SourceType
from app.estimator.barcode_proposal import (
    FAILURE_INVALID,
    FAILURE_NO_MATCH,
    FAILURE_SOURCE_UNAVAILABLE,
    BarcodeProposalGenerator,
    FallbackFacts,
)
from app.estimator.exact_evidence import decode_proposal_ref
from app.estimator.fdc import ProductFacts
from app.estimator.food_resolvers import BarcodeResolver, _ResolvedProduct
from app.estimator.food_serving import NutritionFacts
from app.estimator.identity_fallback import IdentityFallbackResolver
from app.estimator.off import OFF_SOURCE, OffClient, OffResponseError, OffSettings
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product
from app.models.identity import User
from app.models.log_events import LogEvent
from app.routers import exact_evidence
from app.services import barcode_proposal as barcode_proposal_service
from tests.corrections_helpers import register, seed_evidence, seed_exercise_item, seed_food_item

SECRET = "test-proposal-secret"  # noqa: S105 (test signing key, not a real credential)
BARCODE = "0123456789012"


# ---------------------------------------------------------------------------
# Fixtures + stubs
# ---------------------------------------------------------------------------


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _off_product(
    *,
    calories: float = 539.0,
    default_serving_g: float | None = 15.0,
    barcode: str = BARCODE,
) -> _ResolvedProduct:
    """A cache/OFF-shaped :class:`_ResolvedProduct` the exact path maps to a proposal."""

    product = Product(
        source=OFF_SOURCE,
        source_ref=f"{OFF_SOURCE}:{barcode}",
        query_key=barcode,
        barcode=barcode,
        description="Hazelnut spread",
        calories_per_100g=calories,
        protein_per_100g=6.3,
        carbs_per_100g=57.5,
        fat_per_100g=30.9,
        default_serving_g=default_serving_g,
        content_hash="hash-off",
    )
    return _ResolvedProduct(product=product, fetched_at=datetime.now(UTC))


class FakeExactSource:
    """A network-free :class:`BarcodeExactSource` recording the barcodes it saw."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        product: _ResolvedProduct | None = None,
        error: Exception | None = None,
    ) -> None:
        self._enabled = enabled
        self._product = product
        self._error = error
        self.barcodes: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def resolve_product(self, barcode: str) -> _ResolvedProduct | None:
        self.barcodes.append(barcode)
        if self._error is not None:
            raise self._error
        return self._product


class FakeFallback:
    """A network-free :class:`IdentityFallbackSource` recording the identities it saw."""

    def __init__(self, facts: FallbackFacts | None = None) -> None:
        self._facts = facts
        self.identities: list[str] = []

    def resolve(self, identity: str) -> FallbackFacts | None:
        self.identities.append(identity)
        return self._facts


def _reference_fallback() -> FallbackFacts:
    return FallbackFacts(
        facts=NutritionFacts(calories=250.0, protein_g=4.0, carbs_g=30.0, fat_g=12.0),
        source_type=SourceType.REFERENCE_SOURCE.value,
        source_ref="reference_source:https://ex.example/nutrition",
        content_hash="hash-ref",
        default_serving_g=40.0,
        serving_label=None,
        assumptions=("barcode exact match unavailable; estimated from reference source",),
    )


def _generator(exact: FakeExactSource, fallback: FakeFallback) -> BarcodeProposalGenerator:
    return BarcodeProposalGenerator(exact_source=exact, fallback_source=fallback)


def _propose_url(user_id: str, item_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/barcode"


def _apply_url(user_id: str, item_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/apply"


def _install(client: TestClient, generator: BarcodeProposalGenerator) -> None:
    """Override the propose route's generator dependency with a network-free stub."""

    client.app.dependency_overrides[  # type: ignore[attr-defined]
        exact_evidence.get_barcode_proposal_generator
    ] = lambda: generator


def _transient_item(owner_id: uuid.UUID, *, name: str = "hazelnut spread") -> DerivedFoodItem:
    """A minimal in-memory food item for pure generator tests (no DB flush)."""

    return DerivedFoodItem(
        id=uuid.uuid4(),
        log_event_id=uuid.uuid4(),
        user_id=owner_id,
        name=name,
        quantity_text="",
        unit="g",
        amount=15.0,
    )


# ---------------------------------------------------------------------------
# (a) Generator logic — source selection, quality, failure reasons
# ---------------------------------------------------------------------------


def test_confident_off_match_yields_exact_product_database_proposal() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id)
    exact = FakeExactSource(product=_off_product())
    fallback = FakeFallback()

    outcome = _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode=BARCODE)

    assert outcome.failure_reason is None
    assert exact.barcodes == [BARCODE]
    assert fallback.identities == []  # exact hit: fallback never consulted
    proposal = outcome.proposal
    assert proposal is not None
    assert proposal.quality is ExactEvidenceQuality.EXACT
    assert proposal.kind is ExactEvidenceKind.BARCODE
    assert proposal.source_type == SourceType.PRODUCT_DATABASE.value
    assert proposal.source_ref == f"{OFF_SOURCE}:{BARCODE}"
    assert proposal.owner_id == owner_id
    assert proposal.item_id == item.id
    assert proposal.facts.calories == 539.0
    assert proposal.facts.default_serving_g == 15.0


def test_no_match_falls_back_with_barcode_no_match_reason() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id)
    exact = FakeExactSource(product=None)
    fallback = FakeFallback(_reference_fallback())

    outcome = _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode=BARCODE)

    assert outcome.failure_reason == FAILURE_NO_MATCH
    assert fallback.identities  # identity fallback consulted
    proposal = outcome.proposal
    assert proposal is not None
    assert proposal.quality is ExactEvidenceQuality.FALLBACK
    assert proposal.source_type == SourceType.REFERENCE_SOURCE.value
    assert proposal.source_ref.startswith("reference_source:")


def test_disabled_source_falls_back_with_source_unavailable_reason() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id)
    exact = FakeExactSource(enabled=False, product=_off_product())
    fallback = FakeFallback(_reference_fallback())

    outcome = _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode=BARCODE)

    assert exact.barcodes == []  # a disabled source is never queried
    assert outcome.failure_reason == FAILURE_SOURCE_UNAVAILABLE
    assert outcome.proposal is not None
    assert outcome.proposal.quality is ExactEvidenceQuality.FALLBACK


def test_source_error_propagates_rather_than_masking_as_a_miss() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id)
    exact = FakeExactSource(error=OffResponseError("off_response_error"))
    fallback = FakeFallback(_reference_fallback())

    # A source outage is never disguised as an honest miss/fallback: it propagates so
    # the route can surface a retryable 503.
    with pytest.raises(OffResponseError):
        _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode=BARCODE)
    assert fallback.identities == []  # no silent fallback on a source error


def test_invalid_barcode_is_barcode_invalid_not_a_source_call() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id)
    exact = FakeExactSource(product=_off_product())
    fallback = FakeFallback(_reference_fallback())

    outcome = _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode="12")

    assert exact.barcodes == []  # not a plausible GTIN: never reaches the source
    assert outcome.failure_reason == FAILURE_INVALID
    assert outcome.proposal is not None
    assert outcome.proposal.quality is ExactEvidenceQuality.FALLBACK


def test_no_match_and_no_fallback_yields_no_proposal() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id)
    exact = FakeExactSource(product=None)
    fallback = FakeFallback(None)

    outcome = _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode=BARCODE)

    assert outcome.proposal is None
    assert outcome.failure_reason == FAILURE_NO_MATCH


def test_fallback_receives_sanitized_identity_only() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id, name="Hazelnut Spread 400g")
    exact = FakeExactSource(product=None)
    fallback = FakeFallback(_reference_fallback())

    _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode=BARCODE)

    # Item identity only — never profile / history / raw log text.
    assert fallback.identities == ["hazelnut spread 400g"]


def test_nameless_item_produces_no_fallback() -> None:
    owner_id = uuid.uuid4()
    item = _transient_item(owner_id, name="!!!")  # no usable food token after sanitizing
    exact = FakeExactSource(product=None)
    fallback = FakeFallback(_reference_fallback())

    outcome = _generator(exact, fallback).generate(owner_id=owner_id, item=item, barcode=BARCODE)

    assert fallback.identities == []
    assert outcome.proposal is None


# ---------------------------------------------------------------------------
# (b) Cache-first OFF resolution — no external call on a repeat barcode
# ---------------------------------------------------------------------------


class CountingOffSource:
    """A network-free OFF ``BarcodeSource`` that counts its lookups."""

    def __init__(self, facts: Any) -> None:
        self._facts = facts
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, barcode: str) -> Any:
        self.lookups.append(barcode)
        return self._facts


def _seed_off_product(session: Session, barcode: str = BARCODE) -> None:
    session.add(
        Product(
            source=OFF_SOURCE,
            source_ref=f"{OFF_SOURCE}:{barcode}",
            query_key=barcode,
            barcode=barcode,
            description="Cached spread",
            calories_per_100g=500.0,
            protein_per_100g=5.0,
            carbs_per_100g=55.0,
            fat_per_100g=30.0,
            default_serving_g=15.0,
            content_hash="cached-hash",
        )
    )
    session.commit()


def test_cached_barcode_makes_no_external_off_call(session: Session) -> None:
    _seed_off_product(session)
    source = CountingOffSource(facts=None)
    resolver = BarcodeResolver(session=session, source=source)

    resolved = resolver.resolve_product(BARCODE)

    assert resolved is not None
    assert resolved.product.source_ref == f"{OFF_SOURCE}:{BARCODE}"
    assert source.lookups == []  # cache hit: OFF never queried


def test_uncached_barcode_queries_off_once(session: Session) -> None:
    facts = ProductFacts(
        source=OFF_SOURCE,
        source_ref=f"{OFF_SOURCE}:{BARCODE}",
        query_key=BARCODE,
        description="Fetched spread",
        facts=NutritionFacts(calories=539.0, protein_g=6.3, carbs_g=57.5, fat_g=30.9),
        default_serving_g=15.0,
        content_hash="fetched-hash",
        barcode=BARCODE,
    )
    source = CountingOffSource(facts=facts)
    resolver = BarcodeResolver(session=session, source=source)

    resolved = resolver.resolve_product(BARCODE)

    assert resolved is not None
    assert source.lookups == [BARCODE]  # miss: one barcode-only lookup


# ---------------------------------------------------------------------------
# (c) OFF egress carries only the barcode + configured headers
# ---------------------------------------------------------------------------


def test_off_request_carries_only_barcode_and_headers() -> None:
    captured: dict[str, Any] = {}

    def _transport(url: str, **kwargs: Any) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        return {
            "status": 1,
            "product": {
                "product_name": "Hazelnut spread",
                "nutriments": {
                    "energy-kcal_100g": 539.0,
                    "proteins_100g": 6.3,
                    "carbohydrates_100g": 57.5,
                    "fat_100g": 30.9,
                },
                "serving_quantity": 15.0,
            },
        }

    client = OffClient(OffSettings(), transport=_transport, resolver=lambda *a, **k: [])
    result = client.lookup(BARCODE)

    assert result is not None
    # The URL is the pinned product endpoint for exactly this barcode — the barcode is
    # the only variable, and there is no profile/history/query context anywhere in it.
    assert f"/api/v2/product/{BARCODE}.json" in captured["url"]
    assert captured["url"].endswith(
        "fields=code,product_name,nutriments,serving_quantity,serving_size"
    )
    # Only the non-secret identifying user-agent header is sent.
    assert captured["headers"] == {"User-Agent": OffSettings().user_agent}


# ---------------------------------------------------------------------------
# (d) Route + service — read shape, costing, no mutation, 404s
# ---------------------------------------------------------------------------


def _seed_resolved_item(
    db_engine: Engine,
    user_id: str,
    *,
    amount: float | None = 20.0,
    unit: str | None = "g",
) -> uuid.UUID:
    item_id = seed_food_item(db_engine, user_id, amount=amount, calories=300.0)
    # Widen the item's unit so the mass/count path can be steered per test.
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        item.unit = unit
        item.quantity_text = ""
        session.add(item)
        session.commit()
    seed_evidence(db_engine, user_id, item_id, source_type="model_prior", source_ref="model_prior")
    return item_id


def test_exact_proposal_route_costs_current_amount_and_never_mutates(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, auth = register(client, "bc-exact@example.com")
    item_id = _seed_resolved_item(db_engine, user_id, amount=20.0, unit="g")
    _install(client, _generator(FakeExactSource(product=_off_product()), FakeFallback()))

    resp = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["quality"] == "exact"
    assert body["failure_reason"] is None
    assert body["proposal_ref"]  # a stable, non-empty signed reference
    assert body["can_cost_current_amount"] is True
    preview = body["preview"]
    assert preview["source"]["source_type"] == "product_database"
    # 20 g of 539 kcal/100 g = 107.8 kcal.
    assert preview["calories"] == pytest.approx(107.8)
    assert preview["amount"] == 20.0

    # The propose route never mutates the item: its stored numbers are unchanged.
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == 300.0


def test_uncostable_amount_requires_amount_without_guessing(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "bc-uncostable@example.com")
    # A count unit with no default serving on the product cannot resolve to grams.
    item_id = _seed_resolved_item(db_engine, user_id, amount=2.0, unit="scoop")
    product = _off_product(default_serving_g=None)
    _install(client, _generator(FakeExactSource(product=product), FakeFallback()))

    resp = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["quality"] == "exact"
    assert body["can_cost_current_amount"] is False
    # The preview shows the source facts on the proposal's basis, not a guessed portion.
    assert body["preview"]["basis"] == "per_100g"
    assert body["preview"]["calories"] == 539.0


def test_fallback_proposal_route_labels_low_trust_source(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "bc-fallback@example.com")
    item_id = _seed_resolved_item(db_engine, user_id, amount=20.0, unit="g")
    _install(client, _generator(FakeExactSource(product=None), FakeFallback(_reference_fallback())))

    resp = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["quality"] == "fallback"
    assert body["failure_reason"] == FAILURE_NO_MATCH
    assert body["preview"]["source"]["source_type"] == "reference_source"
    assert body["proposal_ref"]


def test_no_proposal_route_is_calm_and_content_free(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, auth = register(client, "bc-none@example.com")
    item_id = _seed_resolved_item(db_engine, user_id, amount=20.0, unit="g")
    _install(client, _generator(FakeExactSource(product=None), FakeFallback(None)))

    resp = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["quality"] == "none"
    assert body["failure_reason"] == FAILURE_NO_MATCH
    assert body["preview"] is None
    assert body["proposal_ref"] == ""  # nothing applyable

    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == 300.0  # unchanged


def test_applying_the_returned_exact_proposal_updates_the_item_in_place(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, auth = register(client, "bc-apply@example.com")
    item_id = _seed_resolved_item(db_engine, user_id, amount=20.0, unit="g")
    _install(client, _generator(FakeExactSource(product=_off_product()), FakeFallback()))

    proposed = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    ).json()
    apply_resp = client.post(
        _apply_url(user_id, item_id),
        json={"proposal_ref": proposed["proposal_ref"]},
        headers={"Authorization": auth},
    )

    assert apply_resp.status_code == 200
    # The apply route (FTY-307) is what mutates the item, in place.
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert any(row.source_type == "product_database" for row in evidence)
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == pytest.approx(107.8)


@pytest.mark.parametrize("bad_body", [{"barcode": ""}, {"barcode": BARCODE, "calories": 5}])
def test_request_validation_errors_are_content_free(
    client: TestClient, db_engine: Engine, bad_body: dict[str, Any]
) -> None:
    user_id, auth = register(client, "bc-validate@example.com")
    item_id = _seed_resolved_item(db_engine, user_id)
    _install(client, _generator(FakeExactSource(product=_off_product()), FakeFallback()))

    resp = client.post(
        _propose_url(user_id, item_id), json=bad_body, headers={"Authorization": auth}
    )

    assert resp.status_code == 422
    assert resp.json() == {"detail": {"error": "invalid_request"}}


def test_already_source_backed_item_is_not_upgradeable(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, auth = register(client, "bc-ineligible@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=20.0)
    # A product_database item is already source-backed: it keeps the normal levers.
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type="product_database",
        source_ref="open_food_facts:0000000000000",
    )
    _install(client, _generator(FakeExactSource(product=_off_product()), FakeFallback()))

    resp = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    )

    assert resp.status_code == 422
    assert resp.json() == {"detail": {"error": "not_upgradeable"}}
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == 200.0  # unchanged


def test_source_outage_surfaces_retryable_503(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "bc-503@example.com")
    item_id = _seed_resolved_item(db_engine, user_id, amount=20.0, unit="g")
    exact = FakeExactSource(error=OffResponseError("off_response_error"))
    _install(client, _generator(exact, FakeFallback(_reference_fallback())))

    resp = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    )

    assert resp.status_code == 503
    assert resp.json() == {"detail": {"error": "source_unavailable"}}


def test_cross_user_item_is_not_found(client: TestClient, db_engine: Engine) -> None:
    owner_id, _owner_auth = register(client, "bc-owner@example.com")
    _other_id, other_auth = register(client, "bc-other@example.com")
    item_id = _seed_resolved_item(db_engine, owner_id)
    _install(client, _generator(FakeExactSource(product=_off_product()), FakeFallback()))

    resp = client.post(
        _propose_url(owner_id, item_id),
        json={"barcode": BARCODE},
        headers={"Authorization": other_auth},
    )

    assert resp.status_code == 404


def test_unknown_and_exercise_items_are_not_found(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "bc-unknown@example.com")
    _install(client, _generator(FakeExactSource(product=_off_product()), FakeFallback()))

    unknown = client.post(
        _propose_url(user_id, uuid.uuid4()),
        json={"barcode": BARCODE},
        headers={"Authorization": auth},
    )
    exercise_id = seed_exercise_item(db_engine, user_id)
    exercise = client.post(
        _propose_url(user_id, exercise_id),
        json={"barcode": BARCODE},
        headers={"Authorization": auth},
    )

    assert unknown.status_code == 404
    assert exercise.status_code == 404  # food-only route


def test_voided_parent_item_is_not_found(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, auth = register(client, "bc-voided@example.com")
    item_id = _seed_resolved_item(db_engine, user_id)
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    event = session.get(LogEvent, item.log_event_id)
    assert event is not None
    event.voided_at = datetime.now(UTC)
    session.add(event)
    session.commit()
    _install(client, _generator(FakeExactSource(product=_off_product()), FakeFallback()))

    resp = client.post(
        _propose_url(user_id, item_id), json={"barcode": BARCODE}, headers={"Authorization": auth}
    )

    assert resp.status_code == 404


def test_service_signs_a_verifiable_reference(
    db_engine: Engine, session: Session, client: TestClient
) -> None:
    user_id, _auth = register(client, "bc-sign@example.com")
    item_id = _seed_resolved_item(db_engine, user_id, amount=20.0, unit="g")
    user = session.get(User, uuid.UUID(user_id))
    assert user is not None

    dto = barcode_proposal_service.propose_barcode_evidence(
        session,
        owner_id=user.id,
        current_user=user,
        item_id=item_id,
        barcode=BARCODE,
        secret=SECRET,
        generator=_generator(FakeExactSource(product=_off_product()), FakeFallback()),
    )

    decoded = decode_proposal_ref(dto.proposal_ref, SECRET)
    assert decoded.owner_id == user.id
    assert decoded.item_id == item_id
    assert decoded.quality is ExactEvidenceQuality.EXACT


# ---------------------------------------------------------------------------
# (e) Production identity fallback resolver — reuses reference / model-prior tiers
# ---------------------------------------------------------------------------


class FakeSearchProvider:
    """A scripted, network-free search provider recording the query (FTY-308)."""

    def __init__(
        self, result: SearchResult, *, enabled: bool = True, available: bool = True
    ) -> None:
        self._result = result
        self._enabled = enabled
        self._available = available
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def available(self) -> bool:
        return self._available

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="fake",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product",),
            enabled=self._enabled,
            available=self._available,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._result


def _fetcher(pages: dict[str, str]) -> Callable[[str, ReferenceFetchSettings], str]:
    def _fetch(url: str, _settings: ReferenceFetchSettings) -> str:
        return pages[url]

    return _fetch


def _resolved_payload(basis: str, **facts: Any) -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": 0.9,
        "facts": {"basis": basis, **facts},
        "assumptions": ["a raw provider assumption that must never be persisted"],
    }


def test_resolver_model_prior_maps_to_honest_low_trust_facts() -> None:
    # Search disabled → the reference tier is skipped and the gated model prior runs.
    provider = FakeProvider(
        responses=[
            _resolved_payload("per_100g", calories=539.0, protein_g=6.3, carbs_g=57.5, fat_g=30.9)
        ]
    )
    resolver = IdentityFallbackResolver(
        provider=provider,
        search_provider=FakeSearchProvider(
            SearchResult(status=SearchStatus.SUCCESS, candidates=()), enabled=False
        ),
        reference_fetch_settings=ReferenceFetchSettings(),
    )

    facts = resolver.resolve("hazelnut spread")

    assert facts is not None
    assert facts.source_type == SourceType.MODEL_PRIOR.value
    assert facts.source_ref == "model_prior"
    assert facts.facts.calories == 539.0
    # Provider-authored free-form assumptions are never persisted — a fixed label only.
    assert facts.assumptions == ("barcode exact match unavailable; estimated from model prior",)


def test_resolver_reference_source_maps_from_a_fetched_page() -> None:
    url = "https://ref.example/spread"
    provider = FakeProvider(
        responses=[
            _resolved_payload(
                "per_serving",
                calories=161.0,
                protein_g=1.9,
                carbs_g=17.3,
                fat_g=9.3,
                serving_size_amount=30.0,
                serving_size_unit="g",
            )
        ]
    )
    search = FakeSearchProvider(
        SearchResult(
            status=SearchStatus.SUCCESS,
            candidates=(SearchCandidate(url=url, title="spread nutrition"),),
        )
    )
    resolver = IdentityFallbackResolver(
        provider=provider,
        search_provider=search,
        reference_fetch_settings=ReferenceFetchSettings(),
        reference_fetch_fn=_fetcher({url: "Serving 30 g: 161 kcal"}),
    )

    facts = resolver.resolve("hazelnut spread")

    assert facts is not None
    assert facts.source_type == SourceType.REFERENCE_SOURCE.value
    assert facts.source_ref == f"reference_source:{url}"
    # 161 kcal / 30 g → ~536.7 kcal per 100 g.
    assert facts.facts.calories == pytest.approx(536.6667, rel=1e-3)
    # The identity query carries item identity + the fixed intent only — no personal data.
    assert search.queries == ["hazelnut spread nutrition facts"]


def test_resolver_low_confidence_model_prior_yields_no_fallback() -> None:
    provider = FakeProvider(
        responses=[
            {
                "disposition": "resolved",
                "confidence": 0.2,
                "facts": {"basis": "per_100g", "calories": 539.0},
                "assumptions": [],
            }
        ]
    )
    resolver = IdentityFallbackResolver(
        provider=provider,
        search_provider=FakeSearchProvider(
            SearchResult(status=SearchStatus.SUCCESS, candidates=()), enabled=False
        ),
        reference_fetch_settings=ReferenceFetchSettings(),
    )

    assert resolver.resolve("hazelnut spread") is None


def test_resolver_empty_identity_yields_no_fallback() -> None:
    resolver = IdentityFallbackResolver(
        provider=FakeProvider(responses=[]),
        search_provider=FakeSearchProvider(
            SearchResult(status=SearchStatus.SUCCESS, candidates=()), enabled=False
        ),
        reference_fetch_settings=ReferenceFetchSettings(),
    )

    assert resolver.resolve("!!!") is None
