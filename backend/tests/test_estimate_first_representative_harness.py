"""FTY-302 representative estimate-first regression harness.

The tests load a synthetic corpus and drive each default-mode case through a real
user-owned log event, the real parse/exercise/user-text/food/rough-resolution
pipeline, and the real persistence path. External provider/search/fetch seams are
faked locally so CI never spends tokens or opens network connections.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus, SourceType
from app.estimator.parse import DEFAULT_CLARIFICATION_QUESTION
from app.estimator.processing import ProcessResult, process_estimation
from app.models.derived import ClarificationQuestion, DerivedExerciseItem, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource
from app.settings import EstimatorClarifyMode
from tests.estimate_first_representative_harness import (
    MODES,
    build_pipeline,
    case_input,
    estimate_first_params,
    expectation,
    fixture_model_provider,
    fixture_parse_provider,
    load_corpus,
    mode_difference_params,
    seed_event,
    set_weight,
)

_REQUIRED_CLASSES = {
    "bare_recognizable_food",
    "crackers_hummus",
    "counted_crackers_hummus",
    "toppables_pb_sandwich",
    "worded_portions",
    "user_stated_nutrition",
    "exercise_only",
    "food_plus_exercise",
    "impossible_missing_identity",
    "non_log_text",
    "unrecoverable_schema_invalid",
    "provider_config_error",
}
_GENERIC_QUESTION_SNIPPETS = (
    DEFAULT_CLARIFICATION_QUESTION,
    "How much did you have",
    "What did you have",
)


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def test_representative_corpus_fixture_is_classified() -> None:
    cases = load_corpus()

    assert {str(case["class"]) for case in cases} >= _REQUIRED_CLASSES
    assert all(set(cast(dict[str, Any], case["expectations"])) == set(MODES) for case in cases)
    assert sum(1 for case in cases if case["class"] == "toppables_pb_sandwich") >= 2
    assert sum(1 for case in cases if "crackers_hummus" in str(case["class"])) >= 3
    assert all(isinstance(case["input"], str) and case["input"].strip() for case in cases)


def test_fixture_provider_outputs_cover_realistic_imperfections() -> None:
    samples = [
        _inner_sample(sample)
        for case in load_corpus()
        for sample in cast(list[dict[str, Any]], case["parse_samples"])
    ]
    items = [
        item for sample in samples for item in cast(list[dict[str, Any]], sample.get("items", []))
    ]

    assert any(sample.get("disposition") == "needs_clarification" for sample in samples)
    assert any(float(cast(float | int, sample.get("confidence", 1.0))) < 0.45 for sample in samples)
    assert any("result" in sample for case in load_corpus() for sample in case["parse_samples"])
    assert any(item.get("amount") is None for item in items)
    assert any("cracker sandwich" in str(item.get("name", "")).casefold() for item in items)


@pytest.mark.parametrize("case", estimate_first_params())
def test_estimate_first_representative_corpus_completes_recognizable_logs(
    client: TestClient,
    session: Session,
    caplog: pytest.LogCaptureFixture,
    case: dict[str, Any],
) -> None:
    outcome = _run_case(client, session, caplog, case, "estimate_first")

    if bool(case.get("recognizable")):
        assert outcome.result.event_status is LogEventStatus.COMPLETED
        assert outcome.questions == []
    _assert_expected_outcome(outcome, expectation(case, "estimate_first"))
    _assert_content_free_metadata(outcome, caplog)


@pytest.mark.parametrize(("case", "mode"), mode_difference_params())
def test_balanced_and_strict_mode_differences_are_pinned(
    client: TestClient,
    session: Session,
    caplog: pytest.LogCaptureFixture,
    case: dict[str, Any],
    mode: EstimatorClarifyMode,
) -> None:
    outcome = _run_case(client, session, caplog, case, mode)

    _assert_expected_outcome(outcome, expectation(case, mode))
    _assert_content_free_metadata(outcome, caplog)


class _Outcome:
    def __init__(
        self,
        *,
        case: dict[str, Any],
        mode: EstimatorClarifyMode,
        event_id: uuid.UUID,
        result: ProcessResult,
        run: EstimationRun,
        foods: list[DerivedFoodItem],
        exercises: list[DerivedExerciseItem],
        evidence: list[EvidenceSource],
        questions: list[ClarificationQuestion],
    ) -> None:
        self.case = case
        self.mode = mode
        self.event_id = event_id
        self.result = result
        self.run = run
        self.foods = foods
        self.exercises = exercises
        self.evidence = evidence
        self.questions = questions


def _run_case(
    client: TestClient,
    session: Session,
    caplog: pytest.LogCaptureFixture,
    case: dict[str, Any],
    mode: EstimatorClarifyMode,
) -> _Outcome:
    caplog.set_level(logging.INFO)
    caplog.clear()
    user_id, event_id = seed_event(client, case, mode)
    set_weight(session, user_id)
    pipeline = build_pipeline(
        session,
        mode=mode,
        parse_provider=fixture_parse_provider(case),
        model_provider=fixture_model_provider(case),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    return _Outcome(
        case=case,
        mode=mode,
        event_id=event_id,
        result=result,
        run=_run(session, event_id),
        foods=_foods(session, event_id),
        exercises=_exercises(session, event_id),
        evidence=_evidence(session, event_id),
        questions=_questions(session, event_id),
    )


def _assert_expected_outcome(outcome: _Outcome, expected: dict[str, Any]) -> None:
    assert str(outcome.result.event_status) == expected["event_status"]
    assert len(outcome.foods) == expected["foods"]
    assert len(outcome.exercises) == expected["exercises"]
    assert len(outcome.questions) == expected["questions"]

    if expected["event_status"] == "completed":
        _assert_completed_items(outcome, expected)
    elif expected["event_status"] == "needs_clarification":
        assert outcome.foods == []
        assert outcome.exercises == []
        assert outcome.evidence == []
    else:
        assert expected["event_status"] == "failed"
        assert outcome.foods == []
        assert outcome.exercises == []
        assert outcome.evidence == []
        assert outcome.questions == []


def _assert_completed_items(outcome: _Outcome, expected: dict[str, Any]) -> None:
    assert outcome.questions == []
    assert all(food.status == DerivedItemStatus.RESOLVED for food in outcome.foods)
    assert all(exercise.status == DerivedItemStatus.RESOLVED for exercise in outcome.exercises)
    assert all(food.calories is not None and food.calories > 0 for food in outcome.foods)
    assert all(
        exercise.active_calories is not None and exercise.active_calories > 0
        for exercise in outcome.exercises
    )

    rough_foods = int(expected.get("rough_foods", 0))
    user_text_foods = int(expected.get("user_text_foods", 0))
    assert len(outcome.evidence) == rough_foods + user_text_foods

    if rough_foods:
        rough = [row for row in outcome.evidence if row.source_type == SourceType.MODEL_PRIOR.value]
        assert len(rough) == rough_foods
        for row in rough:
            assert row.source_ref == "model_prior"
            assert row.product_id is None
            assumptions = row.assumptions
            assert assumptions is not None
            assert any("model_prior" in assumption for assumption in assumptions)

    if user_text_foods:
        user_text = [
            row for row in outcome.evidence if row.source_type == SourceType.USER_TEXT.value
        ]
        assert len(user_text) == user_text_foods
        assert all(row.basis == "as_logged" for row in user_text)
        assert all(row.source_ref.startswith("user_text:") for row in user_text)

    if outcome.mode == "estimate_first" and bool(outcome.case.get("recognizable")):
        persisted = _persisted_metadata(outcome)
        assert all(snippet not in persisted for snippet in _GENERIC_QUESTION_SNIPPETS)


def _assert_content_free_metadata(outcome: _Outcome, caplog: pytest.LogCaptureFixture) -> None:
    raw_text = case_input(outcome.case)
    persisted = _persisted_metadata(outcome)
    assert raw_text not in persisted
    assert raw_text not in caplog.text


def _persisted_metadata(outcome: _Outcome) -> str:
    fields: list[object] = [
        outcome.run.trace,
        outcome.run.assumptions,
        outcome.run.source_refs,
        outcome.run.validation_errors,
        outcome.run.error,
    ]
    for row in outcome.evidence:
        fields.extend([row.source_ref, row.assumptions])
    return repr(fields)


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _exercises(session: Session, event_id: uuid.UUID) -> list[DerivedExerciseItem]:
    return list(
        session.scalars(
            select(DerivedExerciseItem).where(DerivedExerciseItem.log_event_id == event_id)
        )
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


def _run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def _inner_sample(sample: dict[str, Any]) -> dict[str, Any]:
    if set(sample) == {"result"}:
        return cast(dict[str, Any], sample["result"])
    return sample
