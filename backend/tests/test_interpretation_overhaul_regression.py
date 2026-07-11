"""FTY-327 regression: phrasing mutations cannot regress to a clarify.

FTY-315 pinned that the audited dogfood snack resolves as plausible intake, but
two gaps let a later *phrasing mutation* of the same snack silently collapse the
live parse back to a clarify: the FTY-315 corpus never carried the mutated
wording, and the FTY-302 representative harness disables search, so the branded
web-tier path the live run actually took was never exercised end-to-end. This
suite closes both against the FTY-325/FTY-326 interpretation overhaul, driving
the real parse -> interpretation-session -> food-resolution ->
official/reference/model-prior pipeline with the network-free
``interpretation_regression_harness`` seams to assert: the exact mutated phrase
and a broad corpus of natural-language mutations resolve as two branded, counted
items (plausible bands, honest provenance, never the audited ``564``/``2`` kcal
shape); a search-enabled web tier whose every fetch 403/405/460s and whose
snippets do not resolve still ends in a rough ``model_prior`` estimate; the
session revises a degenerate single-item collapse back to the two-item hypothesis
(FTY-325) under sanitized hypothesis-revision trace labels; the amountless
boundary keeps its FTY-298/FTY-278 outcome; and no app path special-cases the
phrase or its brands.

The exact phrase is operator-approved user-log text under the same privacy terms
as FTY-315: it appears only as this fixture, never in run trace, assumptions,
source refs, provider errors, logs, or persisted rows.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.branded_routing import RETAILER_BRAND_ALIASES
from app.estimator.decision_trace import AMOUNT_KINDS
from app.estimator.food_step import FoodResolver, FoodResolveStep
from app.estimator.interpretation import InterpretationSession
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import QUANTITY_QUESTION, OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.pipeline import EstimationContext, Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import SearchCandidate, SearchResult, SearchStatus
from app.estimator.searched_reference import (
    MODEL_PRIOR_SOURCE,
    MODEL_PRIOR_SOURCE_TYPE,
    REFERENCE_SOURCE_TYPE,
    SNIPPET_ASSUMPTION,
)
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.food_sources import Product
from tests.interpretation_regression_harness import (
    CRACKER_SNIPPET_ESTIMATE,
    HUMMUS_SNIPPET_ESTIMATE,
    HUMMUS_URL,
    RAW_SNIPPET_SENTINEL,
    TOPPABLES_URL,
    CyclingFailFetcher,
    ForbiddenFetcher,
    KeyedSnippetSearchProvider,
    MissingFoodSource,
    build_pipeline,
    cracker_item,
    evidence_for,
    foods,
    hummus_item,
    hypothesis_entries,
    model_prior_estimate,
    no_official_fetch,
    parsed_sample,
    per_candidate_hypothesis_entries,
    persisted_text,
    questions,
    run_for,
    seed_event,
    snack_search_provider,
)

#: The exact mutated phrase from the 2026-07-10 dogfood failure — operator
#: approved as a regression fixture. Minimal food text only: no ids, timestamps,
#: screenshots, or provider transcripts accompany it; the redaction assertions
#: below prove it never persists outside the user-owned raw event.
_EXACT_PHRASE = (
    "4 toppables brand crackers with 1tbsp of loblaws store brand "
    "(PC/presidents choice) dill pickle hummus"
)

#: The audited bad numbers this suite exists to prevent (a hummus identity costed
#: as an FDC pickles row, and four *full servings* instead of four crackers).
_AUDITED_CRACKERS_KCAL = 564.0
_AUDITED_HUMMUS_KCAL = 2.0
_AUDITED_TOTAL_KCAL = 566.0


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


# ---------------------------------------------------------------------------
# The exact mutated dogfood phrase
# ---------------------------------------------------------------------------

#: The parse the interpreter forms for the mutated phrase: two items, each
#: carrying *its own* brand and amount — crackers ``Toppables`` x4 (count), hummus
#: the ``PC``/Loblaws store-brand marker x1 tbsp (volume). Wrapped in the messy
#: provider envelope (string numbers, cased enums) the recovery layer normalizes.
_EXACT_PARSE_SAMPLE: dict[str, Any] = {
    "result": {
        "disposition": "Parsed",
        "confidence": "0.93",
        "items": [
            {
                "type": "Food",
                "name": "crackers",
                "brand": "Toppables",
                "quantity_text": "4",
                "unit": "crackers",
                "amount": "4",
            },
            {
                "type": "Food",
                "name": "dill pickle hummus",
                "brand": "PC Loblaws presidents choice store brand",
                "quantity_text": "1tbsp",
                "unit": "tbsp",
                "amount": "1",
            },
        ],
        "clarification_questions": None,
    }
}


def test_exact_mutated_phrase_resolves_as_plausible_counted_snack(
    client: TestClient, session: Session
) -> None:
    user_id, event_id, auth = seed_event(client, "fty327-exact@example.com", _EXACT_PHRASE)
    search = snack_search_provider()
    reference_fetcher = ForbiddenFetcher()
    extraction_provider = FakeProvider(
        responses=[CRACKER_SNIPPET_ESTIMATE, HUMMUS_SNIPPET_ESTIMATE]
    )
    pipeline = Pipeline(
        [
            ParseStep(
                FakeProvider(responses=[_EXACT_PARSE_SAMPLE] * SELF_CONSISTENCY_FIRST_WINDOW),
                policy=ParsePolicySettings(),
            ),
            FoodResolveStep(FoodResolver(session=session, source=MissingFoodSource())),
            OfficialSourceResolveStep(
                provider=extraction_provider,
                search_provider=search,
                fetch_settings=OfficialFetchSettings(),
                reference_fetch_settings=ReferenceFetchSettings(),
                fetch_fn=no_official_fetch,
                reference_fetch_fn=reference_fetcher,
            ),
        ]
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    # Completed intake under default estimate_first: no failure, no clarification.
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert questions(session, event_id) == []

    by_name = {food.name: food for food in foods(session, event_id)}
    assert set(by_name) == {"crackers", "dill pickle hummus"}
    assert {food.status for food in by_name.values()} == {DerivedItemStatus.RESOLVED}
    crackers = by_name["crackers"]
    hummus = by_name["dill pickle hummus"]

    # Four crackers by FTY-252 count math against ``per 5 crackers (19 g)``:
    # ~72 kcal / 15.2 g — never four full servings, never the audited 564.
    assert crackers.calories is not None and hummus.calories is not None
    assert crackers.calories == pytest.approx(72.0)
    assert crackers.grams == pytest.approx(15.2)
    assert crackers.calories != pytest.approx(_AUDITED_CRACKERS_KCAL)

    # One tbsp (~15 g) of PC hummus at 80 kcal / 30 g: ~40 kcal — a plausible
    # hummus amount in the tens of kcal, never the audited 2 kcal pickles scaling.
    assert hummus.calories == pytest.approx(40.0)
    assert hummus.grams == pytest.approx(15.0)
    assert 10.0 < hummus.calories < 90.0
    assert hummus.calories != pytest.approx(_AUDITED_HUMMUS_KCAL)
    assert crackers.calories + hummus.calories < _AUDITED_TOTAL_KCAL / 2

    # Honest provenance: both items are snippet-derived reference evidence.
    for food, url in ((crackers, TOPPABLES_URL), (hummus, HUMMUS_URL)):
        evidence = evidence_for(session, food)
        assert evidence.source_type == REFERENCE_SOURCE_TYPE
        assert evidence.source_ref == f"{REFERENCE_SOURCE_TYPE}:{url}"
        assert SNIPPET_ASSUMPTION in (evidence.assumptions or [])
        assert evidence.product_id is None
    assert session.scalars(select(Product)).all() == []

    # The page fetch was attempted first and 403ed; the snippet rescued each item.
    assert reference_fetcher.fetched == [TOPPABLES_URL, HUMMUS_URL]

    # Interpretation structure via the sanitized FTY-325 trace labels.
    _assert_exact_phrase_interpretation_trace(run_for(session, event_id).trace)

    # Redaction: the raw phrase and raw snippet text persist nowhere beyond the
    # user-owned raw event, and no generic quantity question was recorded.
    persisted = persisted_text(session, event_id)
    assert _EXACT_PHRASE not in persisted
    assert RAW_SNIPPET_SENTINEL not in persisted
    assert QUANTITY_QUESTION not in persisted
    assert all(_EXACT_PHRASE not in prompt for prompt in extraction_provider.prompts)
    # Identity search egressed only sanitized identity — the raw phrase, its
    # slash/dash parentheticals, and store-brand punctuation never leaked.
    for query in search.queries:
        assert _EXACT_PHRASE not in query
        assert query.endswith("nutrition facts")
        assert not any(char in query for char in "()/")

    # The completed event serves both costed items through the read model.
    _assert_read_model_serves_the_snack(client, user_id, event_id, auth)


def _assert_exact_phrase_interpretation_trace(trace: list[dict[str, Any]] | None) -> None:
    """The exact phrase forms a two-item hypothesis, each item branded and
    amount-classified, with no clarify/gate-failure revision — read off the
    sanitized FTY-325 hypothesis-revision trace labels."""

    snapshot = [
        entry
        for entry in hypothesis_entries(trace)
        if entry.get("outcome") == "initial_hypothesis" and "candidate_index" not in entry
    ]
    assert len(snapshot) == 1
    assert snapshot[0]["result_count"] == 2  # two items, not a degenerate single.

    per_candidate = per_candidate_hypothesis_entries(trace)
    assert len(per_candidate) == 2
    assert {entry["candidate_index"] for entry in per_candidate} == {0, 1}
    # Each item carries its brand (has_brand) and its amount kind (4 count; 1 tbsp).
    assert all(entry["has_brand"] is True for entry in per_candidate)
    assert all(entry["result_count"] == 2 for entry in per_candidate)
    amount_kinds = {entry["candidate_index"]: entry["amount_kind"] for entry in per_candidate}
    assert amount_kinds == {0: "count", 1: "volume"}
    # No revision event ended the interpretation in a clarify/gate-failure.
    assert not any(
        entry.get("outcome") in {"clarification_needed", "deterministic_gate_failed"}
        for entry in hypothesis_entries(trace)
    )


def _assert_read_model_serves_the_snack(
    client: TestClient, user_id: uuid.UUID, event_id: uuid.UUID, auth: str
) -> None:
    listing = client.get(
        f"/api/users/{user_id}/log-events/by-date", headers={"Authorization": auth}
    )
    assert listing.status_code == 200
    entry = next(row for row in listing.json() if row["event"]["id"] == str(event_id))
    served = {item["name"]: item for item in entry["items"]}
    assert served["crackers"]["calories"] == pytest.approx(72.0)
    assert served["dill pickle hummus"]["calories"] == pytest.approx(40.0)
    assert {item["source"]["ref"] for item in entry["items"]} == {
        f"{REFERENCE_SOURCE_TYPE}:{TOPPABLES_URL}",
        f"{REFERENCE_SOURCE_TYPE}:{HUMMUS_URL}",
    }
    # The raw phrase appears exactly once — as the user-owned raw event text.
    assert listing.text.count(_EXACT_PHRASE) == 1


# ---------------------------------------------------------------------------
# Adversarial natural-language mutations: the behavior generalizes
# ---------------------------------------------------------------------------

#: Each variant exercises a listed mutation class. Every one carries two items,
#: each with its own brand and its own amount, so all resolve through the branded
#: reference tier; the assertions prove no clarification, plausible bands, honest
#: provenance, and the two-item interpretation structure.
_VARIANT_CASES: list[dict[str, Any]] = [
    {
        # inline brand-marker wording: "X brand Y".
        "id": "inline-brand-marker",
        "raw_text": "4 Toppables brand crackers with 1 tbsp PC brand dill pickle hummus",
        "items": [
            cracker_item(quantity_text="4", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1 tbsp", amount=1, brand="PC"),
        ],
    },
    {
        # "A store brand Z": the store-brand marker sits before the noun.
        "id": "store-brand-before-noun",
        "raw_text": (
            "4 Toppables crackers and 1 tbsp of Presidents Choice store brand dill pickle hummus"
        ),
        "items": [
            cracker_item(quantity_text="4", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1 tbsp", amount=1, brand="Presidents Choice"),
        ],
    },
    {
        # slash parenthetical: "(PC/presidents choice)".
        "id": "slash-parenthetical",
        "raw_text": "4 Toppables crackers, 1 tbsp dill pickle hummus (PC/presidents choice)",
        "items": [
            cracker_item(quantity_text="4", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1 tbsp", amount=1, brand="PC presidents choice"),
        ],
    },
    {
        # dash parenthetical: "(PC - Loblaws)".
        "id": "dash-parenthetical",
        "raw_text": "4 Toppables crackers with 1 tbsp dill pickle hummus (PC - Loblaws)",
        "items": [
            cracker_item(quantity_text="4", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1 tbsp", amount=1, brand="PC Loblaws"),
        ],
    },
    {
        # brand before the noun on both items.
        "id": "brand-before-noun",
        "raw_text": "4 Toppables crackers and 1 tbsp President's Choice dill pickle hummus",
        "items": [
            cracker_item(quantity_text="4", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1 tbsp", amount=1, brand="President's Choice"),
        ],
    },
    {
        # compound "+" clause with per-item amounts.
        "id": "compound-plus-clause",
        "raw_text": "Toppables crackers x4 + 1 tbsp PC dill pickle hummus",
        "items": [
            cracker_item(quantity_text="x4", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1 tbsp", amount=1, brand="PC"),
        ],
    },
    {
        # the live misspelling: "toppabales" survives in the raw text and quantity
        # hint; the interpreter still recognizes the Toppables brand.
        "id": "live-misspelling",
        "raw_text": "4 toppabales brand crackers with 1 tbsp PC dill pickle hummus",
        "items": [
            cracker_item(quantity_text="4 toppabales", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1 tbsp", amount=1, brand="PC"),
        ],
    },
    {
        # unit crush: "1tbsp".
        "id": "unit-crush",
        "raw_text": "4 Toppables crackers with 1tbsp of PC dill pickle hummus",
        "items": [
            cracker_item(quantity_text="4", amount=4, brand="Toppables"),
            hummus_item(quantity_text="1tbsp", amount=1, brand="PC"),
        ],
    },
    {
        # worded portions: "four" and "a tablespoon of".
        "id": "worded-portions",
        "raw_text": "four Toppables crackers and a tablespoon of PC dill pickle hummus",
        "items": [
            cracker_item(quantity_text="four", amount=4, brand="Toppables"),
            hummus_item(quantity_text="a tablespoon", amount=1, brand="PC"),
        ],
    },
]


@pytest.mark.parametrize("case", _VARIANT_CASES, ids=lambda case: str(case["id"]))
def test_natural_language_mutations_resolve_without_clarification(
    client: TestClient, session: Session, case: dict[str, Any]
) -> None:
    raw_text = str(case["raw_text"])
    user_id, event_id, _ = seed_event(client, f"fty327-{case['id']}@example.com", raw_text)
    search = snack_search_provider()
    pipeline = build_pipeline(
        session,
        parse_samples=[parsed_sample(list(case["items"]))],
        estimates=[CRACKER_SNIPPET_ESTIMATE, HUMMUS_SNIPPET_ESTIMATE],
        search=search,
        reference_fetcher=ForbiddenFetcher(),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert questions(session, event_id) == []

    by_name = {food.name: food for food in foods(session, event_id)}
    assert set(by_name) == {"crackers", "dill pickle hummus"}
    crackers = by_name["crackers"]
    hummus = by_name["dill pickle hummus"]
    assert {food.status for food in by_name.values()} == {DerivedItemStatus.RESOLVED}

    # Plausible bands (FTY-315): crackers ~72 for 4, hummus in the tens for 1 tbsp.
    assert crackers.calories is not None and 55.0 <= crackers.calories <= 95.0
    assert hummus.calories is not None and 20.0 <= hummus.calories <= 70.0
    assert crackers.calories + hummus.calories < _AUDITED_TOTAL_KCAL
    for food in (crackers, hummus):
        evidence = evidence_for(session, food)
        assert evidence.source_type == REFERENCE_SOURCE_TYPE
        assert SNIPPET_ASSUMPTION in (evidence.assumptions or [])

    # Two items, each carrying its brand and amount, via the FTY-325 trace labels.
    per_candidate = per_candidate_hypothesis_entries(run_for(session, event_id).trace)
    assert len(per_candidate) == 2
    assert all(entry["has_brand"] is True for entry in per_candidate)
    assert {entry["amount_kind"] for entry in per_candidate} == {"count", "volume"}

    # Redaction rides along with every end-to-end case.
    persisted = persisted_text(session, event_id)
    assert raw_text not in persisted
    assert RAW_SNIPPET_SENTINEL not in persisted
    assert QUANTITY_QUESTION not in persisted
    for query in search.queries:
        assert raw_text not in query
        assert not any(char in query for char in "()/")


# ---------------------------------------------------------------------------
# The audited dead end: search succeeds, every fetch fails, snippets unresolved
# ---------------------------------------------------------------------------

_DEAD_END_URLS = (
    "https://blocked.example.com/oat-thins/a",
    "https://blocked.example.com/oat-thins/b",
    "https://blocked.example.com/oat-thins/c",
)


def _dead_end_search_provider() -> KeyedSnippetSearchProvider:
    """Search *succeeds* with three candidate pages for the branded query."""

    candidates = tuple(
        SearchCandidate(
            url=url,
            title="Oat Thins Nutrition",
            snippet=f"{RAW_SNIPPET_SENTINEL} nutrition information for oat thins.",
        )
        for url in _DEAD_END_URLS
    )
    hit = SearchResult(status=SearchStatus.SUCCESS, candidates=candidates)
    return KeyedSnippetSearchProvider((("nofacts", hit),))


def test_search_enabled_all_fetches_fail_dead_end_still_rough_estimates(
    client: TestClient, session: Session
) -> None:
    """The audited dead-end shape: the branded web tier is *reached* (search
    succeeds), every result-page fetch 403/405/460s, and the fallback snippets do
    not resolve — yet the run still completes as a rough, honestly-labelled
    ``model_prior`` estimate rather than asking a clarification."""

    user_id, event_id, _ = seed_event(
        client, "fty327-dead-end@example.com", "5 NoFacts brand oat thins"
    )
    search = _dead_end_search_provider()
    reference_fetcher = CyclingFailFetcher()
    # Three snippet-extraction attempts all report they cannot estimate, then the
    # gated model-prior last resort returns a plausible rough estimate.
    estimates: list[dict[str, Any] | LLMError] = [
        {"disposition": "unresolved", "confidence": 0.1},
        {"disposition": "unresolved", "confidence": 0.1},
        {"disposition": "unresolved", "confidence": 0.1},
        model_prior_estimate(130.0, 3.0, 22.0, 4.0, "five typical oat cracker thins"),
    ]
    pipeline = build_pipeline(
        session,
        parse_samples=[
            parsed_sample(
                [
                    {
                        "type": "food",
                        "name": "oat thins",
                        "brand": "NoFacts",
                        "quantity_text": "5",
                        "unit": "crackers",
                        "amount": 5,
                    }
                ]
            )
        ],
        estimates=estimates,
        search=search,
        reference_fetcher=reference_fetcher,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert questions(session, event_id) == []

    all_foods = foods(session, event_id)
    assert len(all_foods) == 1
    food = all_foods[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories is not None and 80.0 <= food.calories <= 200.0
    assert food.calories != pytest.approx(_AUDITED_CRACKERS_KCAL)

    # Honest provenance: the rough estimate is labelled model_prior, not faked
    # trusted/reference evidence.
    evidence = evidence_for(session, food)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == MODEL_PRIOR_SOURCE
    assert evidence.product_id is None
    assert any("model prior" in assumption for assumption in (evidence.assumptions or []))

    # Every result-page fetch was attempted and failed with an audited code.
    assert reference_fetcher.fetched == list(_DEAD_END_URLS)
    assert set(reference_fetcher.status_codes) == {403, 405, 460}

    persisted = persisted_text(session, event_id)
    assert RAW_SNIPPET_SENTINEL not in persisted
    assert QUANTITY_QUESTION not in persisted


# ---------------------------------------------------------------------------
# The core FTY-325 mechanism: a degenerate collapse is re-interpreted, not frozen
# ---------------------------------------------------------------------------


def test_sample_collapse_is_reinterpreted_not_frozen_into_one_item() -> None:
    """When the parse samples structurally disagree — one reads the two branded
    items, another collapses them into a single generic candidate — the
    interpretation session re-reads the entry and revises back to the two-item
    hypothesis instead of freezing the degenerate collapse (FTY-325). The revision
    is recorded under the sanitized hypothesis-revision trace labels."""

    context = EstimationContext(
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="4 Toppables crackers with 1 tbsp PC dill pickle hummus",
    )
    two_items = [
        cracker_item(quantity_text="4", amount=4, brand="Toppables"),
        hummus_item(quantity_text="1 tbsp", amount=1, brand="PC"),
    ]
    collapsed = {
        "disposition": "parsed",
        "confidence": 0.95,
        "items": [{"type": "food", "name": "snack", "quantity_text": "some"}],
    }
    two_item_sample = {"disposition": "parsed", "confidence": 0.6, "items": two_items}
    # First window (collapsed, two-item) disagrees -> a third sample is drawn, then
    # the session spends its bounded re-interpretation on the raw text: the re-ask
    # returns the complete two-item reading.
    provider = FakeProvider(
        responses=[
            collapsed,
            two_item_sample,
            two_item_sample,
            {"disposition": "parsed", "confidence": 0.9, "items": two_items},
        ]
    )
    session = InterpretationSession(provider, context.raw_text, policy=ParsePolicySettings())

    session.interpret_initial(context)

    # The hypothesis did not freeze the degenerate single-item collapse.
    assert session.hypothesis is not None
    hypothesis_names = sorted(item.candidate.name for item in session.hypothesis.items)
    assert hypothesis_names == ["crackers", "dill pickle hummus"]

    outcomes = {entry.get("outcome") for entry in hypothesis_entries(context.trace)}
    # An initial snapshot, then a real revision event away from the collapse.
    assert "initial_hypothesis" in outcomes
    assert outcomes & {"item_added", "item_split"}
    # Every revision outcome is a sanitized label from the documented vocabulary.
    allowed = {
        "initial_hypothesis",
        "hypothesis_kept",
        "item_added",
        "item_removed",
        "item_split",
        "item_merged",
        "identity_revised",
        "brand_revised",
        "quantity_revised",
        "unit_revised",
        "stated_nutrition_revised",
        "exercise_detail_revised",
        "evidence_attached",
        "evidence_rejected",
        "clarification_needed",
        "deterministic_gate_failed",
        "revision_truncated",
    }
    assert outcomes <= allowed
    # The revised two-item hypothesis carries both brands and both amount kinds.
    revised = per_candidate_hypothesis_entries(context.trace)
    assert any(entry["has_brand"] for entry in revised)
    assert {entry["amount_kind"] for entry in revised} >= {"count", "volume"}
    assert all(entry["amount_kind"] in AMOUNT_KINDS for entry in revised)


# ---------------------------------------------------------------------------
# Boundary: a genuinely amountless phrase (FTY-298/FTY-278)
# ---------------------------------------------------------------------------

_AMOUNTLESS_ITEMS = [
    {"type": "food", "name": "crackers"},
    {"type": "food", "name": "hummus"},
]


def _amountless_clarify_sample() -> dict[str, Any]:
    return {
        "disposition": "needs_clarification",
        "confidence": 0.38,
        "items": _AMOUNTLESS_ITEMS,
        "clarification_questions": [
            {
                "text": "How much crackers and hummus should be counted?",
                "options": ["1 snack plate", "2 snack plates", "Crackers only"],
            }
        ],
    }


def test_amountless_boundary_estimate_first_rough_estimates(
    client: TestClient, session: Session
) -> None:
    """``crackers and hummus`` carries no stated portion at all. Under default
    estimate_first it rough-estimates both recognizable identities (no clarify),
    per FTY-298 — the amountless boundary does not regress."""

    user_id, event_id, _ = seed_event(
        client, "fty327-amountless-ef@example.com", "crackers and hummus"
    )
    pipeline = build_pipeline(
        session,
        parse_samples=[_amountless_clarify_sample()],
        estimates=[
            model_prior_estimate(90.0, 2.0, 15.0, 3.0, "a serving of crackers"),
            model_prior_estimate(80.0, 3.0, 7.0, 5.0, "a serving of hummus"),
        ],
        search=snack_search_provider(),
        reference_fetcher=ForbiddenFetcher(),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert questions(session, event_id) == []
    all_foods = foods(session, event_id)
    assert len(all_foods) == 2
    assert {food.status for food in all_foods} == {DerivedItemStatus.RESOLVED}
    assert {evidence_for(session, food).source_type for food in all_foods} == {
        MODEL_PRIOR_SOURCE_TYPE
    }


def test_amountless_boundary_strict_keeps_item_specific_clarification(
    client: TestClient, session: Session
) -> None:
    """Under the strict operator mode the contract-valid non-counted outcome — an
    item-specific optioned clarification, never the generic quantity fallback —
    remains (FTY-278)."""

    user_id, event_id, _ = seed_event(
        client, "fty327-amountless-strict@example.com", "crackers and hummus"
    )
    pipeline = build_pipeline(
        session,
        parse_samples=[_amountless_clarify_sample()],
        estimates=[],
        search=snack_search_provider(),
        reference_fetcher=ForbiddenFetcher(),
        mode="strict",
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert all(food.status is not DerivedItemStatus.RESOLVED for food in foods(session, event_id))
    open_questions = questions(session, event_id)
    assert len(open_questions) == 1
    assert open_questions[0].question_text != QUANTITY_QUESTION
    assert open_questions[0].options
    assert "How much did you have" not in open_questions[0].question_text


# ---------------------------------------------------------------------------
# No string special-case: the phrase and its brands are not hardcoded
# ---------------------------------------------------------------------------

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"

#: The only modules allowed to mention the PC/Loblaws retailer identity in
#: executable strings (identical rationale to FTY-315's scan): ``branded_routing``
#: (the FTY-253 static retailer alias map — brand words only, checked digit-free
#: below) and ``parse_prompt`` (the brand-extraction instruction example).
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
    """No app-code path may special-case this regression fixture: the exact phrase
    appears nowhere in ``backend/app``, the Toppables product name appears in no
    executable string, and the PC/Loblaws retailer tokens appear only in the two
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
