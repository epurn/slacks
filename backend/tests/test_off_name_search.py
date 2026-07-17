"""Tests for brand-name-only Open Food Facts resolution (FTY-369).

Network-free, in three layers:

- **OFF name-search client** (`OffClient.search_by_name`): request building (identity
  only, sanitized, URL-encoded, page-size bounded), response parsing/validation, and
  the same energy/plausibility gate the barcode path enforces — all against a stubbed
  transport.
- **Egress safety**: the identity-query variants a candidate egresses are item
  identity only and each already survives `sanitize_query`.
- **`OffNameResolver` + the official step**: the brand/product-compatibility gate
  rejects a foreign product and accepts a compatible one, the cache serves a repeat
  without an external call, and the tier order is preserved — OFF name search fills the
  branded `product_database` gap between official source and reference, never
  displacing an official-source result, and a foreign hit falls through to the next
  tier.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.branded_routing import identity_variants, is_evidence_brand_compatible
from app.estimator.evidence_utils import _content_hash
from app.estimator.fdc import ProductFacts, normalize_query
from app.estimator.food_resolvers import FoodResolver, OffNameResolver
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolveStep
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.off import (
    OFF_SOURCE,
    OffClient,
    OffResponseError,
    OffSettings,
    OffTransientError,
)
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import CandidateDraft, Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
    sanitize_query,
)
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product

_OAT_BAR_CODE = "0687456789012"


# ---------------------------------------------------------------------------
# OFF name-search client (stubbed transport)
# ---------------------------------------------------------------------------


def _search_reply(*products: dict[str, Any]) -> dict[str, Any]:
    """An OFF ``cgi/search.pl`` reply body carrying ``products``."""

    return {"count": len(products), "products": list(products)}


def _oat_bar_product() -> dict[str, Any]:
    return {
        "code": _OAT_BAR_CODE,
        "product_name": "Made Good Chocolate Chip Soft Baked Oat Bars",
        "serving_quantity": 40,
        "nutriments": {
            "energy-kcal_100g": 300.0,
            "proteins_100g": 6.0,
            "carbohydrates_100g": 60.0,
            "fat_100g": 10.0,
        },
    }


class _RecordingTransport:
    """A fake transport recording its call and returning a canned reply (or raising)."""

    def __init__(self, reply: dict[str, Any] | Exception) -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _client(reply: dict[str, Any] | Exception) -> tuple[OffClient, _RecordingTransport]:
    transport = _RecordingTransport(reply)
    return OffClient(OffSettings(), transport=transport), transport


def test_search_by_name_maps_products_to_name_keyed_facts() -> None:
    client, _ = _client(_search_reply(_oat_bar_product()))

    matches = client.search_by_name("Made Good chocolate chip oat bars")

    assert len(matches) == 1
    facts = matches[0]
    assert facts.source == OFF_SOURCE
    # A name hit is referenced by the product's own code — a stable open_food_facts ref.
    assert facts.source_ref == f"open_food_facts:{_OAT_BAR_CODE}"
    # Name-keyed, not barcode-keyed: the cache key is the normalized name query and the
    # dedicated barcode column stays empty so it never collides with a barcode row.
    assert facts.query_key == "made good chocolate chip oat bars"
    assert facts.barcode is None
    assert facts.facts.calories == pytest.approx(300.0)
    assert facts.default_serving_g == pytest.approx(40.0)
    assert facts.content_hash


def test_search_by_name_sends_identity_only_sanitized_query() -> None:
    client, transport = _client(_search_reply(_oat_bar_product()))

    # Control characters / smuggled newlines are stripped at the sanitize chokepoint.
    client.search_by_name("made good\n\toat bars")

    call = transport.calls[0]
    assert "/cgi/search.pl?" in call["url"]
    assert "search_terms=made+good+oat+bars" in call["url"] or "made%20good%20oat%20bars" in call[
        "url"
    ].replace("+", "%20")
    # The window is bounded, and JSON is requested.
    assert "page_size=10" in call["url"]
    assert "json=1" in call["url"]
    # No raw newline/tab and no secret rides along — item identity only.
    assert "%0A" not in call["url"] and "%09" not in call["url"]
    assert "X-Api-Key" not in call["headers"]


def test_search_by_name_drops_energyless_and_implausible_products() -> None:
    client, _ = _client(
        _search_reply(
            {"code": "1", "product_name": "No Energy", "nutriments": {"proteins_100g": 5.0}},
            {
                "code": "2",
                "product_name": "kJ mislabelled",
                "nutriments": {"energy-kcal_100g": 1500.0},
            },
            _oat_bar_product(),
        )
    )

    matches = client.search_by_name("oat bars")

    # Only the usable, plausible product survives — no code / no energy / over-cap dropped.
    assert [m.source_ref for m in matches] == [f"open_food_facts:{_OAT_BAR_CODE}"]


def test_search_by_name_drops_product_without_code() -> None:
    client, _ = _client(
        _search_reply({"product_name": "Codeless", "nutriments": {"energy-kcal_100g": 200.0}})
    )

    assert client.search_by_name("oat bars") == ()


def test_search_by_name_disabled_source_makes_no_call() -> None:
    transport = _RecordingTransport(_search_reply(_oat_bar_product()))
    client = OffClient(OffSettings(enabled=False), transport=transport)

    assert client.search_by_name("oat bars") == ()
    assert transport.calls == []


def test_search_by_name_empty_query_makes_no_call() -> None:
    client, transport = _client(_search_reply(_oat_bar_product()))

    assert client.search_by_name("   ") == ()
    assert transport.calls == []


def test_search_by_name_transient_error_maps_to_off_transient() -> None:
    client, _ = _client(FetchTransientError("boom"))

    with pytest.raises(OffTransientError):
        client.search_by_name("oat bars")


@pytest.mark.parametrize("error", [FetchResponseError("bad"), FetchPolicyError("blocked")])
def test_search_by_name_response_and_policy_errors_map_to_off_response(error: Exception) -> None:
    client, _ = _client(error)

    with pytest.raises(OffResponseError):
        client.search_by_name("oat bars")


def test_search_by_name_malformed_body_maps_to_off_response() -> None:
    client, _ = _client({"products": "not_a_list"})

    with pytest.raises(OffResponseError):
        client.search_by_name("oat bars")


# ---------------------------------------------------------------------------
# Egress safety: identity-only, sanitized query variants
# ---------------------------------------------------------------------------


def test_identity_variants_are_identity_only_and_sanitized() -> None:
    candidate = CandidateDraft(
        name="chocolate chip oat bars",
        brand="Made Good",
        quantity_text="1 serving",
        amount=1,
    )

    variants = identity_variants(candidate)

    assert variants  # at least the name+brand base
    for variant in variants:
        # Every egressed variant already survives the shared sanitize_query chokepoint
        # unchanged (no control chars, bounded), so nothing extra can smuggle through.
        assert variant == sanitize_query(variant)
        # It is item identity only — the parsed name/brand tokens, never personal context.
        lowered = variant.lower()
        assert "made" in lowered and "good" in lowered
        for personal in ("weight", "goal", "calorie", "kg", "profile", "@"):
            assert personal not in lowered


# ---------------------------------------------------------------------------
# OffNameResolver: compatibility gate + cache (real session)
# ---------------------------------------------------------------------------


class _FakeNameSource:
    """A scripted, network-free :class:`NameProductSource` recording its queries."""

    def __init__(
        self,
        products: list[tuple[str, str, float, float | None]],
        *,
        enabled: bool = True,
        error: Exception | None = None,
    ) -> None:
        self._products = products
        self._enabled = enabled
        self._error = error
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def search_by_name(self, query: str) -> tuple[ProductFacts, ...]:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        query_key = normalize_query(query)
        out: list[ProductFacts] = []
        for name, code, calories, serving in self._products:
            facts = NutritionFacts(calories=calories, protein_g=0.0, carbs_g=0.0, fat_g=0.0)
            source_ref = f"open_food_facts:{code}"
            out.append(
                ProductFacts(
                    source=OFF_SOURCE,
                    source_ref=source_ref,
                    query_key=query_key,
                    description=name,
                    facts=facts,
                    default_serving_g=serving,
                    content_hash=_content_hash(source_ref, facts),
                    barcode=None,
                )
            )
        return tuple(out)


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _brand_accept(name: str) -> bool:
    return is_evidence_brand_compatible(name, name="oat bars", brand="Made Good")


def test_resolver_accepts_compatible_hit_and_caches(session: Session) -> None:
    source = _FakeNameSource([("Made Good Oat Bars", _OAT_BAR_CODE, 300.0, 40.0)])
    resolver = OffNameResolver(session=session, source=source)

    resolved = resolver.resolve_compatible("Made Good oat bars", accept=_brand_accept)

    assert resolved is not None
    assert resolved.product.source_ref == f"open_food_facts:{_OAT_BAR_CODE}"
    # It was cached as a global, name-keyed products row (barcode column empty).
    cached = session.scalars(select(Product).where(Product.source == OFF_SOURCE)).one()
    assert cached.barcode is None
    assert cached.query_key == "made good oat bars"

    # A repeat with an equivalent query is served from the cache — no second OFF call.
    again = resolver.resolve_compatible("Made Good oat bars", accept=_brand_accept)
    assert again is not None
    assert source.queries == ["Made Good oat bars"]


def test_resolver_rejects_foreign_product(session: Session) -> None:
    # OFF returns a different brand's product for the query — a wrong-product hit.
    source = _FakeNameSource([("Nature Valley Granola Bars", "9990000000001", 450.0, 40.0)])
    resolver = OffNameResolver(session=session, source=source)

    resolved = resolver.resolve_compatible("Made Good oat bars", accept=_brand_accept)

    assert resolved is None
    # A rejected product is never cached — the chain must be free to try the next tier.
    assert session.scalars(select(Product)).all() == []


# ---------------------------------------------------------------------------
# Chain ordering — full pipeline through the official step
# ---------------------------------------------------------------------------

_OFFICIAL_URL = "https://example.com/menu/oat-bar"
_PAGE_FACTS = {
    "basis": "per_100g",
    "product_name": "Made Good Oat Bar",
    "calories": 250.0,
    "protein_g": 6.0,
    "carbs_g": 60.0,
    "fat_g": 10.0,
    "serving_size_amount": 40.0,
    "serving_size_unit": "g",
}


class _FakeFoodSource:
    """A scripted USDA stand-in that always misses (branded item defers)."""

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        return None


class _FakeSearchProvider:
    def __init__(self, result: SearchResult) -> None:
        self._result = result
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    @property
    def available(self) -> bool:
        return True

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product", "restaurant_item"),
            enabled=True,
            available=True,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._result


class _RecordingFetcher:
    def __init__(self, text: str = "Oat bar — 250 kcal per 100 g") -> None:
        self._text = text
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        return self._text


def _branded_oat_bar_item() -> dict[str, object]:
    return {
        "type": "food",
        "name": "chocolate chip oat bars",
        "brand": "Made Good",
        "quantity_text": "1 serving",
        "unit": "serving",
        "amount": 1,
    }


def _seed_event(client: TestClient, email: str, raw_text: str) -> tuple[uuid.UUID, uuid.UUID]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": raw_text},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


def _pipeline(
    session: Session,
    *,
    search_provider: _FakeSearchProvider,
    off_source: _FakeNameSource,
    estimates: list[dict[str, Any] | LLMError],
    reference_enabled: bool = False,
) -> Pipeline:
    parse_provider = FakeProvider(
        responses=[
            {"disposition": "parsed", "confidence": 0.95, "items": [_branded_oat_bar_item()]}
        ]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    official_provider = FakeProvider(responses=estimates)
    resolver = FoodResolver(session=session, source=_FakeFoodSource())
    fetcher = _RecordingFetcher()
    official_step = OfficialSourceResolveStep(
        provider=official_provider,
        search_provider=search_provider,
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(enabled=reference_enabled),
        fetch_fn=fetcher,
        reference_fetch_fn=fetcher,
        off_name_resolver=OffNameResolver(session=session, source=off_source),
    )
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence(session: Session, event_id: uuid.UUID) -> EvidenceSource:
    return session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()


def test_branded_barcode_less_product_resolves_from_off_name_search(
    client: TestClient, session: Session
) -> None:
    # Official source misses (no candidate URL); OFF name search fills the branded gap.
    search = _FakeSearchProvider(SearchResult(status=SearchStatus.PARTIAL))
    off_source = _FakeNameSource([("Made Good Oat Bars", _OAT_BAR_CODE, 300.0, 40.0)])
    pipeline = _pipeline(session, search_provider=search, off_source=off_source, estimates=[])
    user_id, event_id = _seed_event(client, "off-name-ok@example.com", "an oat bar")

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories is not None
    # 1 serving (40 g) of 300 kcal/100g = 120 kcal — inside the ~90-130 band.
    assert 90.0 <= food.calories <= 130.0

    evidence = _evidence(session, event_id)
    assert evidence.source_type == "product_database"
    assert evidence.source_ref == f"open_food_facts:{_OAT_BAR_CODE}"
    # OFF was consulted by name, and the hit was cached as a global name-keyed row.
    assert off_source.queries
    cached = session.scalars(select(Product).where(Product.source == OFF_SOURCE)).one()
    assert cached.barcode is None


def test_official_source_result_is_not_displaced_by_off_name_search(
    client: TestClient, session: Session
) -> None:
    # Official source resolves; the lower-ranked product_database tier is never consulted.
    search = _FakeSearchProvider(
        SearchResult(
            status=SearchStatus.SUCCESS,
            candidates=(SearchCandidate(url=_OFFICIAL_URL, title="Made Good Oat Bar"),),
        )
    )
    off_source = _FakeNameSource([("Made Good Oat Bars", _OAT_BAR_CODE, 300.0, 40.0)])
    pipeline = _pipeline(
        session,
        search_provider=search,
        off_source=off_source,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}],
    )
    user_id, event_id = _seed_event(client, "official-wins@example.com", "an oat bar")

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
    # OFF name search was never reached — official source (rank 2) is higher-preference.
    assert off_source.queries == []
    assert session.scalars(select(Product).where(Product.source == OFF_SOURCE)).all() == []


def test_foreign_off_hit_is_rejected_and_chain_continues_to_model_prior(
    client: TestClient, session: Session
) -> None:
    # Official misses, OFF returns a foreign product (rejected), reference disabled → the
    # chain continues to an honest model-prior estimate rather than the wrong product.
    search = _FakeSearchProvider(SearchResult(status=SearchStatus.PARTIAL))
    off_source = _FakeNameSource([("Nature Valley Granola Bars", "9990000000001", 450.0, 40.0)])
    pipeline = _pipeline(
        session,
        search_provider=search,
        off_source=off_source,
        estimates=[
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _PAGE_FACTS,
                "assumptions": ["estimated from model prior"],
            }
        ],
    )
    user_id, event_id = _seed_event(client, "off-foreign@example.com", "an oat bar")

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    # OFF was consulted (its name query egressed) but the foreign product was not
    # committed and nothing was cached for it.
    assert off_source.queries
    assert session.scalars(select(Product).where(Product.source == OFF_SOURCE)).all() == []
