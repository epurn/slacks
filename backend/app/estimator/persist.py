"""Persistence layer for the estimation worker (FTY-331).

The functions here take the structured products the pipeline accumulated on an
:class:`~app.estimator.pipeline.EstimationContext` and write them as user-owned
rows: derived food/exercise items, their evidence-source provenance,
clarification questions, and the discard-by-default raw label image. They are the
row-writing half of the estimation worker, extracted verbatim from
:mod:`app.estimator.processing` so the state machine there stays focused on job
claim, idempotency, and outcome routing.

Behaviour is unchanged from when this code lived in ``processing.py``: every write
carries ownership (``user_id``) and the owning ``log_event_id`` for object-level
authorization and retention, void exclusion and discard-by-default label
retention are preserved, and no raw user text ever reaches a persisted row,
assumption string, or source ref (security baseline +
``docs/security/data-retention.md``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.enums import DerivedItemStatus
from app.estimator.label_step import LabelInput
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    PipelineOutcome,
    ResolvedFoodItem,
)
from app.models.derived import (
    ClarificationAnswer,
    ClarificationQuestion,
    DerivedExerciseItem,
    DerivedFoodItem,
)
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource
from app.models.identity import User
from app.services.attachments import ingest_upload


def _persist_candidates(session: Session, run: EstimationRun, context: EstimationContext) -> None:
    """Persist the parsed food/exercise candidates as user-owned rows.

    Food candidates the resolver (FTY-044) costed are written ``resolved`` with their
    calories/macros plus a user-owned ``evidence_sources`` provenance row; if the food
    step did not resolve them (e.g. the source was unconfigured), they fall back to
    ``unresolved`` rows with no calories. Exercise candidates the calculator (FTY-043)
    costed are written ``resolved`` with their ``active_calories``; otherwise they fall
    back to ``unresolved``. Candidate names and portions are schema-validated *data*
    written through parameterized ORM inserts — never executed. Ownership (``user_id``)
    and the owning ``log_event_id`` are carried on every row for object-level
    authorization and retention.
    """

    if context.resolved_label_items:
        _persist_resolved_labels(session, run, context)

    _persist_food(session, run, context)

    if context.resolved_exercise_items:
        for item in context.resolved_exercise_items:
            session.add(
                DerivedExerciseItem(
                    log_event_id=run.log_event_id,
                    user_id=run.user_id,
                    name=item.name,
                    quantity_text=item.quantity_text,
                    unit=item.unit,
                    amount=item.amount,
                    status=DerivedItemStatus.RESOLVED,
                    active_calories=item.active_calories,
                    # Snapshot the estimator's original burn at creation so a later
                    # user correction (FTY-051) preserves it immutably.
                    active_calories_estimated=item.active_calories,
                )
            )
    else:
        for draft in context.exercise_candidates:
            session.add(
                DerivedExerciseItem(
                    log_event_id=run.log_event_id,
                    user_id=run.user_id,
                    name=draft.name,
                    quantity_text=draft.quantity_text,
                    unit=draft.unit,
                    amount=draft.amount,
                )
            )


def _persist_food(session: Session, run: EstimationRun, context: EstimationContext) -> None:
    """Persist the food side of a completed estimation: resolved + unresolved rows.

    When the food step ran it sorts every candidate into exactly one bucket —
    ``resolved_food_items`` (USDA/OFF/official/model-prior), ``unresolved_food_candidates``
    (no applicable source), or, if no official step ran, leftover
    ``pending_official_candidates``. Persisting the resolved items plus the two
    unresolved buckets covers every candidate without ever dropping one in a mixed
    batch. When no food step ran at all (a resolver-less pipeline), all three buckets
    are empty and the parsed ``food_candidates`` are persisted ``unresolved`` instead —
    the pre-FTY-044 behavior.
    """

    leftover = context.unresolved_food_candidates + context.pending_official_candidates
    # Item-scoped clarified components (FTY-329) are persisted separately (as
    # ``unresolved`` rows owning their question) by
    # :func:`_persist_item_scoped_clarifications`; counting them here keeps the food
    # step's "sort every candidate into exactly one bucket" invariant, so the
    # all-candidates fallback below never re-persists a component that already resolved
    # or already owns an item-scoped question.
    if context.resolved_food_items or leftover or context.item_scoped_clarifications:
        _persist_resolved_food(session, run, context)
        for draft in leftover:
            session.add(_unresolved_food_row(run, draft))
        return

    for draft in context.food_candidates:
        session.add(_unresolved_food_row(run, draft))


def _unresolved_food_row(run: EstimationRun, draft: CandidateDraft) -> DerivedFoodItem:
    """Build an ``unresolved`` derived food row from a parsed candidate (no calories)."""

    return DerivedFoodItem(
        log_event_id=run.log_event_id,
        user_id=run.user_id,
        name=draft.name,
        quantity_text=draft.quantity_text,
        unit=draft.unit,
        amount=draft.amount,
    )


def _persist_resolved_food(
    session: Session, run: EstimationRun, context: EstimationContext
) -> None:
    """Persist resolved food items with calories/macros and their evidence rows.

    Each item becomes a ``resolved`` ``derived_food_items`` row (flushed so its id is
    available) plus a user-owned ``evidence_sources`` row recording the source
    reference, content hash, fetch time, per-100g facts snapshot, and any documented
    ``assumptions`` (the model-prior fallback reason) — never a raw page. The cached
    global ``products`` rows the resolver created are already in the session and
    committed with this transaction; an official-source or model-prior item carries no
    ``product_id``.
    """

    for item in context.resolved_food_items:
        food = DerivedFoodItem(
            log_event_id=run.log_event_id,
            user_id=run.user_id,
            name=item.name,
            quantity_text=item.quantity_text,
            unit=item.unit,
            amount=item.amount,
            status=DerivedItemStatus.RESOLVED,
            grams=item.grams,
            calories=item.calories,
            protein_g=item.protein_g,
            carbs_g=item.carbs_g,
            fat_g=item.fat_g,
            # Snapshot the estimator's original calories/macros at creation so a
            # later user correction (FTY-051) preserves them immutably.
            calories_estimated=item.calories,
            protein_g_estimated=item.protein_g,
            carbs_g_estimated=item.carbs_g,
            fat_g_estimated=item.fat_g,
        )
        session.add(food)
        session.flush()  # assign food.id for the evidence foreign key

        session.add(
            EvidenceSource(
                user_id=run.user_id,
                log_event_id=run.log_event_id,
                derived_food_item_id=food.id,
                product_id=item.product_id,
                source_type=item.source_type,
                source_ref=item.source_ref,
                content_hash=item.content_hash,
                fetched_at=item.fetched_at,
                calories_per_100g=item.calories_per_100g,
                protein_per_100g=item.protein_per_100g,
                carbs_per_100g=item.carbs_per_100g,
                fat_per_100g=item.fat_per_100g,
                # What the fact snapshot is expressed against: ``per_100g`` for a
                # scaled source, ``as_logged`` for a user-stated total (FTY-280).
                basis=item.basis,
                # Per-field origin map for a heterogeneous (user-stated + estimated/
                # unknown) record; ``None`` for a single-origin source.
                field_provenance=item.field_provenance,
                # Documented assumptions (e.g. the model-prior fallback reason, or a
                # per-field estimate source); a deterministic database source carries
                # none, stored as NULL.
                assumptions=list(item.assumptions) or None,
            )
        )


def _persist_resolved_labels(
    session: Session, run: EstimationRun, context: EstimationContext
) -> None:
    """Persist extracted nutrition-label items as **uncounted proposals** (FTY-196).

    Each item becomes a ``derived_food_items`` row (flushed so its id is available)
    plus a user-owned ``evidence_sources`` row recording the ``user_label`` source
    type, the image content hash, the extraction timestamp, and the immutable
    per-100g facts snapshot — **never** the raw image or raw model output. There is
    no ``product_id``: a label is user-provided evidence, not a global cache row, so
    the nullable ``product_id`` is left ``None``.

    The deterministic serving math (FTY-061) is unchanged; only the item's
    committed/counted status changes. The row is written :attr:`~app.enums.
    DerivedItemStatus.PROPOSED`, **not** ``RESOLVED``: "OCR is fallible — Slacks never
    silently trusts a fallible parse" (``docs/design-philosophy.md``). A ``proposed``
    item is excluded from every finalized-state read by construction (the
    daily-summary filter requires ``resolved``), so it does not count toward totals
    until the user confirms it (``proposed → resolved``, see
    :mod:`app.services.label_proposal`). The owning event still reaches terminal
    ``completed`` — extraction finished — the food item simply does not count while
    ``proposed``.
    """

    for item in context.resolved_label_items:
        food = DerivedFoodItem(
            log_event_id=run.log_event_id,
            user_id=run.user_id,
            name=item.name,
            quantity_text=item.quantity_text,
            unit=item.unit,
            amount=item.amount,
            status=DerivedItemStatus.PROPOSED,
            grams=item.grams,
            calories=item.calories,
            protein_g=item.protein_g,
            carbs_g=item.carbs_g,
            fat_g=item.fat_g,
            # Snapshot the estimator's original calories/macros at creation so a
            # later user correction (FTY-051) preserves them immutably.
            calories_estimated=item.calories,
            protein_g_estimated=item.protein_g,
            carbs_g_estimated=item.carbs_g,
            fat_g_estimated=item.fat_g,
        )
        session.add(food)
        session.flush()  # assign food.id for the evidence foreign key

        session.add(
            EvidenceSource(
                user_id=run.user_id,
                log_event_id=run.log_event_id,
                derived_food_item_id=food.id,
                product_id=None,
                source_type=item.source_type,
                source_ref=item.source_ref,
                content_hash=item.content_hash,
                fetched_at=item.extracted_at,
                calories_per_100g=item.calories_per_100g,
                protein_per_100g=item.protein_per_100g,
                carbs_per_100g=item.carbs_per_100g,
                fat_per_100g=item.fat_per_100g,
            )
        )


def _retain_label_image(
    session: Session,
    user_id: uuid.UUID,
    log_event_id: uuid.UUID,
    label: LabelInput,
    outcome: PipelineOutcome,
) -> None:
    """Apply discard-by-default raw-image retention after extraction (FTY-077).

    Delegates to :func:`app.services.attachments.ingest_upload`: with the user's
    default (``save = False``) no raw image is persisted; only an explicit save
    writes exactly one ``log_attachments`` row. A failed extraction (unusable /
    invalid image) never persists the image — there is nothing worth keeping and
    re-validating an invalid image would error. The saved row shares the evidence's
    content hash, so a kept image is correlatable with its extracted facts.
    """

    if not label.save or outcome is PipelineOutcome.FAILED:
        return

    current_user = session.get(User, user_id)
    if current_user is None:  # pragma: no cover - the event was loaded scoped to this user
        return
    ingest_upload(
        session,
        owner_id=user_id,
        current_user=current_user,
        log_event_id=log_event_id,
        data=label.data,
        content_type=label.content_type,
        save=True,
    )


def _persist_clarification_questions(
    session: Session, run: EstimationRun, context: EstimationContext
) -> None:
    """Persist the parse step's clarification questions, unanswered and ordered.

    A fresh clarification round **replaces** the event's unanswered question rows
    (``parse-candidates.md``): on an answer-triggered re-estimate that lands on
    ``needs_clarification`` again, the previous round's still-open questions are
    superseded by the new round's, in the same transaction as the terminal
    status. Answered questions — and their ``clarification_answers`` — are kept:
    they carry the accumulated details the next re-estimate consumes. On a first
    estimate there are no prior rows and the delete is a no-op.
    """

    answered_ids = select(ClarificationAnswer.question_id)
    session.execute(
        delete(ClarificationQuestion).where(
            ClarificationQuestion.log_event_id == run.log_event_id,
            ClarificationQuestion.id.not_in(answered_ids),
        )
    )
    for position, question in enumerate(context.clarification_questions):
        session.add(
            ClarificationQuestion(
                log_event_id=run.log_event_id,
                user_id=run.user_id,
                question_text=question.text,
                options=question.options,
                position=position,
            )
        )


def _persist_item_scoped_clarifications(
    session: Session, run: EstimationRun, context: EstimationContext
) -> None:
    """Persist each un-costable component as an ``unresolved`` row owning its question.

    The emit half of item-scoped partial resolution (FTY-329): the costable siblings are
    already persisted ``resolved`` by :func:`_persist_candidates`; here each collected
    :class:`~app.estimator.pipeline.ComponentClarification` becomes an ``unresolved``
    ``derived_food_items`` row (no calories) plus a single **item-scoped**
    ``clarification_questions`` row carrying the ``derived_food_item_id`` carrier, so the
    answer-triggered re-estimate can re-cost exactly that component. As with the
    event-level path a fresh round first replaces the event's unanswered question rows
    (answered rows and their answers are kept — they carry accumulated detail); on a
    first-pass partial there are no prior rows and the delete is a no-op. The question
    text names the component by its bounded, schema-validated parse ``name`` only — never
    raw diary text (the ``before_insert`` guard on the carrier fails closed otherwise).
    """

    answered_ids = select(ClarificationAnswer.question_id)
    session.execute(
        delete(ClarificationQuestion).where(
            ClarificationQuestion.log_event_id == run.log_event_id,
            ClarificationQuestion.id.not_in(answered_ids),
        )
    )
    for position, clarification in enumerate(context.item_scoped_clarifications):
        food = _unresolved_food_row(run, clarification.candidate)
        session.add(food)
        session.flush()  # assign food.id for the item-scoped carrier
        session.add(
            ClarificationQuestion(
                log_event_id=run.log_event_id,
                user_id=run.user_id,
                question_text=clarification.question.text,
                options=clarification.question.options,
                derived_food_item_id=food.id,
                position=position,
            )
        )


def _delete_component_open_questions(
    session: Session, log_event_id: uuid.UUID, component_id: uuid.UUID
) -> None:
    """Drop a component's still-**unanswered** item-scoped questions (FTY-329).

    Answered rows are retained — the unique ``question_id`` on
    ``clarification_answers`` is the answer-flow idempotency anchor and the row carries
    accumulated detail — so only the open questions this scoped round supersedes are
    removed. Used both when the component finally resolves (its open ask is moot) and
    when a fresh scoped round replaces it with a new question.
    """

    answered_ids = select(ClarificationAnswer.question_id)
    session.execute(
        delete(ClarificationQuestion).where(
            ClarificationQuestion.log_event_id == log_event_id,
            ClarificationQuestion.derived_food_item_id == component_id,
            ClarificationQuestion.id.not_in(answered_ids),
        )
    )


def apply_scoped_resolution(
    session: Session, run: EstimationRun, component: DerivedFoodItem, item: ResolvedFoodItem
) -> None:
    """Advance one open component to ``resolved`` **in place** (FTY-329 scoped re-estimate).

    The answered component's own row is updated — never deleted and re-inserted — so its
    id (and the ``derived_food_item_id`` carrier of its answered question) is preserved
    and the component stays represented exactly once. The row gets the re-costed
    calories/macros/grams and an original-value snapshot, plus a fresh
    ``evidence_sources`` provenance row; the already-``resolved`` siblings are never
    touched. The component's still-open questions are dropped (the ask is answered); the
    answered question row and its answer are kept.
    """

    component.status = DerivedItemStatus.RESOLVED
    component.name = item.name
    component.quantity_text = item.quantity_text
    component.unit = item.unit
    component.amount = item.amount
    component.grams = item.grams
    component.calories = item.calories
    component.protein_g = item.protein_g
    component.carbs_g = item.carbs_g
    component.fat_g = item.fat_g
    component.calories_estimated = item.calories
    component.protein_g_estimated = item.protein_g
    component.carbs_g_estimated = item.carbs_g
    component.fat_g_estimated = item.fat_g
    session.add(component)
    session.add(
        EvidenceSource(
            user_id=run.user_id,
            log_event_id=run.log_event_id,
            derived_food_item_id=component.id,
            product_id=item.product_id,
            source_type=item.source_type,
            source_ref=item.source_ref,
            content_hash=item.content_hash,
            fetched_at=item.fetched_at,
            calories_per_100g=item.calories_per_100g,
            protein_per_100g=item.protein_per_100g,
            carbs_per_100g=item.carbs_per_100g,
            fat_per_100g=item.fat_per_100g,
            basis=item.basis,
            field_provenance=item.field_provenance,
            assumptions=list(item.assumptions) or None,
        )
    )
    _delete_component_open_questions(session, run.log_event_id, component.id)


def replace_component_question(
    session: Session, run: EstimationRun, component: DerivedFoodItem, question: ClarificationDraft
) -> None:
    """Keep a component ``unresolved`` and swap its open ask for a fresh one (FTY-329).

    When a scoped re-estimate still cannot cost the answered component, the component
    stays ``unresolved`` and its still-open questions are replaced by ``question`` (the
    accumulated answered rows are retained). ``position`` is placed after any retained
    rows so ordering stays stable.
    """

    _delete_component_open_questions(session, run.log_event_id, component.id)
    next_position = (
        session.scalar(
            select(func.max(ClarificationQuestion.position)).where(
                ClarificationQuestion.log_event_id == run.log_event_id
            )
        )
        or 0
    )
    session.add(
        ClarificationQuestion(
            log_event_id=run.log_event_id,
            user_id=run.user_id,
            question_text=question.text,
            options=question.options,
            derived_food_item_id=component.id,
            position=next_position + 1,
        )
    )
