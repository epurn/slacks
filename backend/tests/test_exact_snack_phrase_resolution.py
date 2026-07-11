"""FTY-315 regression: the exact dogfood snack phrase resolves as plausible intake.

The audited entry completed as ``dill pickle hummus = 2 kcal`` (an FDC pickles row
costing a hummus identity) and ``crackers = 564 kcal`` (four *full servings* instead
of four crackers). These tests drive the real parse/recovery → food-resolution →
official/reference/model-prior pipeline through the production worker entrypoint
with network-free fakes shaped like the audit evidence — a real :class:`FdcClient`
fed the pickles row that must be rejected (FTY-254), search-result candidates whose
snippets state Toppables facts per ``5 crackers (19 g)`` and PC hummus facts per
``30 g`` (FTY-314), a page fetch that 403s or returns a JavaScript shell, and
brand/hint identity search variants (FTY-253) — asserting plausible calorie bands,
honest provenance, and the exact FTY-252 count math instead of the audited numbers.

Natural-language variants of the same snack are covered alongside the exact phrase
so the pipeline cannot pass by special-casing one raw string, and a static scan
asserts no implementation path hardcodes the phrase or its brands. The exact phrase
is user-supplied food-log text the operator explicitly approved as a regression
fixture; it must never appear outside the user-owned raw event and this file.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.branded_routing import RETAILER_BRAND_ALIASES
from app.estimator.fdc import FdcClient, FdcSettings
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_step import FoodResolveStep
from app.estimator.hardened_fetch import FetchResponseError
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import QUANTITY_QUESTION, OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import (
    MODEL_PRIOR_SOURCE,
    MODEL_PRIOR_SOURCE_TYPE,
    REFERENCE_SOURCE_TYPE,
    SNIPPET_ASSUMPTION,
)
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource, Product
from app.settings import EstimatorClarifyMode

#: The exact dogfood phrase from the audited entry — operator-approved as a
#: regression fixture. Minimal food text only: no user ids, timestamps, DB ids,
#: or provider transcripts accompany it, and the redaction assertions below prove
#: it never persists outside the user-owned raw event.
_EXACT_PHRASE = (
    "4 toppabales brand crackers with 1tbsp of dill pickle hummus (PC - Loblaws store brand)"
)

#: The audited bad numbers this suite exists to prevent.
_AUDITED_CRACKERS_KCAL = 564.0
_AUDITED_HUMMUS_KCAL = 2.0
_AUDITED_TOTAL_KCAL = 566.0

#: A marker embedded in every fake snippet, asserted absent from everything
#: persisted — raw snippet text must never be retained (data-retention.md).
_RAW_SNIPPET_SENTINEL = "RAW-SNIPPET-SENTINEL"

_TOPPABLES_URL = "https://reference.example.com/toppables-crackers"
_TOPPABLES_SNIPPET = (
    f"{_RAW_SNIPPET_SENTINEL} Serving Size Per 5 crackers (19 g). "
    "Calories 90. Fat 3.5 g. Carbs 13 g. Protein 1 g."
)
#: What the extraction model transcribes from the Toppables snippet: facts per
#: counted serving ``5 crackers (19 g)`` (FTY-252), matching the audit evidence.
_TOPPABLES_SNIPPET_FACTS = {
    "basis": "per_serving",
    "product_name": "Toppables crackers",
    "calories": 90.0,
    "protein_g": 1.0,
    "carbs_g": 13.0,
    "fat_g": 3.5,
    "serving_size_amount": 19.0,
    "serving_size_unit": "g",
    "serving_count": {"amount": 5.0, "unit": "crackers"},
}

_HUMMUS_URL = "https://reference.example.com/pc-dill-pickle-hummus"
_HUMMUS_SNIPPET = (
    f"{_RAW_SNIPPET_SENTINEL} Serving Size Per 30 g. Calories 80. Fat 6 g. Carbs 4 g. Protein 2 g."
)
#: PC dill pickle hummus facts per 30 g, matching the audit evidence.
_HUMMUS_SNIPPET_FACTS = {
    "basis": "per_serving",
    "product_name": "PC Dill Pickle Hummus",
    "calories": 80.0,
    "protein_g": 2.0,
    "carbs_g": 4.0,
    "fat_g": 6.0,
    "serving_size_amount": 30.0,
    "serving_size_unit": "g",
}

_CRACKER_SNIPPET_ESTIMATE: dict[str, Any] = {
    "disposition": "resolved",
    "confidence": 0.9,
    "facts": _TOPPABLES_SNIPPET_FACTS,
}
_HUMMUS_SNIPPET_ESTIMATE: dict[str, Any] = {
    "disposition": "resolved",
    "confidence": 0.9,
    "facts": _HUMMUS_SNIPPET_FACTS,
}

#: The FDC pickles row from the audit — energy-bearing and plausible, so only the
#: FTY-254 head-noun identity gate (not fixture malformation) can reject it for a
#: hummus query. Public USDA SR Legacy per-100g figures.
_PICKLES_ROW: dict[str, Any] = {
    "fdcId": 11937,
    "description": "Pickles, cucumber, dill or kosher dill",
    "servingSize": 65.0,
    "servingSizeUnit": "g",
    "foodNutrients": [
        {"nutrientId": 1008, "value": 11.0},
        {"nutrientId": 1003, "value": 0.33},
        {"nutrientId": 1005, "value": 2.41},
        {"nutrientId": 1004, "value": 0.2},
    ],
}

#: What the fake FDC returns per normalized query: the pickles row surfaces for
#: hummus (the audited false match) and for plain pickles (a true match); every
#: other query — crackers, Toppables, PB sandwiches — is a clean miss.
_FDC_RESPONSES: dict[str, dict[str, Any]] = {
    "dill pickle hummus": {"foods": [_PICKLES_ROW]},
    "dill pickles": {"foods": [_PICKLES_ROW]},
}


class QueryKeyedTransport:
    """Network-free FDC transport returning the scripted result list per query."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs["payload"]["query"])
        self.queries.append(query)
        return _FDC_RESPONSES.get(query, {"foods": []})


