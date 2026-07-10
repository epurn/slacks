"""FTY-326 evidence-tier tools inside the interpretation loop."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import EstimationJobStatus, LogEventStatus
from app.estimator.fdc import ProductFacts
from app.estimator.food_step import FoodResolver, FoodResolveStep
from app.estimator.model_prior import _model_prior
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    NeedsClarification,
    Pipeline,
)
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource

_RAW_SENTINEL = "RAW-FTY326-SECRET sk-secretquery123"
_HUMMUS_URL = "https://source.example.com/products/pc-dill-pickle-hummus"

_HUMMUS_FACTS = {
    "basis": "per_serving",
    "product_name": "Presidents Choice Dill Pickle Hummus",
    "calories": 80.0,
    "protein_g": 2.0,
    "carbs_g": 4.0,
    "fat_g": 6.0,
    "serving_size_amount": 30.0,
    "serving_size_unit": "g",
}

_ROUGH_AS_LOGGED = {
    "basis": "as_logged",
    "calories": 240.0,
    "protein_g": 10.0,
    "carbs_g": 30.0,
    "fat_g": 8.0,
}


class FakeFoodSource:
    """Network-free USDA stand-in."""

    def __init__(self, facts: dict[str, ProductFacts] | None = None) -> None:
        self._facts = facts or {}
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return self._facts.get(query.strip().lower())


class ScriptedSearchProvider:
    """Network-free search seam keyed by sanitized query."""

    def __init__(self, results: dict[str, SearchResult] | None = None) -> None:
        self._results = results or {}
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
            kinds=("named_product",),
            enabled=True,
            available=True,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._results.get(query, SearchResult(status=SearchStatus.PARTIAL))


class RecordingFetcher:
    """Network-free fetch seam."""

    def __init__(self, text: str = "nutrition facts page") -> None:
        self._text = text
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        return self._text


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _success(url: str) -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=(SearchCandidate(url=url, title="result"),),
    )


def _parsed_response(items: list[dict[str, Any]], *, confidence: float) -> dict[str, Any]:
    return {"disposition": "parsed", "confidence": confidence, "items": items}


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


def _run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def _decisions(run: EstimationRun) -> list[dict[str, Any]]:
    return [entry for entry in run.trace if "decision" in entry]


def _find(entries: list[dict[str, Any]], **fields: object) -> list[dict[str, Any]]:
    return [
        entry for entry in entries if all(entry.get(key) == value for key, value in fields.items())
    ]


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence(session: Session, event_id: uuid.UUID) -> list[EvidenceSource]:
    return list(
        session.scalars(select(EvidenceSource).where(EvidenceSource.log_event_id == event_id))
    )


def _questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )


def test_evidence_dead_end_requeries_revised_identity_before_model_prior(
    client: TestClient, session: Session
) -> None:
    """A brand phrasing the old token gate rejected can be revised and accepted."""

    initial_item: dict[str, Any] = {
        "type": "food",
        "name": "dill pickle hummus",
        "brand": "store brand",
        "quantity_text": "1 tbsp",
        "unit": "tbsp",
        "amount": 1,
    }
    revised_item: dict[str, Any] = {**initial_item, "brand": "Presidents Choice"}
    parse_responses: list[dict[str, Any] | LLMError] = []
    parse_responses.extend(
        _parsed_response([initial_item], confidence=0.95)
        for _ in range(SELF_CONSISTENCY_FIRST_WINDOW)
    )
    parse_responses.append(_parsed_response([revised_item], confidence=0.95))
    parse_provider = FakeProvider(responses=parse_responses)
    official_provider = FakeProvider(
        responses=[
            {"disposition": "resolved", "confidence": 0.95, "facts": _HUMMUS_FACTS},
            {"disposition": "resolved", "confidence": 0.95, "facts": _HUMMUS_FACTS},
        ]
    )
    search = ScriptedSearchProvider(
        {
            "dill pickle hummus store brand": _success(_HUMMUS_URL),
            "dill pickle hummus Presidents Choice": _success(_HUMMUS_URL),
        }
    )
    fetcher = RecordingFetcher()
    pipeline = Pipeline(
        [
            ParseStep(parse_provider),
            FoodResolveStep(FoodResolver(session=session, source=FakeFoodSource())),
            OfficialSourceResolveStep(
                provider=official_provider,
                search_provider=search,
                fetch_settings=OfficialFetchSettings(
                    allowed_hosts=frozenset({"source.example.com"})
                ),
                reference_fetch_settings=ReferenceFetchSettings(),
                fetch_fn=fetcher,
                reference_fetch_fn=fetcher,
            ),
        ]
    )
    user_id, event_id = _seed_event(
        client,
        "fty326-requery@example.com",
        f"PC store brand dill pickle hummus {_RAW_SENTINEL}",
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    assert food.calories == pytest.approx(40.0)
    evidence = _evidence(session, event_id)[0]
    assert evidence.source_type == "official_source"
    assert (
        evidence.source_ref
        == "official_source:https://source.example.com/products/pc-dill-pickle-hummus"
    )

    run = _run(session, event_id)
    entries = _decisions(run)
    assert _find(entries, tier="official_source", outcome="rejected_brand_mismatch")
    assert _find(entries, tier="interpretation_session", outcome="requery_revised_identity")
    assert not _find(entries, outcome="skipped_generic")
    assert not _find(entries, tier="model_prior", outcome="accepted")
    assert search.queries.index("dill pickle hummus Presidents Choice") > search.queries.index(
        "dill pickle hummus store brand"
    )
    requery_prompts = [prompt for prompt in parse_provider.prompts if "<evidence_status>" in prompt]
    assert len(requery_prompts) == 1
    assert "official_source: rejected_brand_mismatch" in requery_prompts[0]
    assert "source_desc=" in requery_prompts[0]
    assert "product=Presidents Choice Dill Pickle Hummus" in requery_prompts[0]
    assert "basis=" in requery_prompts[0]
    assert "serving_g=30" in requery_prompts[0]

    persisted = json.dumps(
        {
            "trace": run.trace,
            "source_refs": run.source_refs,
            "assumptions": run.assumptions,
            "evidence_assumptions": evidence.assumptions,
        }
    )
    assert _RAW_SENTINEL not in persisted
    assert "sk-secretquery123" not in persisted
    assert all(_RAW_SENTINEL not in query for query in search.queries)


def test_tier_exhaustion_uses_session_ledger_then_rough_model_prior(
    client: TestClient, session: Session
) -> None:
    """Default estimate-first falls to an honest rough estimate, not clarify."""

    item: dict[str, Any] = {"type": "food", "name": "mystery wrap", "quantity_text": ""}
    parse_responses: list[dict[str, Any] | LLMError] = []
    parse_responses.extend(
        _parsed_response([item], confidence=0.9) for _ in range(SELF_CONSISTENCY_FIRST_WINDOW)
    )
    parse_responses.append(_parsed_response([item], confidence=0.9))
    parse_provider = FakeProvider(responses=parse_responses)
    official_provider = FakeProvider(
        responses=[
            {
                "disposition": "resolved",
                "confidence": 0.85,
                "facts": _ROUGH_AS_LOGGED,
                "assumptions": ["bounded rough wrap estimate"],
            }
        ]
    )
    search = ScriptedSearchProvider()
    fetcher = RecordingFetcher()
    pipeline = Pipeline(
        [
            ParseStep(parse_provider),
            FoodResolveStep(FoodResolver(session=session, source=FakeFoodSource())),
            OfficialSourceResolveStep(
                provider=official_provider,
                search_provider=search,
                fetch_settings=OfficialFetchSettings(
                    allowed_hosts=frozenset({"source.example.com"})
                ),
                reference_fetch_settings=ReferenceFetchSettings(),
                fetch_fn=fetcher,
                reference_fetch_fn=fetcher,
            ),
        ]
    )
    user_id, event_id = _seed_event(
        client, "fty326-rough@example.com", f"had a mystery wrap {_RAW_SENTINEL}"
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    evidence = _evidence(session, event_id)[0]
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == "model_prior"
    assert evidence.basis == "as_logged"
    assert "as_logged_model_prior" in (evidence.assumptions or [])

    model_prior_prompt = official_provider.prompts[-1]
    assert "Evidence gathered before this rough-estimate tool" in model_prior_prompt
    assert "usda_fdc: miss" in model_prior_prompt
    assert "reference_source: partial" in model_prior_prompt
    assert _RAW_SENTINEL not in model_prior_prompt

    run = _run(session, event_id)
    assert _find(
        _decisions(run),
        tier="interpretation_session",
        outcome="requery_identity_unchanged",
    )
    persisted = json.dumps({"trace": run.trace, "assumptions": run.assumptions})
    assert _RAW_SENTINEL not in persisted


@pytest.mark.parametrize(
    ("responses", "detail"),
    [
        ([], "provider_error"),
        ([{"disposition": "unresolved", "confidence": 0.9}], "non_resolved_disposition"),
        (
            [
                {
                    "disposition": "resolved",
                    "confidence": 0.1,
                    "facts": {**_ROUGH_AS_LOGGED, "basis": "per_100g"},
                }
            ],
            "low_confidence",
        ),
        (
            [
                {
                    "disposition": "resolved",
                    "confidence": 0.9,
                    "facts": {**_ROUGH_AS_LOGGED, "basis": "per_100g", "calories": 4000.0},
                }
            ],
            "unusable_facts",
        ),
    ],
)
def test_model_prior_failure_trace_carries_sanitized_reason_detail(
    responses: list[dict[str, Any]], detail: str
) -> None:
    context = EstimationContext(
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text=f"snack {_RAW_SENTINEL}",
    )
    candidate = CandidateDraft(name="snack", quantity_text="")

    with pytest.raises(NeedsClarification):
        _model_prior(
            context,
            candidate,
            ["reference_source returned no confident match"],
            0,
            step_name="official_source_resolve",
            provider=FakeProvider(responses=list(responses)),
            model_prior_confidence_floor=0.6,
            clarify_mode="estimate_first",
            unknown_food_question="Which food was that?",
            quantity_question="How much?",
        )

    entries = [entry for entry in context.trace if "decision" in entry]
    assert _find(entries, tier="model_prior", outcome=detail)
    assert _RAW_SENTINEL not in json.dumps(context.trace)
