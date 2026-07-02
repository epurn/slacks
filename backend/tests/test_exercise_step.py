"""Unit tests for the exercise-burn pipeline step (FTY-043).

Pin the step's routing and evidence without a database: exercise candidates resolve
into costed items with net active calories; an unknown activity or a missing
duration routes to ``needs_clarification`` with a sanitized question; a missing body
weight fails closed; food-only events are a no-op; and the curated MET table
version/source plus the net-active formula are recorded as run evidence without
leaking the weight or any raw text.
"""

from __future__ import annotations

import uuid

import pytest

from app.estimator.exercise import NET_ACTIVE_FORMULA
from app.estimator.exercise_step import (
    DURATION_QUESTION,
    UNKNOWN_ACTIVITY_QUESTION,
    ExerciseCalculateStep,
)
from app.estimator.met_table import MET_TABLE_SOURCE, MET_TABLE_VERSION
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    NeedsClarification,
    StepFailed,
)


def _context(
    *, weight_kg: float | None = 70.0, exercise: list[CandidateDraft] | None = None
) -> EstimationContext:
    ctx = EstimationContext(
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="ignored",
        weight_kg=weight_kg,
    )
    ctx.exercise_candidates = list(exercise or [])
    return ctx


def _run(
    name: str, quantity_text: str = "", unit: str | None = None, amount: float | None = None
) -> CandidateDraft:
    return CandidateDraft(name=name, quantity_text=quantity_text, unit=unit, amount=amount)


def test_resolves_candidate_into_active_calories() -> None:
    ctx = _context(exercise=[_run("run", "30 min", "min", 30.0)])

    ExerciseCalculateStep().run(ctx)

    assert len(ctx.resolved_exercise_items) == 1
    item = ctx.resolved_exercise_items[0]
    assert item.name == "run"
    assert item.met == 7.0
    assert item.duration_minutes == 30.0
    assert item.active_calories == 210.0
    assert ctx.trace[-1] == {"step": "exercise_calculate", "status": "ok"}


def test_records_met_table_version_and_formula_as_evidence() -> None:
    ctx = _context(exercise=[_run("run", "30 min", "min", 30.0)])

    ExerciseCalculateStep().run(ctx)

    assert f"met_table:{MET_TABLE_VERSION}" in ctx.source_refs
    assert MET_TABLE_SOURCE in ctx.source_refs
    assert NET_ACTIVE_FORMULA in ctx.assumptions
    # Evidence is sanitized: the user's weight never appears.
    assert "70" not in " ".join(ctx.source_refs + ctx.assumptions)


def test_unknown_activity_routes_to_clarification() -> None:
    ctx = _context(exercise=[_run("teleporting", "30 min", "min", 30.0)])

    with pytest.raises(NeedsClarification) as excinfo:
        ExerciseCalculateStep().run(ctx)

    assert excinfo.value.reason == "unknown_activity"
    assert [q.text for q in ctx.clarification_questions] == [UNKNOWN_ACTIVITY_QUESTION]
    assert [q.options for q in ctx.clarification_questions] == [[]]


def test_missing_duration_routes_to_clarification() -> None:
    ctx = _context(exercise=[_run("run", "went for a run")])

    with pytest.raises(NeedsClarification) as excinfo:
        ExerciseCalculateStep().run(ctx)

    assert excinfo.value.reason == "missing_duration"
    assert [q.text for q in ctx.clarification_questions] == [DURATION_QUESTION]
    assert [q.options for q in ctx.clarification_questions] == [[]]


def test_missing_body_weight_fails_closed() -> None:
    ctx = _context(weight_kg=None, exercise=[_run("run", "30 min", "min", 30.0)])

    with pytest.raises(StepFailed) as excinfo:
        ExerciseCalculateStep().run(ctx)

    assert excinfo.value.reason == "missing_body_weight"


def test_food_only_event_is_a_no_op() -> None:
    # No exercise candidates: the step records itself but consults no MET table.
    ctx = _context(exercise=[])

    ExerciseCalculateStep().run(ctx)

    assert ctx.resolved_exercise_items == []
    assert ctx.source_refs == []
    assert ctx.trace[-1] == {"step": "exercise_calculate", "status": "ok"}


def test_multiple_candidates_all_resolve() -> None:
    ctx = _context(
        exercise=[
            _run("run", "30 min", "min", 30.0),
            _run("walk", "1 hour", "h", 1.0),
        ]
    )

    ExerciseCalculateStep().run(ctx)

    assert [i.name for i in ctx.resolved_exercise_items] == ["run", "walk"]
    assert ctx.resolved_exercise_items[0].active_calories == 210.0
    # walking MET 3.5, 70 kg, 60 min: (3.5 - 1) * 70 * 1.0 = 175.0
    assert ctx.resolved_exercise_items[1].active_calories == 175.0


def test_source_refs_idempotent_no_duplicates_on_repeat() -> None:
    """Running the step twice does not duplicate source refs (de-duplication works)."""

    ctx = _context(exercise=[_run("run", "30 min", "min", 30.0)])

    # First resolution
    ExerciseCalculateStep().run(ctx)
    first_refs = list(ctx.source_refs)

    # Second resolution (simulating the step running again)
    ExerciseCalculateStep().run(ctx)
    second_refs = list(ctx.source_refs)

    # Source refs should be identical: no duplicates added
    assert first_refs == second_refs
    assert first_refs.count(f"met_table:{MET_TABLE_VERSION}") == 1
    assert first_refs.count(MET_TABLE_SOURCE) == 1