class KeyedSnippetSearchProvider:
    """A network-free search seam routing each query by keyword, like a real engine.

    Rules are ordered ``(keyword, result)`` pairs matched against the lower-cased
    query; an unmatched query returns no results. Queries are recorded so tests can
    assert exactly what identity text egressed.
    """

    def __init__(self, rules: tuple[tuple[str, SearchResult], ...]) -> None:
        self._rules = rules
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
        lowered = query.casefold()
        for keyword, result in self._rules:
            if keyword in lowered:
                return result
        return SearchResult(status=SearchStatus.PARTIAL)


class ForbiddenFetcher:
    """A network-free result-page fetch that always fails with HTTP 403 (the audit)."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        raise FetchResponseError("fetch returned HTTP 403", status_code=403)


class ShellPageFetcher:
    """A fetch that succeeds but returns a factless JavaScript shell (the audit)."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        return "Please enable JavaScript to view this page."


def _no_official_fetch(url: str, settings: object) -> str:
    raise AssertionError(f"official fetch must not run (tier unconfigured): {url}")


def _snippet_result(url: str, title: str, snippet: str) -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=(SearchCandidate(url=url, title=title, snippet=snippet),),
    )


def _search_provider() -> KeyedSnippetSearchProvider:
    return KeyedSnippetSearchProvider(
        (
            # No reference page exists for the PB cracker sandwiches — that
            # variant proves the rough model-prior path stays acceptable.
            ("sandwich", SearchResult(status=SearchStatus.PARTIAL)),
            (
                "toppab",
                _snippet_result(
                    _TOPPABLES_URL, "Toppables Crackers | Nutrition", _TOPPABLES_SNIPPET
                ),
            ),
            ("dill", _snippet_result(_HUMMUS_URL, "PC Dill Pickle Hummus", _HUMMUS_SNIPPET)),
        )
    )


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _seed_event(client: TestClient, email: str, raw_text: str) -> tuple[uuid.UUID, uuid.UUID, str]:
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
    return user_id, uuid.UUID(created.json()["id"]), auth


