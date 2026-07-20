"""Prior-correction resolution tier (FTY-406).

Corrections were write-only telemetry: a food the user had already hand-corrected
was re-guessed from scratch on the next log. These tests pin the closed loop — a
prior confident correction resolves a later estimate for the same normalized name
from that curated value, short-circuiting the wrong source match — and the safety
rails around it: per-user isolation, ambiguous-priors fall-through, quantity rescale
vs. mismatch, and no regression for an item with no matching prior.

The centrepiece is the **black-coffee regression fixture** (FTY-373 lineage): the
exact operator case — a "black coffee" that first-passed a deterministic 148.8 kcal
source match, was auto-``re_match``ed to 4.8, then hand-edited to 3 — now resolves to
3, not 148.8, on the next estimate.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import (
    CandidateType,
    CorrectionSource,
    DerivedItemStatus,
    LogEventStatus,
    SourceType,
)
from app.estimator.correction_resolution import (
    PRIOR_CORRECTION_RESCALED_ASSUMPTION,
    PriorCorrectionResolver,
    PriorCorrectionResolveStep,
)
from app.estimator.pipeline import CandidateDraft, EstimationContext, Pipeline
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.identity import User
from app.models.log_events import LogEvent
from app.normalization import normalize_text


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _new_user(session: Session) -> uuid.UUID:
    user = User()
    session.add(user)
    session.flush()
    return user.id


#: The estimator's wrong first guess snapshotted into ``calories_estimated`` — the
#: 148.8 the operator's "black coffee" re-guessed every time before the correction.
_ORIGINAL_GUESS = 148.8

#: ``(protein_g, carbs_g, fat_g)`` — the corrected macros; all unknown by default.
_NO_MACROS: tuple[float | None, float | None, float | None] = (None, None, None)
#: ``(unit, amount, quantity_text)`` — the item's stated portion; unportioned default.
_UNPORTIONED: tuple[str | None, float | None, str] = (None, None, "")


def _seed_corrected_food(
    session: Session,
    user_id: uuid.UUID,
    *,
    name: str,
    calories: float,
    macros: tuple[float | None, float | None, float | None] = _NO_MACROS,
    grams: float | None = None,
    portion: tuple[str | None, float | None, str] = _UNPORTIONED,
    corrected_at: datetime | None = None,
    voided: bool = False,
) -> uuid.UUID:
    """Seed a food item the user has hand-corrected (a ``user_edit`` on calories).

    ``calories`` is the corrected current value the resolution tier must replay; the
    estimator's original wrong guess (:data:`_ORIGINAL_GUESS`) is snapshotted into
    ``calories_estimated`` exactly as the edit path does.
    """

    protein_g, carbs_g, fat_g = macros
    unit, amount, quantity_text = portion
    event = LogEvent(
        user_id=user_id,
        raw_text="seed",
        status=LogEventStatus.COMPLETED,
        voided_at=datetime.now(UTC) if voided else None,
    )
    session.add(event)
    session.flush()

    item = DerivedFoodItem(
        log_event_id=event.id,
        user_id=user_id,
        name=name,
        quantity_text=quantity_text,
        unit=unit,
        amount=amount,
        status=DerivedItemStatus.RESOLVED,
        grams=grams,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        calories_estimated=_ORIGINAL_GUESS,
        protein_g_estimated=protein_g,
        carbs_g_estimated=carbs_g,
        fat_g_estimated=fat_g,
    )
    session.add(item)
    session.flush()

    correction = Correction(
        user_id=user_id,
        item_type=CandidateType.FOOD,
        derived_food_item_id=item.id,
        field="calories",
        old_value=_ORIGINAL_GUESS,
        new_value=calories,
        source=CorrectionSource.USER_EDIT,
        created_at=corrected_at or datetime.now(UTC),
    )
    session.add(correction)
    session.commit()
    return item.id


def _context(user_id: uuid.UUID, candidates: list[CandidateDraft]) -> EstimationContext:
    context = EstimationContext(log_event_id=uuid.uuid4(), user_id=user_id, raw_text="black coffee")
    context.food_candidates = candidates
    return context


def _run_step(session: Session, context: EstimationContext) -> None:
    step = PriorCorrectionResolveStep(PriorCorrectionResolver(session=session))
    step.run(context)


class _WrongGuessStep:
    """A stand-in food step that fails loudly if it ever sees a claimed candidate.

    Proves the prior-correction tier resolves the item *without first producing the
    wrong source-match value*: if the correction claimed the candidate, this step
    never sees it, so the 148.8 guess is never produced.
    """

    name = "wrong_guess"

    def __init__(self, forbidden_name: str) -> None:
        self._forbidden = normalize_text(forbidden_name)

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        for candidate in context.food_candidates:
            if normalize_text(candidate.name) == self._forbidden:
                raise AssertionError(
                    "prior correction should have claimed the candidate before source lookup"
                )


# --------------------------------------------------------------------------- #
# Short-circuit + the black-coffee regression fixture
# --------------------------------------------------------------------------- #


def test_black_coffee_regression_resolves_to_the_corrected_value_not_148_8(
    session: Session,
) -> None:
    """The exact operator case: a prior "black coffee = 3" resolves the next estimate
    to 3, not the deterministic 148.8 source match it used to re-guess every time."""

    user_id = _new_user(session)
    _seed_corrected_food(session, user_id, name="black coffee", calories=3.0)

    context = _context(user_id, [CandidateDraft(name="black coffee")])
    # The wrong-guess food step must never see the claimed candidate.
    Pipeline(
        [
            PriorCorrectionResolveStep(PriorCorrectionResolver(session=session)),
            _WrongGuessStep("black coffee"),
        ]
    ).run(context)

    assert context.food_candidates == []
    assert len(context.resolved_food_items) == 1
    resolved = context.resolved_food_items[0]
    assert resolved.calories == 3.0
    assert resolved.calories != 148.8
    assert resolved.source_type == SourceType.PRIOR_CORRECTION.value
    assert resolved.source_ref.startswith("prior_correction:")
    assert resolved.basis == "as_logged"
    assert resolved.product_id is None
    assert SourceType.PRIOR_CORRECTION.value in context.source_refs


def test_prior_correction_carries_corrected_macros_and_provenance(session: Session) -> None:
    user_id = _new_user(session)
    _seed_corrected_food(
        session,
        user_id,
        name="protein shake",
        calories=180.0,
        macros=(30.0, 8.0, 2.0),
    )

    context = _context(user_id, [CandidateDraft(name="Protein Shake")])
    _run_step(session, context)

    assert len(context.resolved_food_items) == 1
    resolved = context.resolved_food_items[0]
    assert (resolved.calories, resolved.protein_g, resolved.carbs_g, resolved.fat_g) == (
        180.0,
        30.0,
        8.0,
        2.0,
    )
    # A same-portion direct match carries no rescale assumption.
    assert resolved.assumptions == ()


# --------------------------------------------------------------------------- #
# No regression: no matching prior falls through untouched
# --------------------------------------------------------------------------- #


def test_no_matching_prior_correction_falls_through(session: Session) -> None:
    user_id = _new_user(session)
    _seed_corrected_food(session, user_id, name="black coffee", calories=3.0)

    # A different food the user never corrected is left for the normal food step.
    context = _context(user_id, [CandidateDraft(name="white rice", quantity_text="150g")])
    _run_step(session, context)

    assert [c.name for c in context.food_candidates] == ["white rice"]
    assert context.resolved_food_items == []


def test_only_non_user_edit_corrections_do_not_resolve(session: Session) -> None:
    """A food auto-``re_match``ed but never hand-edited is not a user correction, so it
    falls through — the tier replays deliberate value overrides only."""

    user_id = _new_user(session)
    event = LogEvent(user_id=user_id, raw_text="seed", status=LogEventStatus.COMPLETED)
    session.add(event)
    session.flush()
    item = DerivedFoodItem(
        log_event_id=event.id,
        user_id=user_id,
        name="black coffee",
        quantity_text="",
        status=DerivedItemStatus.RESOLVED,
        calories=4.8,
    )
    session.add(item)
    session.flush()
    session.add(
        Correction(
            user_id=user_id,
            item_type=CandidateType.FOOD,
            derived_food_item_id=item.id,
            field="calories",
            old_value=148.8,
            new_value=4.8,
            source=CorrectionSource.RE_MATCH,
        )
    )
    session.commit()

    context = _context(user_id, [CandidateDraft(name="black coffee")])
    _run_step(session, context)

    assert [c.name for c in context.food_candidates] == ["black coffee"]
    assert context.resolved_food_items == []


def test_correction_on_a_voided_event_is_not_replayed(session: Session) -> None:
    user_id = _new_user(session)
    _seed_corrected_food(session, user_id, name="black coffee", calories=3.0, voided=True)

    context = _context(user_id, [CandidateDraft(name="black coffee")])
    _run_step(session, context)

    assert [c.name for c in context.food_candidates] == ["black coffee"]
    assert context.resolved_food_items == []


# --------------------------------------------------------------------------- #
# Per-user isolation
# --------------------------------------------------------------------------- #


def test_lookup_is_per_user_no_cross_user_match(session: Session) -> None:
    owner = _new_user(session)
    other = _new_user(session)
    # The *other* user corrected black coffee to 3; the owner never did.
    _seed_corrected_food(session, other, name="black coffee", calories=3.0)

    context = _context(owner, [CandidateDraft(name="black coffee")])
    _run_step(session, context)

    # No cross-user leakage: the owner's black coffee is not resolved from another
    # user's correction, so it falls through to normal resolution.
    assert [c.name for c in context.food_candidates] == ["black coffee"]
    assert context.resolved_food_items == []


# --------------------------------------------------------------------------- #
# Ambiguity: conflicting priors fall through
# --------------------------------------------------------------------------- #


def test_conflicting_priors_fall_through(session: Session) -> None:
    user_id = _new_user(session)
    base = datetime.now(UTC)
    # Same normalized name, same (unportioned) portion, two *different* corrected
    # values → ambiguous → fall through.
    _seed_corrected_food(session, user_id, name="black coffee", calories=3.0, corrected_at=base)
    _seed_corrected_food(
        session,
        user_id,
        name="black coffee",
        calories=45.0,
        corrected_at=base - timedelta(hours=1),
    )

    context = _context(user_id, [CandidateDraft(name="black coffee")])
    _run_step(session, context)

    assert [c.name for c in context.food_candidates] == ["black coffee"]
    assert context.resolved_food_items == []


def test_agreeing_priors_are_stable_and_resolve(session: Session) -> None:
    user_id = _new_user(session)
    base = datetime.now(UTC)
    # Two corrections agreeing on 3 → stable → resolves.
    _seed_corrected_food(session, user_id, name="black coffee", calories=3.0, corrected_at=base)
    _seed_corrected_food(
        session,
        user_id,
        name="black coffee",
        calories=3.0,
        corrected_at=base - timedelta(hours=1),
    )

    context = _context(user_id, [CandidateDraft(name="black coffee")])
    _run_step(session, context)

    assert context.food_candidates == []
    assert len(context.resolved_food_items) == 1
    assert context.resolved_food_items[0].calories == 3.0


# --------------------------------------------------------------------------- #
# Quantity: rescale vs. mismatch
# --------------------------------------------------------------------------- #


def test_different_quantity_rescales_from_a_mass_bearing_prior(session: Session) -> None:
    user_id = _new_user(session)
    # Prior: "latte 240ml = 120 kcal" (0.5 kcal/g at 240 g).
    _seed_corrected_food(
        session,
        user_id,
        name="latte",
        calories=120.0,
        macros=(6.0, None, None),
        grams=240.0,
        portion=("ml", 240.0, "240ml"),
    )

    # A larger latte (480 ml) is rescaled per-gram, not mismatched.
    context = _context(
        user_id,
        [CandidateDraft(name="latte", unit="ml", amount=480.0, quantity_text="480ml")],
    )
    _run_step(session, context)

    assert context.food_candidates == []
    resolved = context.resolved_food_items[0]
    assert resolved.calories == 240.0
    assert resolved.protein_g == 12.0
    assert resolved.grams == 480.0
    assert PRIOR_CORRECTION_RESCALED_ASSUMPTION in resolved.assumptions


def test_different_quantity_without_a_mass_bearing_prior_falls_through(session: Session) -> None:
    """An as-logged prior with no portion mass cannot be rescaled to a different
    quantity, so the candidate falls through rather than mismatching."""

    user_id = _new_user(session)
    # Prior: bare "black coffee = 3", no grams — an as-logged total.
    _seed_corrected_food(session, user_id, name="black coffee", calories=3.0, grams=None)

    # A now-quantified log ("2 black coffees") differs and can't be rescaled.
    context = _context(user_id, [CandidateDraft(name="black coffee", amount=2.0)])
    _run_step(session, context)

    assert [c.name for c in context.food_candidates] == ["black coffee"]
    assert context.resolved_food_items == []


# --------------------------------------------------------------------------- #
# Precedence: a barcode candidate is not claimed by the correction tier
# --------------------------------------------------------------------------- #


def test_barcode_candidate_is_left_for_the_product_source(session: Session) -> None:
    user_id = _new_user(session)
    _seed_corrected_food(session, user_id, name="black coffee", calories=3.0)

    context = _context(user_id, [CandidateDraft(name="black coffee", barcode="0123456789012")])
    _run_step(session, context)

    # A scanned product is the current entry's own explicit evidence: the correction
    # tier leaves it for the barcode source.
    assert [c.barcode for c in context.food_candidates] == ["0123456789012"]
    assert context.resolved_food_items == []


def test_step_is_skipped_when_there_are_no_food_candidates(session: Session) -> None:
    user_id = _new_user(session)
    context = _context(user_id, [])
    _run_step(session, context)
    assert context.resolved_food_items == []
