"""Idempotent, retry-aware estimation worker core (FTY-040).

:func:`process_estimation` is the single attempt the Celery task (and tests) call
to drive one log event through the estimation pipeline. It is deliberately a
plain function over a :class:`~sqlalchemy.orm.Session` so it can be exercised
against SQLite in tests without a live broker, mirroring the service pattern used
elsewhere in the backend.

Contracts implemented here:

- **Idempotency.** Exactly one :class:`~app.models.estimation.EstimationJob`
  exists per log event (unique ``log_event_id``). A job already in a terminal
  status is never reprocessed, so re-delivering the same task is a no-op that
  writes nothing. The event is claimed (``pending → processing``) only when it is
  still ``pending``.
- **Ownership.** The event is loaded scoped to the job's ``user_id``; a mismatch
  (or missing event) fails closed with :class:`EstimationEventNotFound` rather
  than processing another user's data.
- **Bounded retries.** Each attempt increments ``attempts``. A retryable failure
  with attempts remaining leaves the job ``running`` and asks the caller to
  retry; once ``attempts`` reaches ``max_attempts`` the job and event become
  ``failed``. ``needs_clarification`` is terminal and never retried.

Every run records sanitized metadata only — no raw prompts, secrets, or raw user
text (security baseline + ``docs/security/data-retention.md``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import (
    TERMINAL_JOB_STATUSES,
    DerivedItemStatus,
    EstimationJobStatus,
    EstimationRunStatus,
    LogEventStatus,
)
from app.estimator.fdc import build_fdc_client
from app.estimator.food_step import BarcodeResolver, FoodResolver
from app.estimator.label_step import LabelInput
from app.estimator.off import build_off_client
from app.estimator.official_fetch import load_official_fetch_settings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    Pipeline,
    PipelineOutcome,
    PipelineResult,
    default_pipeline,
    label_pipeline,
)
from app.estimator.reference_fetch import load_reference_fetch_settings
from app.estimator.search import build_search_provider
from app.llm import build_provider, load_llm_settings
from app.models.derived import (
    ClarificationQuestion,
    DerivedExerciseItem,
    DerivedFoodItem,
)
from app.models.estimation import EstimationJob, EstimationRun
from app.models.food_sources import EvidenceSource
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services.attachments import ingest_upload
from app.services.log_events import transition_event

#: Maximum number of estimation attempts before the job is marked ``failed``.
#: Conservative default (one initial try plus two retries); tunable per the
#: story's planning notes.
DEFAULT_MAX_ATTEMPTS = 3

#: Exponential-backoff base, in seconds, between retries.
RETRY_BACKOFF_BASE_SECONDS = 10

#: Cap on a single retry delay so backoff cannot grow unbounded.
RETRY_BACKOFF_MAX_SECONDS = 600


class EstimationEventNotFound(Exception):
    """Raised when the job's log event does not exist for the owning user.

    A missing or cross-user event is a fail-closed condition: the worker must not
    process data it cannot prove the job owns.
    """


def retry_countdown(retries_so_far: int) -> int:
    """Return the backoff delay (seconds) before the next retry.

    Exponential on the number of retries already performed, capped at
    :data:`RETRY_BACKOFF_MAX_SECONDS`: 10s, 20s, 40s, ….
    """

    # ``1 << n`` is 2**n as a plain int (avoids mypy's Any-typed int.__pow__).
    delay = RETRY_BACKOFF_BASE_SECONDS * (1 << max(retries_so_far, 0))
    return min(delay, RETRY_BACKOFF_MAX_SECONDS)


@dataclass(frozen=True)
class ProcessResult:
    """The outcome of one :func:`process_estimation` attempt.

    ``should_retry`` is ``True`` only when this attempt failed transiently and
    attempts remain; the caller (the Celery task) is responsible for scheduling
    the retry. ``run_id`` is ``None`` for an idempotent no-op (terminal job).
    """

    job_status: EstimationJobStatus
    event_status: LogEventStatus | None
    run_id: uuid.UUID | None
    attempts: int
    should_retry: bool


def _get_or_create_job(
    session: Session, log_event_id: uuid.UUID, user_id: uuid.UUID, max_attempts: int
) -> EstimationJob:
    """Return the event's job, creating a ``queued`` one if absent.

    The unique ``log_event_id`` makes this safe under concurrent delivery: if a
    racing worker inserts first, the ``IntegrityError`` is caught and the existing
    row is loaded instead, so there is still exactly one job per event.
    """

    job = session.scalars(
        select(EstimationJob).where(EstimationJob.log_event_id == log_event_id)
    ).one_or_none()
    if job is not None:
        return job

    job = EstimationJob(
        log_event_id=log_event_id,
        user_id=user_id,
        status=EstimationJobStatus.QUEUED,
        attempts=0,
        max_attempts=max_attempts,
        idempotency_key=str(log_event_id),
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        job = session.scalars(
            select(EstimationJob).where(EstimationJob.log_event_id == log_event_id)
        ).one()
    else:
        session.refresh(job)
    return job


def _load_owned_event(session: Session, log_event_id: uuid.UUID, user_id: uuid.UUID) -> LogEvent:
    """Load the event scoped to ``user_id``; fail closed if absent or cross-user."""

    event = session.scalars(
        select(LogEvent).where(LogEvent.id == log_event_id, LogEvent.user_id == user_id)
    ).one_or_none()
    if event is None:
        raise EstimationEventNotFound("log event not found for job owner")
    return event


def _load_user_weight_kg(session: Session, user_id: uuid.UUID) -> float | None:
    """Return the user's canonical body weight (kg), or ``None`` if not yet set.

    The exercise calculator (FTY-043) needs the user's own weight; it is read from
    the owning user's profile, never supplied by the model. A missing profile or
    weight returns ``None`` and the calculator fails closed.
    """

    return session.scalars(
        select(UserProfile.weight_kg).where(UserProfile.user_id == user_id)
    ).one_or_none()


def process_estimation(
    session: Session,
    *,
    log_event_id: uuid.UUID,
    user_id: uuid.UUID,
    pipeline: Pipeline | None = None,
    label_upload: LabelInput | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> ProcessResult:
    """Run one estimation attempt for ``log_event_id``, idempotently.

    Returns a :class:`ProcessResult`. The caller schedules a retry iff
    ``should_retry`` is set. Raises :class:`EstimationEventNotFound` when the
    event is missing or not owned by ``user_id``.

    ``label_upload`` carries a user-provided nutrition-label image (FTY-061): when
    present, the default pipeline is the label-extraction pipeline (the image is
    read by the v2 vision provider rather than the text parsed), and after
    extraction the raw image is retained only on an explicit save (FTY-077),
    discarded by default.
    """

    if pipeline is None:
        provider = build_provider(load_llm_settings())
        if label_upload is not None:
            # A label event has an image, not NL text: extract it deterministically
            # rather than running the text parse pipeline.
            pipeline = label_pipeline(provider)
        else:
            # The food step (FTY-044/060) needs this session for the product cache and
            # evidence writes, so the default pipeline is built per call here where the
            # session is in scope. A barcode candidate prefers the Open Food Facts source
            # (enabled by default); a generic food uses USDA FDC (disabled without a key,
            # leaving the candidate unresolved). The official-source step (FTY-062/166)
            # runs last for the candidates the food step deferred: it searches (FTY-079)
            # and fetches official pages (FTY-078), then public reference pages
            # (FTY-166), else falls through to a model-prior estimate. Building the
            # clients/adapters makes no network call.
            resolver = FoodResolver(session=session, source=build_fdc_client())
            barcode_resolver = BarcodeResolver(session=session, source=build_off_client())
            official_step = OfficialSourceResolveStep(
                provider=provider,
                search_provider=build_search_provider(),
                fetch_settings=load_official_fetch_settings(),
                reference_fetch_settings=load_reference_fetch_settings(),
            )
            pipeline = default_pipeline(
                provider,
                food_resolver=resolver,
                barcode_resolver=barcode_resolver,
                official_step=official_step,
            )

    # Enforce ownership before any write: a missing or cross-user event fails
    # closed and no job row is created on its behalf.
    event = _load_owned_event(session, log_event_id, user_id)

    job = _get_or_create_job(session, log_event_id, user_id, max_attempts)

    # Idempotent no-op: a terminal job is fully resolved, so a re-delivered task
    # writes nothing and re-advances nothing.
    if EstimationJobStatus(job.status) in TERMINAL_JOB_STATUSES:
        return ProcessResult(
            job_status=EstimationJobStatus(job.status),
            event_status=LogEventStatus(event.status),
            run_id=None,
            attempts=job.attempts,
            should_retry=False,
        )

    # Claim the event. Only a pending event is claimed; a re-entry mid-retry finds
    # it already ``processing`` and leaves it. Any other (terminal) state is an
    # inconsistency we treat as an idempotent no-op rather than forcing a
    # transition the state machine forbids.
    current = LogEventStatus(event.status)
    if current is LogEventStatus.PENDING:
        transition_event(session, event, LogEventStatus.PROCESSING)
    elif current is not LogEventStatus.PROCESSING:
        return ProcessResult(
            job_status=EstimationJobStatus(job.status),
            event_status=current,
            run_id=None,
            attempts=job.attempts,
            should_retry=False,
        )

    job.attempts += 1
    job.status = EstimationJobStatus.RUNNING
    session.add(job)
    session.commit()

    run = EstimationRun(
        job_id=job.id,
        log_event_id=log_event_id,
        user_id=user_id,
        attempt=job.attempts,
        status=EstimationRunStatus.RUNNING,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    context = EstimationContext(
        log_event_id=log_event_id,
        user_id=user_id,
        raw_text=event.raw_text,
        weight_kg=_load_user_weight_kg(session, user_id),
        label_input=label_upload,
    )
    result = _run_pipeline(pipeline, context)

    # Persist the sanitized run metadata regardless of outcome.
    run.provider = context.provider
    run.model = context.model
    run.schema_version = context.schema_version
    run.tool_names = list(context.tool_names)
    run.source_refs = list(context.source_refs)
    run.assumptions = list(context.assumptions)
    run.validation_errors = list(context.validation_errors)
    run.trace = list(context.trace)

    process_result = _finalize(session, job, event, run, result, context)

    if label_upload is not None:
        _retain_label_image(session, user_id, log_event_id, label_upload, result.outcome)

    return process_result


def _run_pipeline(pipeline: Pipeline, context: EstimationContext) -> PipelineResult:
    """Run the pipeline, converting an unexpected exception into a failed result.

    Typed step signals are handled inside :meth:`Pipeline.run`; this catch-all is
    a safety net so a bug in a step is recorded as a *retryable* failure (with only
    the exception *type* name, never its message, to avoid leaking user text)
    rather than crashing the worker.
    """

    try:
        return pipeline.run(context)
    except Exception as exc:  # noqa: BLE001 (defensive worker boundary)
        return PipelineResult(
            PipelineOutcome.FAILED,
            f"unexpected step error: {type(exc).__name__}",
            retryable=True,
        )


def _finalize(
    session: Session,
    job: EstimationJob,
    event: LogEvent,
    run: EstimationRun,
    result: PipelineResult,
    context: EstimationContext,
) -> ProcessResult:
    """Apply the pipeline outcome to the run, job, and event, and commit.

    On a successful or needs-clarification outcome the parse step's structured
    products (candidates / questions accumulated on ``context``) are persisted in
    the same transaction as the terminal status. A failed outcome persists no
    derived data — the step failed closed.
    """

    outcome = result.outcome

    if outcome is PipelineOutcome.COMPLETED:
        _persist_candidates(session, run, context)
        run.status = EstimationRunStatus.COMPLETED
        job.status = EstimationJobStatus.SUCCEEDED
        session.add_all([run, job])
        session.commit()
        transition_event(session, event, LogEventStatus.COMPLETED)
        return _result(job, event, run, should_retry=False)

    if outcome is PipelineOutcome.NEEDS_CLARIFICATION:
        _persist_clarification_questions(session, run, context)
        run.status = EstimationRunStatus.NEEDS_CLARIFICATION
        job.status = EstimationJobStatus.NEEDS_CLARIFICATION
        session.add_all([run, job])
        session.commit()
        transition_event(session, event, LogEventStatus.NEEDS_CLARIFICATION)
        return _result(job, event, run, should_retry=False)

    # Failed. A deterministic (non-retryable) failure or an exhausted retry bound
    # is terminal; otherwise the worker reports a retry is due.
    run.status = EstimationRunStatus.FAILED
    run.error = result.error
    terminal = not result.retryable or job.attempts >= job.max_attempts
    if terminal:
        job.status = EstimationJobStatus.FAILED
        session.add_all([run, job])
        session.commit()
        transition_event(session, event, LogEventStatus.FAILED)
        return _result(job, event, run, should_retry=False)

    # Retries remain: keep the job ``running`` and the event ``processing``.
    job.status = EstimationJobStatus.RUNNING
    session.add_all([run, job])
    session.commit()
    return _result(job, event, run, should_retry=True)


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
    if context.resolved_food_items or leftover:
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
                # Documented assumptions (e.g. the model-prior fallback reason); a
                # deterministic database source carries none, stored as NULL.
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
    DerivedItemStatus.PROPOSED`, **not** ``RESOLVED``: "OCR is fallible — Fatty never
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
    """Persist the parse step's clarification questions, unanswered and ordered."""

    for position, question in enumerate(context.clarification_questions):
        session.add(
            ClarificationQuestion(
                log_event_id=run.log_event_id,
                user_id=run.user_id,
                question_text=question,
                position=position,
            )
        )


def _result(
    job: EstimationJob, event: LogEvent, run: EstimationRun, *, should_retry: bool
) -> ProcessResult:
    """Build a :class:`ProcessResult` snapshot from the post-commit state."""

    return ProcessResult(
        job_status=EstimationJobStatus(job.status),
        event_status=LogEventStatus(event.status),
        run_id=run.id,
        attempts=job.attempts,
        should_retry=should_retry,
    )