def _pipeline(
    session: Session,
    *,
    parse_samples: list[dict[str, Any] | LLMError],
    estimates: list[dict[str, Any] | LLMError],
    transport: QueryKeyedTransport,
    search: KeyedSnippetSearchProvider,
    reference_fetcher: ForbiddenFetcher | ShellPageFetcher,
    mode: EstimatorClarifyMode = "estimate_first",
) -> Pipeline:
    """The real parse → food → official/reference pipeline, network seams faked.

    The official-fetch allowlist is left unconfigured, matching the audited
    deployment: branded candidates skip the official tier and reach the reference
    tier, whose result-page fetch then fails or returns a shell — forcing the
    FTY-314 snippet fallback.
    """

    parse_provider = FakeProvider(responses=parse_samples * SELF_CONSISTENCY_FIRST_WINDOW)
    fdc_client = FdcClient(FdcSettings(api_key=SecretStr("test-key")), transport=transport)
    resolver = FoodResolver(session=session, source=fdc_client)
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=estimates),
        search_provider=search,
        fetch_settings=OfficialFetchSettings(),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_no_official_fetch,
        reference_fetch_fn=reference_fetcher,
        clarify_mode=mode,
    )
    return Pipeline(
        [
            ParseStep(parse_provider, policy=ParsePolicySettings(mode=mode)),
            FoodResolveStep(resolver, clarify_mode=mode),
            official_step,
        ]
    )


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence_for(session: Session, food: DerivedFoodItem) -> EvidenceSource:
    return session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == food.id)
    ).one()


def _questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )


def _run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def _persisted_text(session: Session, event_id: uuid.UUID) -> str:
    """Everything the run persisted beyond the raw event, as one searchable string."""

    run = _run(session, event_id)
    parts = [
        f"{run.trace!r} {run.assumptions!r} {run.source_refs!r} "
        f"{run.validation_errors!r} {run.error!r}"
    ]
    for food in _foods(session, event_id):
        evidence = session.scalars(
            select(EvidenceSource).where(EvidenceSource.derived_food_item_id == food.id)
        ).one_or_none()
        if evidence is not None:
            parts.append(f"{evidence.source_ref!r} {evidence.assumptions!r}")
    parts.extend(
        f"{question.question_text!r} {question.options!r}"
        for question in _questions(session, event_id)
    )
    parts.extend(f"{product.description!r}" for product in session.scalars(select(Product)))
    return " ".join(parts)


def _parsed_sample(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"disposition": "parsed", "confidence": 0.93, "items": items}


def _model_prior_estimate(
    calories: float, protein: float, carbs: float, fat: float, assumption: str
) -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": 0.85,
        "facts": {
            "basis": "as_logged",
            "calories": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
        },
        "assumptions": [assumption],
    }


# ---------------------------------------------------------------------------
# The exact dogfood phrase
# ---------------------------------------------------------------------------

#: The audited parse shape for the exact phrase: the parser stranded the product
#: tokens in ``quantity_text`` for the crackers (FTY-253's hint path) and extracted
#: the store-brand marker for the hummus. Wrapped in the messy provider envelope
#: (string numbers, cased enums) the parse-recovery layer must normalize, mirroring
#: real provider output.
_EXACT_PARSE_SAMPLE: dict[str, Any] = {
    "result": {
        "disposition": "Parsed",
        "confidence": "0.93",
        "items": [
            {
                "type": "Food",
                "name": "crackers",
                "quantity_text": "4 toppabales brand",
                "unit": "crackers",
                "amount": "4",
            },
            {
                "type": "Food",
                "name": "dill pickle hummus",
                "brand": "PC - Loblaws store brand",
                "quantity_text": "1tbsp",
                "unit": "tbsp",
                "amount": "1",
            },
        ],
        "clarification_questions": None,
    }
}


