"""FTY-329 item-scoped partial-resolution estimator tests.

These drive the real parse -> food-resolution -> official/model-prior pipeline with
network-free fakes and prove the emit side (a mixed run commits the costable siblings
and asks only about the un-costable component, landing ``partially_resolved``) and the
answer-triggered **scoped** re-estimate (only the open component is re-costed; the
committed sibling is preserved byte-identically and no provider/source call is made
about it; the event then completes). Whole-event ``needs_clarification`` survives only
when nothing is costable or a deterministic safety gate fires.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.fdc import FDC_SOURCE, ProductFacts
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolveStep
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMTransientError
from app.llm.providers.fake import FakeProvider
from app.models.derived import (
    ClarificationAnswer,
    ClarificationQuestion,
    DerivedFoodItem,
)
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services import clarification as clarification_service
from app.services import daily_summary as daily_summary_service
from app.services import log_events as log_event_service
from app.settings import DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR
from tests.conftest import upgrade


class FakeFoodSource:
    """A scripted, network-free USDA stand-in (records every lookup)."""

    def __init__(self, facts: dict[str, ProductFacts] | None = None) -> None:
        self._facts = facts or {}
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return self._facts.get(query.strip().lower())


class DisabledSearchProvider:
    """Search disabled so the pipeline falls straight to model-prior."""

    @property
    def enabled(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return False

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product",),
            enabled=False,
            available=False,
        )

    def search(self, query: str) -> SearchResult:  # pragma: no cover - disabled
        return SearchResult(status=SearchStatus.PARTIAL)


def _unused_fetch(url: str, settings: object) -> str:  # pragma: no cover - search disabled
    raise AssertionError("fetch must not run when search is disabled")


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


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
    *,
    session: Session,
    parse_provider: FakeProvider,
    estimates: list[Any],
    food_source: FakeFoodSource,
) -> Pipeline:
    resolver = FoodResolver(session=session, source=food_source)
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=estimates),
        search_provider=DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
        clarify_mode="estimate_first",
        model_prior_confidence_floor=DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR,
    )
    return Pipeline(
        [
            ParseStep(parse_provider),
            FoodResolveStep(resolver, clarify_mode="estimate_first"),
            official_step,
        ]
    )


def _parse_provider(items: list[dict[str, Any]], *, confidence: float = 0.95) -> FakeProvider:
    return FakeProvider(
        responses=[{"disposition": "parsed", "confidence": confidence, "items": items}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )


def _fdc_facts(name: str, *, calories_per_100g: float) -> ProductFacts:
    return ProductFacts(
        source=FDC_SOURCE,
        source_ref=f"usda_fdc:{name}",
        query_key=name,
        description=name,
        facts=NutritionFacts(calories=calories_per_100g, protein_g=8.0, carbs_g=5.0, fat_g=2.0),
        default_serving_g=None,
        content_hash=f"{name}-hash",
        barcode=None,
    )


def _low_confidence_estimate() -> dict[str, Any]:
    """A model-prior estimate below the floor, so its component clarifies."""

    return {
        "disposition": "resolved",
        "confidence": 0.40,
        "facts": {
            "basis": "per_serving",
            "calories": 120.0,
            "protein_g": 8.0,
            "carbs_g": 12.0,
            "fat_g": 5.0,
            "serving_size_amount": 244.0,
            "serving_size_unit": "g",
        },
        "assumptions": ["typical serving"],
    }


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(
            select(DerivedFoodItem)
            .where(DerivedFoodItem.log_event_id == event_id)
            .order_by(DerivedFoodItem.created_at.asc(), DerivedFoodItem.id.asc())
        )
    )


def _questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion)
            .where(ClarificationQuestion.log_event_id == event_id)
            .order_by(ClarificationQuestion.position.asc())
        )
    )


def _evidence(session: Session, event_id: uuid.UUID) -> list[EvidenceSource]:
    return list(
        session.scalars(select(EvidenceSource).where(EvidenceSource.log_event_id == event_id))
    )


def _run_mixed_first_pass(
    client: TestClient, session: Session, email: str
) -> tuple[uuid.UUID, uuid.UUID, DerivedFoodItem, DerivedFoodItem]:
    """Resolve "chicken 150g and milk": chicken costs, milk clarifies (partial)."""

    user_id, event_id = _seed_event(client, email, "grilled chicken 150g and a glass of milk")
    pipeline = _pipeline(
        session=session,
        parse_provider=_parse_provider(
            [
                {
                    "type": "food",
                    "name": "grilled chicken",
                    "quantity_text": "150g",
                    "unit": "g",
                    "amount": 150,
                },
                {"type": "food", "name": "milk", "quantity_text": ""},
            ]
        ),
        estimates=[_low_confidence_estimate()],
        food_source=FakeFoodSource(
            {"grilled chicken": _fdc_facts("grilled chicken", calories_per_100g=200.0)}
        ),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.PARTIALLY_RESOLVED
    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    foods = _foods(session, event_id)
    assert len(foods) == 2
    resolved = next(f for f in foods if f.status == DerivedItemStatus.RESOLVED)
    unresolved = next(f for f in foods if f.status == DerivedItemStatus.UNRESOLVED)
    return user_id, event_id, resolved, unresolved


def test_mixed_run_commits_sibling_and_scopes_one_question(
    client: TestClient, session: Session
) -> None:
    """A mixed run costs the sibling and asks exactly one item-scoped question."""

    _user, event_id, resolved, unresolved = _run_mixed_first_pass(
        client, session, "fty329-mixed@example.com"
    )

    # The costable sibling is committed with real calories + one evidence row.
    assert resolved.name == "grilled chicken"
    assert resolved.calories == pytest.approx(300.0)  # 200 kcal/100g * 150g
    assert unresolved.name == "milk"
    assert unresolved.calories is None

    # Exactly one item-scoped question, carrier -> the unresolved milk component,
    # naming the component but never the whole diary phrase.
    questions = _questions(session, event_id)
    assert len(questions) == 1
    assert questions[0].derived_food_item_id == unresolved.id
    assert "milk" in questions[0].question_text
    assert "grilled chicken 150g and a glass of milk" not in questions[0].question_text

    # Exactly one committed evidence row — the sibling's; the open component has none.
    evidence = _evidence(session, event_id)
    assert [e.derived_food_item_id for e in evidence] == [resolved.id]


def test_answer_reestimates_only_open_component_and_preserves_sibling(
    client: TestClient, session: Session
) -> None:
    """The answer re-costs only milk; chicken stays byte-identical; the event completes."""

    user_id, event_id, resolved, unresolved = _run_mixed_first_pass(
        client, session, "fty329-answer@example.com"
    )
    sibling_before = {
        "id": resolved.id,
        "calories": resolved.calories,
        "grams": resolved.grams,
        "protein_g": resolved.protein_g,
        "content_hash": _evidence(session, event_id)[0].content_hash,
    }
    question = _questions(session, event_id)[0]

    # Answer the milk question through the real resolve flow (event -> processing).
    current_user = session.get(User, user_id)
    assert current_user is not None
    event, resolved_flag = clarification_service.answer_clarification_question(
        session, user_id, current_user, event_id, question.id, "1 cup"
    )
    assert resolved_flag is True
    assert LogEventStatus(event.status) is LogEventStatus.PROCESSING

    # The scoped re-estimate: milk resolves from its own identity + the answer only.
    scoped_source = FakeFoodSource({"milk": _fdc_facts("milk", calories_per_100g=50.0)})
    scoped_parse = _parse_provider(
        [{"type": "food", "name": "milk", "quantity_text": "1 cup", "unit": "cup", "amount": 1}]
    )
    scoped_pipeline = _pipeline(
        session=session,
        parse_provider=scoped_parse,
        estimates=[],
        food_source=scoped_source,
    )

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=scoped_pipeline
    )

    assert result.event_status is LogEventStatus.COMPLETED
    assert result.job_status is EstimationJobStatus.SUCCEEDED

    # No provider/source call was made about the sibling: the scoped pipeline only ever
    # looked up / interpreted the open component.
    assert scoped_source.lookups == ["milk"]
    assert all("grilled chicken" not in prompt for prompt in scoped_parse.prompts)

    foods = _foods(session, event_id)
    assert len(foods) == 2  # no duplicate row; the component resolved in place
    sibling_after = session.get(DerivedFoodItem, resolved.id)
    assert sibling_after is not None
    assert sibling_after.status == DerivedItemStatus.RESOLVED
    assert sibling_after.calories == sibling_before["calories"]
    assert sibling_after.grams == sibling_before["grams"]
    assert sibling_after.protein_g == sibling_before["protein_g"]

    milk_after = session.get(DerivedFoodItem, unresolved.id)
    assert milk_after is not None
    assert milk_after.status == DerivedItemStatus.RESOLVED
    assert milk_after.grams == pytest.approx(240.0)  # 1 cup -> 240 ml ~ 240 g
    assert milk_after.calories == pytest.approx(120.0)  # 50 kcal/100g * 240g

    # The sibling's evidence row is untouched (same content hash) and milk gained one.
    evidence_by_item = {e.derived_food_item_id: e for e in _evidence(session, event_id)}
    assert evidence_by_item[resolved.id].content_hash == sibling_before["content_hash"]
    assert unresolved.id in evidence_by_item

    # The answered question row is retained (the answer-flow idempotency anchor), but no
    # *open* item-scoped question survives — the status-gated read serves none on the now
    # completed event, and the retained row is the answered one on the resolved component.
    current_user = session.get(User, user_id)
    assert current_user is not None
    assert (
        log_event_service.list_clarification_questions(session, user_id, current_user, event_id)
        == []
    )
    retained = _questions(session, event_id)
    assert [q.derived_food_item_id for q in retained] == [unresolved.id]
    answered_ids = set(
        session.scalars(
            select(ClarificationAnswer.question_id).where(
                ClarificationAnswer.log_event_id == event_id
            )
        )
    )
    assert retained[0].id in answered_ids


def test_day_total_never_dips_across_scoped_reestimate(
    client: TestClient, session: Session
) -> None:
    """The counted sibling stays in ``intake`` before, during, and after the re-estimate."""

    user_id, event_id, _resolved, _unresolved = _run_mixed_first_pass(
        client, session, "fty329-nodip@example.com"
    )
    current_user = session.get(User, user_id)
    assert current_user is not None

    def _summary() -> tuple[float, int]:
        single = daily_summary_service.get_daily_summary(session, user_id, current_user)
        return single.intake.calories, single.uncounted_entries

    # BEFORE: the committed sibling counts; the open component is one uncounted entry.
    assert _summary() == (300.0, 1)

    # DURING: the real answer flow flips the event to ``processing`` in the same
    # transaction as the answer. The scoped-re-estimate read-model gate keeps the
    # committed sibling counted — nothing dips — while the component is still open.
    question = _questions(session, event_id)[0]
    clarification_service.answer_clarification_question(
        session, user_id, current_user, event_id, question.id, "1 cup"
    )
    assert _summary() == (300.0, 1)

    # AFTER: the open component resolves and the event completes; the total rises by
    # exactly the new item and the uncounted entry drops — the sibling never re-added.
    scoped_pipeline = _pipeline(
        session=session,
        parse_provider=_parse_provider(
            [{"type": "food", "name": "milk", "quantity_text": "1 cup", "unit": "cup", "amount": 1}]
        ),
        estimates=[],
        food_source=FakeFoodSource({"milk": _fdc_facts("milk", calories_per_100g=50.0)}),
    )
    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=scoped_pipeline)
    assert _summary() == (420.0, 0)  # 300 chicken + 120 milk


def test_replayed_answer_after_scoped_completion_is_noop(
    client: TestClient, session: Session
) -> None:
    """Re-answering an already-resolved question neither re-costs nor re-enqueues."""

    user_id, event_id, _resolved, _unresolved = _run_mixed_first_pass(
        client, session, "fty329-replay@example.com"
    )
    question = _questions(session, event_id)[0]
    current_user = session.get(User, user_id)
    assert current_user is not None
    clarification_service.answer_clarification_question(
        session, user_id, current_user, event_id, question.id, "1 cup"
    )
    scoped_pipeline = _pipeline(
        session=session,
        parse_provider=_parse_provider(
            [{"type": "food", "name": "milk", "quantity_text": "1 cup", "unit": "cup", "amount": 1}]
        ),
        estimates=[],
        food_source=FakeFoodSource({"milk": _fdc_facts("milk", calories_per_100g=50.0)}),
    )
    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=scoped_pipeline)

    # A replayed answer is an idempotent no-op: no new answer row, event stays completed.
    event, resolved_flag = clarification_service.answer_clarification_question(
        session, user_id, current_user, event_id, question.id, "2 cups"
    )
    assert resolved_flag is False
    assert LogEventStatus(event.status) is LogEventStatus.COMPLETED
    answer_count = session.scalar(
        select(func.count())
        .select_from(ClarificationAnswer)
        .where(ClarificationAnswer.log_event_id == event_id)
    )
    assert answer_count == 1
    assert len(_foods(session, event_id)) == 2


def test_scoped_reestimate_transient_error_is_retryable(
    client: TestClient, session: Session
) -> None:
    """A transient failure during the scoped re-estimate asks the caller to retry.

    Without this the event would be stuck ``partially_resolved`` — the answer is already
    recorded, so re-answering is a no-op. The sibling and the open component are both
    left untouched (the round's in-place applications are discarded) and the event stays
    ``processing`` for the retry.
    """

    user_id, event_id, resolved, unresolved = _run_mixed_first_pass(
        client, session, "fty329-retry@example.com"
    )
    question = _questions(session, event_id)[0]
    current_user = session.get(User, user_id)
    assert current_user is not None
    clarification_service.answer_clarification_question(
        session, user_id, current_user, event_id, question.id, "1 cup"
    )

    transient_parse = FakeProvider(
        responses=[LLMTransientError("boom")] * SELF_CONSISTENCY_FIRST_WINDOW
    )
    scoped_pipeline = _pipeline(
        session=session,
        parse_provider=transient_parse,
        estimates=[],
        food_source=FakeFoodSource({"milk": _fdc_facts("milk", calories_per_100g=50.0)}),
    )

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=scoped_pipeline
    )

    assert result.should_retry is True
    assert result.event_status is LogEventStatus.PROCESSING
    milk_after = session.get(DerivedFoodItem, unresolved.id)
    chicken_after = session.get(DerivedFoodItem, resolved.id)
    assert milk_after is not None and chicken_after is not None
    assert milk_after.status == DerivedItemStatus.UNRESOLVED
    assert chicken_after.status == DerivedItemStatus.RESOLVED
    assert chicken_after.calories == pytest.approx(300.0)


def test_no_costable_component_lands_whole_event_needs_clarification(
    client: TestClient, session: Session
) -> None:
    """Two un-costable components -> whole-event needs_clarification, nothing committed."""

    user_id, event_id = _seed_event(
        client, "fty329-none@example.com", "some mystery goo and some other goo"
    )
    pipeline = _pipeline(
        session=session,
        parse_provider=_parse_provider(
            [
                {"type": "food", "name": "mystery goo", "quantity_text": ""},
                {"type": "food", "name": "other goo", "quantity_text": ""},
            ]
        ),
        estimates=[_low_confidence_estimate(), _low_confidence_estimate()],
        food_source=FakeFoodSource({}),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    # Nothing costed: no derived rows, no evidence — the event-level questions carry no
    # derived_food_item_id carrier.
    assert _foods(session, event_id) == []
    assert _evidence(session, event_id) == []
    questions = _questions(session, event_id)
    assert questions != []
    assert all(question.derived_food_item_id is None for question in questions)


def test_safety_gate_stays_whole_event_even_with_a_costable_sibling(
    client: TestClient, session: Session
) -> None:
    """A deterministic plausibility gate fails the whole event; no sibling is committed."""

    user_id, event_id = _seed_event(
        client, "fty329-safety@example.com", "chicken 150g and 9000 eggs"
    )
    pipeline = _pipeline(
        session=session,
        parse_provider=_parse_provider(
            [
                {
                    "type": "food",
                    "name": "chicken",
                    "quantity_text": "150g",
                    "unit": "g",
                    "amount": 150,
                },
                {
                    "type": "food",
                    "name": "eggs",
                    "quantity_text": "9000",
                    "unit": "count",
                    "amount": 9000,
                },
            ]
        ),
        estimates=[],
        food_source=FakeFoodSource({"chicken": _fdc_facts("chicken", calories_per_100g=200.0)}),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    # The implausible count trips the parse safety gate: the whole event asks, and even
    # the otherwise-costable chicken is not committed.
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []
    questions = _questions(session, event_id)
    assert questions != []
    assert all(question.derived_food_item_id is None for question in questions)


def test_run_trace_never_carries_raw_diary_text_on_partial(
    client: TestClient, session: Session
) -> None:
    """The sanitized run trace/metadata never carries the raw diary phrase (redaction)."""

    _user, event_id, _resolved, _unresolved = _run_mixed_first_pass(
        client, session, "fty329-redaction@example.com"
    )
    run = session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id)).one()
    persisted = repr(
        (run.trace, run.assumptions, run.source_refs, run.validation_errors, run.error)
    )
    assert "grilled chicken 150g and a glass of milk" not in persisted
    # The bounded per-component trace is present (source/outcome labels).
    assert any(entry.get("decision") == "outcome" for entry in run.trace)


def _latest_run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    """The most recent estimation run for an event (highest attempt)."""

    return session.scalars(
        select(EstimationRun)
        .where(EstimationRun.log_event_id == event_id)
        .order_by(EstimationRun.attempt.desc())
        .limit(1)
    ).one()


def _trace_outcomes(run: EstimationRun) -> set[str | None]:
    return {entry.get("outcome") for entry in run.trace if entry.get("decision") == "outcome"}


def test_partial_run_emits_per_component_trace_labels(client: TestClient, session: Session) -> None:
    """The mixed first pass emits the required sanitized per-component partial labels."""

    _user, event_id, _resolved, _unresolved = _run_mixed_first_pass(
        client, session, "fty329-trace-labels@example.com"
    )
    run = _latest_run(session, event_id)
    outcomes = _trace_outcomes(run)

    # FTY-329 vocabulary: the resolved sibling, the clarified component, and the
    # partial-finalization marker are all recorded, and sanitized (no diary phrase).
    assert "component_resolved" in outcomes
    assert "component_clarified" in outcomes
    assert "partial_finalized" in outcomes
    assert "grilled chicken 150g and a glass of milk" not in repr(run.trace)


def test_scoped_reestimate_resolution_emits_trace_label(
    client: TestClient, session: Session
) -> None:
    """The scoped re-estimate that completes the event records a scoped-resolve label."""

    user_id, event_id, _resolved, _unresolved = _run_mixed_first_pass(
        client, session, "fty329-scoped-trace@example.com"
    )
    question = _questions(session, event_id)[0]
    current_user = session.get(User, user_id)
    assert current_user is not None
    clarification_service.answer_clarification_question(
        session, user_id, current_user, event_id, question.id, "1 cup"
    )
    scoped_pipeline = _pipeline(
        session=session,
        parse_provider=_parse_provider(
            [{"type": "food", "name": "milk", "quantity_text": "1 cup", "unit": "cup", "amount": 1}]
        ),
        estimates=[],
        food_source=FakeFoodSource({"milk": _fdc_facts("milk", calories_per_100g=50.0)}),
    )
    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=scoped_pipeline
    )

    assert result.event_status is LogEventStatus.COMPLETED
    run = _latest_run(session, event_id)
    scoped = [entry for entry in run.trace if entry.get("step") == "scoped_reestimate"]
    assert any(entry.get("outcome") == "component_resolved" for entry in scoped)


def test_scoped_deterministic_failure_reopens_answerable_question(
    client: TestClient, session: Session
) -> None:
    """A deterministic scoped failure never leaves an inert answerless partial.

    The 2026-07-10 failure class extended: when a component's answered scoped re-estimate
    fails closed (unparseable), the event stays ``partially_resolved`` but re-opens a
    *fresh, answerable* item-scoped question — the committed sibling is preserved — instead
    of stranding the user with a ``partially_resolved`` event and no answerable question.
    """

    user_id, event_id, resolved, unresolved = _run_mixed_first_pass(
        client, session, "fty329-dead-partial@example.com"
    )
    question = _questions(session, event_id)[0]
    current_user = session.get(User, user_id)
    assert current_user is not None
    clarification_service.answer_clarification_question(
        session, user_id, current_user, event_id, question.id, "some nonsense"
    )

    # A deterministic parse failure (unparseable) on the scoped re-estimate: non-retryable.
    failing_parse = FakeProvider(
        responses=[{"disposition": "unparseable", "confidence": 0.0, "reason": "not a log"}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    scoped_pipeline = _pipeline(
        session=session,
        parse_provider=failing_parse,
        estimates=[],
        food_source=FakeFoodSource({"milk": _fdc_facts("milk", calories_per_100g=50.0)}),
    )
    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=scoped_pipeline
    )

    # Not a whole-event failure and not a dead partial: the event stays partial and the
    # committed sibling is untouched.
    assert result.event_status is LogEventStatus.PARTIALLY_RESOLVED
    assert result.should_retry is False
    chicken_after = session.get(DerivedFoodItem, resolved.id)
    milk_after = session.get(DerivedFoodItem, unresolved.id)
    assert chicken_after is not None and chicken_after.status == DerivedItemStatus.RESOLVED
    assert chicken_after.calories == pytest.approx(300.0)
    assert milk_after is not None and milk_after.status == DerivedItemStatus.UNRESOLVED

    # The user is not stranded: a fresh, answerable item-scoped question is served on the
    # still-open component (the read model filters the already-answered one).
    open_questions = log_event_service.list_clarification_questions(
        session, user_id, current_user, event_id
    )
    assert [q.derived_food_item_id for q in open_questions] == [unresolved.id]
    answered_ids = set(
        session.scalars(
            select(ClarificationAnswer.question_id).where(
                ClarificationAnswer.log_event_id == event_id
            )
        )
    )
    assert open_questions[0].id not in answered_ids
    # The failure is recorded in the sanitized trace, not swallowed.
    assert "component_reestimate_failed" in _trace_outcomes(_latest_run(session, event_id))


def _seed_pg_user(pg_engine: Engine) -> uuid.UUID:
    """Create one user with a UTC profile on the Postgres engine."""

    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id, timezone="UTC"))
        session.commit()
        return user.id


def test_partial_emit_and_scoped_reestimate_on_postgres(pg_engine: Engine) -> None:
    """FTY-329 end-to-end on the production engine: emit -> answer -> scoped complete.

    Proves the DB-touching item-scoped persistence works on Postgres, not only SQLite:
    the mixed run commits the sibling + one item-scoped question (event
    ``partially_resolved``), the real answer flow re-costs only the open component in
    place, and the event completes with both components counted and the sibling never
    duplicated.
    """

    upgrade(pg_engine, "head")
    factory = create_session_factory(pg_engine)
    user_id = _seed_pg_user(pg_engine)

    with factory() as session:
        event = LogEvent(
            user_id=user_id,
            raw_text="grilled chicken 150g and a glass of milk",
            status=LogEventStatus.PENDING,
        )
        session.add(event)
        session.commit()
        event_id = event.id
        pipeline = _pipeline(
            session=session,
            parse_provider=_parse_provider(
                [
                    {
                        "type": "food",
                        "name": "grilled chicken",
                        "quantity_text": "150g",
                        "unit": "g",
                        "amount": 150,
                    },
                    {"type": "food", "name": "milk", "quantity_text": ""},
                ]
            ),
            estimates=[_low_confidence_estimate()],
            food_source=FakeFoodSource(
                {"grilled chicken": _fdc_facts("grilled chicken", calories_per_100g=200.0)}
            ),
        )
        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=pipeline
        )
        assert result.event_status is LogEventStatus.PARTIALLY_RESOLVED
        foods = _foods(session, event_id)
        chicken = next(f for f in foods if f.status == DerivedItemStatus.RESOLVED)
        milk = next(f for f in foods if f.status == DerivedItemStatus.UNRESOLVED)
        chicken_id, milk_id = chicken.id, milk.id
        assert chicken.calories == pytest.approx(300.0)
        question_id = _questions(session, event_id)[0].id

    with factory() as session:
        current_user = session.get(User, user_id)
        assert current_user is not None
        clarification_service.answer_clarification_question(
            session, user_id, current_user, event_id, question_id, "1 cup"
        )
        scoped_pipeline = _pipeline(
            session=session,
            parse_provider=_parse_provider(
                [
                    {
                        "type": "food",
                        "name": "milk",
                        "quantity_text": "1 cup",
                        "unit": "cup",
                        "amount": 1,
                    }
                ]
            ),
            estimates=[],
            food_source=FakeFoodSource({"milk": _fdc_facts("milk", calories_per_100g=50.0)}),
        )
        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=scoped_pipeline
        )
        assert result.event_status is LogEventStatus.COMPLETED

    with factory() as session:
        current_user = session.get(User, user_id)
        loaded_event = session.get(LogEvent, event_id)
        assert current_user is not None and loaded_event is not None
        chicken_after = session.get(DerivedFoodItem, chicken_id)
        milk_after = session.get(DerivedFoodItem, milk_id)
        assert chicken_after is not None and milk_after is not None
        # The sibling is untouched; the open component resolved in place (no duplicate).
        assert chicken_after.status == DerivedItemStatus.RESOLVED
        assert chicken_after.calories == pytest.approx(300.0)
        assert milk_after.status == DerivedItemStatus.RESOLVED
        assert milk_after.calories == pytest.approx(120.0)
        assert len(_foods(session, event_id)) == 2
        summary = daily_summary_service.get_daily_summary(
            session, user_id, current_user, loaded_event.created_at.date()
        )
        assert summary.intake.calories == pytest.approx(420.0)
        assert summary.uncounted_entries == 0
