"""Shared helpers for the FTY-302 estimate-first representative harness.

The helpers intentionally use the production worker entrypoint and real estimator
steps while replacing every external provider/search/fetch seam with local fakes.
The fixture phrases are synthetic and are stored only as user-owned event text.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimator.exercise_step import ExerciseCalculateStep
from app.estimator.fdc import ProductFacts
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_step import FoodResolveStep
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.pipeline import Pipeline
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.user_text_step import UserTextResolveStep
from app.llm.base import ImageInput, Provider
from app.llm.errors import LLMConfigurationError, LLMError
from app.llm.providers.fake import FakeProvider
from app.models.identity import UserProfile
from app.settings import EstimatorClarifyMode

CORPUS_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "estimate_first_representative" / "corpus.json"
)
MODES: tuple[EstimatorClarifyMode, ...] = ("estimate_first", "balanced", "strict")
DEFAULT_TEST_WEIGHT_KG = 70.0


class FakeFoodSource:
    """A network-free USDA stand-in that intentionally misses every query."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return None


class DisabledSearchProvider:
    """A disabled search seam; any search attempt is recorded and returns no hit."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return False

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="none",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product", "restaurant_item"),
            enabled=False,
            available=False,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return SearchResult(status=SearchStatus.PARTIAL)


class StaticModelPriorProvider(Provider):
    """Provider fake that returns scripted estimates, then a safe synthetic default."""

    name = "static_model_prior"

    def __init__(self, responses: Sequence[dict[str, Any]] = ()) -> None:
        super().__init__(timeout_seconds=1.0, max_retries=0)
        self._responses: deque[dict[str, Any]] = deque(responses)
        self.prompts: list[str] = []

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if images:
            raise AssertionError("estimate-first representative harness does not use images")
        self.prompts.append(prompt)
        if self._responses:
            return self._responses.popleft()
        return {
            "disposition": "resolved",
            "confidence": 0.8,
            "facts": {
                "basis": "as_logged",
                "calories": 125.0,
                "protein_g": 4.0,
                "carbs_g": 18.0,
                "fat_g": 4.0,
            },
            "assumptions": ["synthetic_model_prior_portion"],
        }


def load_corpus() -> list[dict[str, Any]]:
    """Load the committed synthetic representative corpus."""

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    if not isinstance(cases, list):
        msg = "estimate-first corpus cases must be a list"
        raise TypeError(msg)
    return cast(list[dict[str, Any]], cases)


def case_id(case: dict[str, Any]) -> str:
    return str(case["id"])


def case_input(case: dict[str, Any]) -> str:
    return str(case["input"])


def expectation(case: dict[str, Any], mode: EstimatorClarifyMode) -> dict[str, Any]:
    return cast(dict[str, Any], cast(dict[str, Any], case["expectations"])[mode])


def estimate_first_params() -> list[Any]:
    """Pytest params for the default-mode representative sweep."""

    return [pytest.param(case, id=case_id(case)) for case in load_corpus()]


def mode_difference_params() -> list[Any]:
    """Pytest params for non-default modes whose expected behavior differs."""

    params: list[Any] = []
    for case in load_corpus():
        default = expectation(case, "estimate_first")
        params.extend(
            pytest.param(case, mode, id=f"{case_id(case)}[{mode}]")
            for mode in ("balanced", "strict")
            if expectation(case, mode) != default
        )
    return params


def smoke_cases() -> list[dict[str, Any]]:
    return [case for case in load_corpus() if bool(case.get("smoke"))]


def seed_event(
    client: TestClient, case: dict[str, Any], mode: EstimatorClarifyMode
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a real user-owned log event through the local API."""

    email = f"fty302-{case_id(case)}-{mode}@example.com"
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": case_input(case)},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


def set_weight(
    session: Session, user_id: uuid.UUID, weight_kg: float = DEFAULT_TEST_WEIGHT_KG
) -> None:
    """Seed the profile weight needed by the real exercise calculator."""

    profile = session.scalars(select(UserProfile).where(UserProfile.user_id == user_id)).one()
    profile.weight_kg = weight_kg
    session.add(profile)
    session.commit()


def fixture_parse_provider(case: dict[str, Any]) -> Provider:
    """Return the parse provider scripted by one corpus case."""

    if case.get("parse_error") == "configuration":
        error = LLMConfigurationError(f"synthetic provider error for {case_input(case)}")
        return FakeProvider(responses=[error, error])
    responses = cast(list[dict[str, Any] | LLMError], case["parse_samples"])
    return FakeProvider(responses=responses)


def fixture_model_provider(case: dict[str, Any]) -> Provider:
    responses = cast(Sequence[dict[str, Any]], case.get("model_prior_estimates", ()))
    return FakeProvider(responses=list(responses))


def static_model_provider() -> Provider:
    return StaticModelPriorProvider()


def build_pipeline(
    session: Session,
    *,
    mode: EstimatorClarifyMode,
    parse_provider: Provider,
    model_provider: Provider,
) -> Pipeline:
    """Build the real parse -> exercise -> user_text -> food -> rough pipeline."""

    resolver = FoodResolver(session=session, source=FakeFoodSource())
    disabled_search = DisabledSearchProvider()
    official_step = OfficialSourceResolveStep(
        provider=model_provider,
        search_provider=disabled_search,
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_no_network_fetch,
        reference_fetch_fn=_no_network_fetch,
        clarify_mode=mode,
    )
    return Pipeline(
        [
            ParseStep(
                parse_provider,
                policy=ParsePolicySettings(mode=mode),
            ),
            ExerciseCalculateStep(),
            UserTextResolveStep(),
            FoodResolveStep(resolver, clarify_mode=mode),
            official_step,
        ]
    )


def _no_network_fetch(url: str, settings: object) -> str:
    raise AssertionError(f"network fetch must not run in FTY-302 harness: {url} {settings!r}")