def test_exact_dogfood_phrase_resolves_as_plausible_counted_snack(
    client: TestClient, session: Session
) -> None:
    user_id, event_id, auth = _seed_event(client, "fty315-exact@example.com", _EXACT_PHRASE)
    transport = QueryKeyedTransport()
    search = _search_provider()
    reference_fetcher = ForbiddenFetcher()
    extraction_provider = FakeProvider(
        responses=[_CRACKER_SNIPPET_ESTIMATE, _HUMMUS_SNIPPET_ESTIMATE]
    )
    fdc_client = FdcClient(FdcSettings(api_key=SecretStr("test-key")), transport=transport)
    official_step = OfficialSourceResolveStep(
        provider=extraction_provider,
        search_provider=search,
        fetch_settings=OfficialFetchSettings(),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_no_official_fetch,
        reference_fetch_fn=reference_fetcher,
    )
    pipeline = Pipeline(
        [
            ParseStep(
                FakeProvider(responses=[_EXACT_PARSE_SAMPLE] * SELF_CONSISTENCY_FIRST_WINDOW),
                policy=ParsePolicySettings(),
            ),
            FoodResolveStep(FoodResolver(session=session, source=fdc_client)),
            official_step,
        ]
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    # Completed intake under default estimate_first: no failure, no clarification,
    # no generic quantity question.
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []

    foods = {food.name: food for food in _foods(session, event_id)}
    assert set(foods) == {"crackers", "dill pickle hummus"}
    assert {food.status for food in foods.values()} == {DerivedItemStatus.RESOLVED}
    crackers = foods["crackers"]
    hummus = foods["dill pickle hummus"]

    # Four crackers cost by FTY-252 count math against `per 5 crackers (19 g)`:
    # ~72 kcal / 15.2 g — never four full servings, never the audited 564.
    assert crackers.calories == pytest.approx(72.0)
    assert crackers.grams == pytest.approx(15.2)
    assert crackers.calories is not None and crackers.calories < 150.0
    assert crackers.calories != pytest.approx(_AUDITED_CRACKERS_KCAL)

    # One tbsp (≈15 g) of PC hummus at 80 kcal / 30 g: ~40 kcal — a plausible
    # hummus amount in the tens of kcal, never the audited 2 kcal pickles scaling.
    assert hummus.calories == pytest.approx(40.0)
    assert hummus.grams == pytest.approx(15.0)
    assert hummus.calories is not None and 10.0 < hummus.calories < 90.0
    assert hummus.calories != pytest.approx(_AUDITED_HUMMUS_KCAL)

    total = crackers.calories + hummus.calories
    assert total < _AUDITED_TOTAL_KCAL / 2

    # The FDC pickles row was consulted for the hummus identity and rejected
    # (FTY-254): nothing resolved through usda_fdc:11937 and no products cache row
    # was written for the false match.
    assert "dill pickle hummus" in transport.queries
    assert session.scalars(select(Product)).all() == []

    # Honest provenance: both items are snippet-derived reference evidence — the
    # result URL plus the explicit snippet label; exact/trusted-database provenance
    # is not faked for either product.
    crackers_evidence = _evidence_for(session, crackers)
    hummus_evidence = _evidence_for(session, hummus)
    assert crackers_evidence.source_type == REFERENCE_SOURCE_TYPE
    assert crackers_evidence.source_ref == f"{REFERENCE_SOURCE_TYPE}:{_TOPPABLES_URL}"
    assert hummus_evidence.source_type == REFERENCE_SOURCE_TYPE
    assert hummus_evidence.source_ref == f"{REFERENCE_SOURCE_TYPE}:{_HUMMUS_URL}"
    for evidence in (crackers_evidence, hummus_evidence):
        assert SNIPPET_ASSUMPTION in (evidence.assumptions or [])
        assert evidence.product_id is None

    # The page fetch was attempted first and 403ed; the snippet rescued each item.
    assert reference_fetcher.fetched == [_TOPPABLES_URL, _HUMMUS_URL]

    # Identity search egressed only bounded name/brand/hint variants (FTY-253) —
    # the stranded "toppabales brand" hint drives the crackers query, and the raw
    # phrase never leaves through the search seam.
    assert search.queries == [
        "crackers nutrition facts",
        "crackers toppabales brand nutrition facts",
        "dill pickle hummus PC Loblaws store brand nutrition facts",
    ]

    # Redaction: the raw phrase and raw snippet text persist nowhere beyond the
    # user-owned raw event, and no generic quantity question was recorded.
    persisted = _persisted_text(session, event_id)
    assert _EXACT_PHRASE not in persisted
    assert _RAW_SNIPPET_SENTINEL not in persisted
    assert QUANTITY_QUESTION not in persisted
    # The extraction prompts see only bounded snippet/query text, not the raw phrase.
    assert all(_EXACT_PHRASE not in prompt for prompt in extraction_provider.prompts)

    _assert_read_model_serves_the_snack(client, user_id, event_id, auth)


def _assert_read_model_serves_the_snack(
    client: TestClient, user_id: uuid.UUID, event_id: uuid.UUID, auth: str
) -> None:
    """The completed event serves both costed items with reference provenance,
    and the raw phrase appears exactly once — as the user-owned raw event text."""

    event = client.get(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert event.status_code == 200
    assert event.json()["status"] == "completed"
    assert event.json()["raw_text"] == _EXACT_PHRASE

    listing = client.get(
        f"/api/users/{user_id}/log-events/by-date", headers={"Authorization": auth}
    )
    assert listing.status_code == 200
    entry = next(row for row in listing.json() if row["event"]["id"] == str(event_id))
    served = {item["name"]: item for item in entry["items"]}
    assert served["crackers"]["calories"] == pytest.approx(72.0)
    assert served["dill pickle hummus"]["calories"] == pytest.approx(40.0)
    assert {item["source"]["ref"] for item in entry["items"]} == {
        f"{REFERENCE_SOURCE_TYPE}:{_TOPPABLES_URL}",
        f"{REFERENCE_SOURCE_TYPE}:{_HUMMUS_URL}",
    }
    assert listing.text.count(_EXACT_PHRASE) == 1


# ---------------------------------------------------------------------------
# Natural-language variants: the behavior generalizes beyond one raw string
# ---------------------------------------------------------------------------


def _cracker_item(*, quantity_text: str, amount: float, brand: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": "food",
        "name": "crackers",
        "quantity_text": quantity_text,
        "unit": "crackers",
        "amount": amount,
    }
    if brand is not None:
        item["brand"] = brand
    return item


def _hummus_item(
    *,
    name: str = "dill pickle hummus",
    quantity_text: str,
    amount: float,
    brand: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": "food",
        "name": name,
        "quantity_text": quantity_text,
        "unit": "tbsp",
        "amount": amount,
    }
    if brand is not None:
        item["brand"] = brand
    return item


#: Each variant: the raw phrase, a realistic parse, the scripted extraction /
#: model-prior responses (consumed in item order), and per-item expectations of
#: ``(calorie band, source_type)``. Bands are deliberately loose — the contract is
#: a sane, source-labelled estimate, not exact calories forever.
_VARIANT_CASES: list[dict[str, Any]] = [
    {
        "id": "brand-extracted",
        "raw_text": "4 Toppables crackers with 1 tbsp PC dill pickle hummus",
        "items": [
            _cracker_item(quantity_text="4", amount=4, brand="Toppables"),
            _hummus_item(quantity_text="1 tbsp", amount=1, brand="PC"),
        ],
        "estimates": [_CRACKER_SNIPPET_ESTIMATE, _HUMMUS_SNIPPET_ESTIMATE],
        "expected": {
            "crackers": ((55.0, 95.0), REFERENCE_SOURCE_TYPE),
            "dill pickle hummus": ((20.0, 70.0), REFERENCE_SOURCE_TYPE),
        },
    },
    {
        "id": "worded-count-and-article",
        "raw_text": "four toppables crackers and a tablespoon of PC dill pickle hummus",
        "items": [
            _cracker_item(quantity_text="four", amount=4, brand="Toppables"),
            _hummus_item(quantity_text="a tablespoon", amount=1, brand="PC"),
        ],
        "estimates": [_CRACKER_SNIPPET_ESTIMATE, _HUMMUS_SNIPPET_ESTIMATE],
        "expected": {
            "crackers": ((55.0, 95.0), REFERENCE_SOURCE_TYPE),
            "dill pickle hummus": ((20.0, 70.0), REFERENCE_SOURCE_TYPE),
        },
    },
    {
        "id": "terse-with-trailing-retailer",
        "raw_text": "toppables crackers x4 + 1 tbsp dill pickle hummus, Loblaws PC",
        "items": [
            _cracker_item(quantity_text="x4", amount=4, brand="Toppables"),
            _hummus_item(quantity_text="1 tbsp", amount=1, brand="Loblaws PC"),
        ],
        "estimates": [_CRACKER_SNIPPET_ESTIMATE, _HUMMUS_SNIPPET_ESTIMATE],
        "expected": {
            "crackers": ((55.0, 95.0), REFERENCE_SOURCE_TYPE),
            "dill pickle hummus": ((20.0, 70.0), REFERENCE_SOURCE_TYPE),
        },
    },
    {
        # The generic-crackers + measured-range variant; the hummus page fetch
        # returns a JavaScript shell, forcing the snippet fallback.
        "id": "range-amount-shell-page",
        "raw_text": "6 crackers with about 1.5-2 tbsp dill pickle hummus",
        "items": [
            _cracker_item(quantity_text="6 crackers", amount=6),
            _hummus_item(quantity_text="about 1.5-2 tbsp", amount=1.75),
        ],
        "estimates": [
            _model_prior_estimate(78.0, 2.0, 13.0, 2.0, "six typical plain crackers"),
            {"disposition": "unresolved", "confidence": 0.1},
            _HUMMUS_SNIPPET_ESTIMATE,
        ],
        "fetcher": "shell",
        "expected": {
            "crackers": ((55.0, 110.0), MODEL_PRIOR_SOURCE_TYPE),
            "dill pickle hummus": ((45.0, 95.0), REFERENCE_SOURCE_TYPE),
        },
    },
    {
        # No reference evidence exists for this product: a rough, labelled
        # model-prior estimate is the acceptable outcome, not a question.
        "id": "pb-sandwiches-kraft",
        "raw_text": "3 toppables PB sandwiches (kraft)",
        "items": [
            {
                "type": "food",
                "name": "Toppables peanut butter cracker sandwiches",
                "brand": "Kraft",
                "quantity_text": "3",
                "unit": "cracker sandwich",
                "amount": 3,
            }
        ],
        "estimates": [
            _model_prior_estimate(210.0, 6.0, 24.0, 10.0, "three PB cracker sandwiches"),
        ],
        "expected": {
            "Toppables peanut butter cracker sandwiches": (
                (150.0, 320.0),
                MODEL_PRIOR_SOURCE_TYPE,
            ),
        },
    },
    {
        # Counted crackers + measured spread with no brand anywhere: both items
        # rough-estimate from the model prior with explicit provenance.
        "id": "generic-no-brand",
        "raw_text": "4 crackers with 1 tbsp of hummus",
        "items": [
            _cracker_item(quantity_text="4", amount=4),
            _hummus_item(name="hummus", quantity_text="1 tbsp", amount=1),
        ],
        "estimates": [
            _model_prior_estimate(72.0, 2.0, 12.0, 2.0, "four typical plain crackers"),
            _model_prior_estimate(25.0, 1.0, 2.0, 1.5, "one tablespoon of hummus"),
        ],
        "expected": {
            "crackers": ((50.0, 110.0), MODEL_PRIOR_SOURCE_TYPE),
            "hummus": ((10.0, 45.0), MODEL_PRIOR_SOURCE_TYPE),
        },
    },
]


@pytest.mark.parametrize("case", _VARIANT_CASES, ids=lambda case: str(case["id"]))
def test_natural_language_variants_resolve_without_clarification(
    client: TestClient, session: Session, case: dict[str, Any]
) -> None:
    raw_text = str(case["raw_text"])
    user_id, event_id, _ = _seed_event(client, f"fty315-{case['id']}@example.com", raw_text)
    reference_fetcher = ShellPageFetcher() if case.get("fetcher") == "shell" else ForbiddenFetcher()
    pipeline = _pipeline(
        session,
        parse_samples=[_parsed_sample(list(case["items"]))],
        estimates=list(case["estimates"]),
        transport=QueryKeyedTransport(),
        search=_search_provider(),
        reference_fetcher=reference_fetcher,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []

    expected: dict[str, tuple[tuple[float, float], str]] = case["expected"]
    foods = {food.name: food for food in _foods(session, event_id)}
    assert set(foods) == set(expected)
    total = 0.0
    for name, ((low, high), source_type) in expected.items():
        food = foods[name]
        assert food.status == DerivedItemStatus.RESOLVED
        assert food.calories is not None and low <= food.calories <= high
        total += food.calories
        evidence = _evidence_for(session, food)
        assert evidence.source_type == source_type
        if source_type == REFERENCE_SOURCE_TYPE:
            # Snippet-derived reference evidence carries the honest label.
            assert SNIPPET_ASSUMPTION in (evidence.assumptions or [])
        else:
            assert evidence.source_ref == MODEL_PRIOR_SOURCE
            assert any("model prior" in a for a in (evidence.assumptions or []))
    assert total < _AUDITED_TOTAL_KCAL

    persisted = _persisted_text(session, event_id)
    assert raw_text not in persisted
    assert _RAW_SNIPPET_SENTINEL not in persisted
    assert QUANTITY_QUESTION not in persisted


# ---------------------------------------------------------------------------
# Boundary: a genuinely amountless phrase may still clarify under strict
# ---------------------------------------------------------------------------


def test_amountless_boundary_phrase_still_clarifies_under_strict(
    client: TestClient, session: Session
) -> None:
    """`crackers and hummus` carries no stated portion at all. Under default
    estimate_first it rough-estimates (pinned by FTY-292's
    ``test_amountless_crackers_and_hummus_rough_estimates`` and the FTY-302
    corpus); under the strict operator mode the contract-valid non-counted
    outcome — an item-specific optioned clarification — remains."""

    user_id, event_id, _ = _seed_event(
        client, "fty315-amountless-strict@example.com", "crackers and hummus"
    )
    clarify_sample: dict[str, Any] = {
        "disposition": "needs_clarification",
        "confidence": 0.38,
        "items": [
            {"type": "food", "name": "crackers"},
            {"type": "food", "name": "hummus"},
        ],
        "clarification_questions": [
            {
                "text": "How much crackers and hummus should be counted?",
                "options": ["1 snack plate", "2 snack plates", "Crackers only"],
            }
        ],
    }
    pipeline = _pipeline(
        session,
        parse_samples=[clarify_sample],
        estimates=[],
        transport=QueryKeyedTransport(),
        search=_search_provider(),
        reference_fetcher=ForbiddenFetcher(),
        mode="strict",
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert all(food.status is not DerivedItemStatus.RESOLVED for food in _foods(session, event_id))
    questions = _questions(session, event_id)
    assert len(questions) == 1
    question = questions[0]
    # An item-specific, optioned question — never the generic quantity fallback.
    assert question.question_text != QUANTITY_QUESTION
    assert question.options
    assert "How much did you have" not in question.question_text


# ---------------------------------------------------------------------------
# Fixture shape: the pickles row is rejected by identity, not malformation
# ---------------------------------------------------------------------------


def test_fake_pickles_row_is_wellformed_and_rejected_only_for_hummus() -> None:
    """The fixture FDC row must be an energy-bearing, plausible row a naive
    first-match resolver *would* accept — so the hummus rejection below is
    attributable to the FTY-254 head-noun identity gate, not a broken fixture."""

    fdc = FdcClient(FdcSettings(api_key=SecretStr("test-key")), transport=QueryKeyedTransport())

    pickles = fdc.lookup("dill pickles")
    assert pickles is not None
    assert pickles.source_ref == "usda_fdc:11937"
    assert pickles.facts.calories == pytest.approx(11.0)
    assert pickles.default_serving_g == pytest.approx(65.0)

    assert fdc.lookup("dill pickle hummus") is None


# ---------------------------------------------------------------------------
# No string special-case: the phrase and its brands are not hardcoded
# ---------------------------------------------------------------------------

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"

#: The only modules allowed to mention the PC/Loblaws retailer identity in
#: executable strings, and why each is not a special case:
#: - ``branded_routing.py``: the FTY-253 static retailer alias map — bounded
#:   identity-query expansion (brand words only, checked digit-free below),
#:   never an equality gate or nutrition data;
#: - ``parse_prompt.py``: the parse prompt's brand-extraction instruction
#:   example, teaching the general store-brand-marker rule — it supplies no
#:   nutrition values and gates no resolution outcome.
_RETAILER_MENTION_ALLOWLIST = frozenset(
    {
        _APP_ROOT / "estimator" / "branded_routing.py",
        _APP_ROOT / "estimator" / "parse_prompt.py",
    }
)


def _executable_string_literals(source: str) -> list[str]:
    """Every string literal in ``source`` except module/class/function docstrings."""

    tree = ast.parse(source)
    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_ids.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_ids
    ]


def test_no_implementation_special_cases_the_exact_phrase_or_its_brands() -> None:
    """No app-code path may special-case the regression fixture: the exact phrase
    appears nowhere in ``backend/app``, the Toppables product name appears in no
    executable string (docstrings explaining the hint mechanism are prose, not
    behavior), and the PC/Loblaws retailer tokens appear only in the two
    documented identity-only surfaces — never as a nutrition table."""

    app_sources = {
        path: path.read_text(encoding="utf-8") for path in sorted(_APP_ROOT.rglob("*.py"))
    }
    assert app_sources, "backend/app sources must be scannable"

    for path, source in app_sources.items():
        assert _EXACT_PHRASE.casefold() not in source.casefold(), path
        literals = "\n".join(_executable_string_literals(source)).casefold()
        assert "toppab" not in literals, path
        if path not in _RETAILER_MENTION_ALLOWLIST:
            assert "loblaws" not in literals, path

    # The allowed retailer alias map stays identity-only: brand words, never
    # numbers — a nutrition table smuggled in here would trip this.
    for key, aliases in RETAILER_BRAND_ALIASES.items():
        for phrase in (key, *aliases):
            assert not any(char.isdigit() for char in phrase), phrase
