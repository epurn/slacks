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
  still ``pending``; an event already ``processing`` with a non-terminal job is
  processed as-is — the path an answer-triggered re-estimate takes (FTY-171: the
  clarification resolve re-opens the terminal ``needs_clarification`` job and
  drives ``needs_clarification → processing`` *before* enqueueing, so the worker
  itself never re-opens a terminal job and redelivery idempotency is preserved).
- **Ownership.** The event is loaded scoped to the job's ``user_id``; a mismatch
  (or missing event) fails closed with :class:`EstimationEventNotFound` rather
  than processing another user's data.
- **Bounded retries + never-fail infra semantics (FTY-372).** Each attempt
  increments ``attempts``. A retryable failure with attempts remaining leaves the
  job ``running`` and asks the caller to retry. An *infrastructure* failure — a
  per-run ceiling breach (FTY-363) or a transient failure that exhausted the
  attempt bound — never lands terminal ``failed``: with ≥1 interpreted candidate
  the worker commits a rough, budget-free estimate and lands ``completed``; with
  nothing interpreted the event stays ``processing`` (honest still-working) with a
  bounded, long-backoff auto-retry. Terminal ``failed`` is reserved for
  deterministic non-food/empty input (``empty_input`` / the narrowed
  ``unparseable_input``) and the fail-closed validation gates.
  ``needs_clarification`` is terminal and never retried.
- **Image-bearing events (FTY-376).** At claim time the worker loads the event's
  image attachments by event id (``event_images.py`` — the ids-only payload never
  carries image data) and attaches them to the context as vision evidence when
  the configured model is vision-capable. When the event reaches an
  **event-terminal** status (``completed``/``failed``) its transient, unsaved
  images are hard-deleted in the same transaction as the terminal status write;
  the worker-terminal clarification outcomes retain them for the answer-triggered
  re-estimate (``log-attachments.md`` v3, ``estimation-jobs.md`` v6).

Every run records sanitized metadata only — no raw prompts, secrets, raw user
text, or image bytes/paths/hashes (security baseline +
``docs/security/data-retention.md``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

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
from app.estimator.decision_trace import MAX_TRACE_ENTRIES
from app.estimator.degrade import PROVIDER_TRANSIENT_EXHAUSTED, DegradeProducer
from app.estimator.event_images import EventImageLoad, load_event_images
from app.estimator.label_step import LabelInput
from app.estimator.persist import (
    _persist_candidates,
    _persist_clarification_questions,
    _persist_item_scoped_clarifications,
    _retain_label_image,
    apply_scoped_resolution,
    replace_component_question,
)
from app.estimator.pipeline import (
    AnsweredClarification,
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    Pipeline,
    PipelineOutcome,
    PipelineResult,
)
from app.estimator.run_budget import is_run_budget_breach
from app.estimator.worker_pipeline import build_worker_pipeline
from app.models.derived import (
    ClarificationAnswer,
    ClarificationQuestion,
    DerivedFoodItem,
)
from app.models.estimation import EstimationJob, EstimationRun
from app.models.identity import UserProfile
from app.models.log_events import LogEvent
from app.services.attachments import purge_transient_for_event
from app.services.log_events import transition_event

#: Maximum number of estimation attempts before the job is marked ``failed``.
#: Conservative default (one initial try plus two retries); tunable per the
#: story's planning notes. The distinct *per-run* provider-call / wall-clock
#: ceiling (a run-scoped bound on total sequential provider work *within* one
#: attempt, separate from this attempt-level retry bound) lives in
#: ``run_budget.py`` — ``DEFAULT_MAX_PROVIDER_CALLS`` / ``DEFAULT_RUN_DEADLINE_SECONDS``
#: (FTY-363), applied by wrapping the built provider in :class:`BudgetedProvider`.
DEFAULT_MAX_ATTEMPTS = 3

#: Exponential-backoff base, in seconds, between retries.
RETRY_BACKOFF_BASE_SECONDS = 10

#: Cap on a single retry delay so backoff cannot grow unbounded.
RETRY_BACKOFF_MAX_SECONDS = 600

#: Extended attempt ceiling for the honest **still-working / will-retry** state (FTY-372).
#: When an *infrastructure* failure — a per-run ceiling breach (FTY-363) or a transient
#: failure that exhausted the attempt-level bound above — leaves the run with **nothing
#: interpreted**, the event stays ``processing`` (never terminal ``failed``) and the job
#: is re-queued with a bounded, long-backoff auto-retry up to this ceiling. It is generous
#: enough to ride out a temporary provider/infra outage yet **bounded**, so a
#: permanently-broken provider cannot drive unbounded re-enqueues (the security-baseline
#: runaway/DoS guard). Beyond it the event **stays** in this deferred still-working state —
#: the user's existing manual retry re-opens it — and still never becomes ``failed``. A
#: documented tunable, like :data:`DEFAULT_MAX_ATTEMPTS`.
DEFAULT_MAX_INFRA_RETRY_ATTEMPTS = 8

#: Long-backoff base (seconds) between still-working infra re-queues — far longer than the
#: transient :data:`RETRY_BACKOFF_BASE_SECONDS`: a pure-infra breach will not clear in
#: seconds, so the still-working retry waits minutes between attempts.
INFRA_RETRY_BACKOFF_BASE_SECONDS = 300

#: Cap on a single still-working retry delay (one hour) so the long backoff stays bounded.
INFRA_RETRY_BACKOFF_MAX_SECONDS = 3600


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


def infra_retry_countdown(retries_so_far: int) -> int:
    """Return the long backoff (seconds) before the next still-working infra retry.

    Exponential on the number of retries already performed, from
    :data:`INFRA_RETRY_BACKOFF_BASE_SECONDS` and capped at
    :data:`INFRA_RETRY_BACKOFF_MAX_SECONDS`: 5m, 10m, 20m, …, ≤ 1h. Deliberately far
    slower than :func:`retry_countdown` — a pure-infrastructure breach will not clear in
    seconds, so the still-working retry paces itself over minutes (FTY-372).
    """

    delay = INFRA_RETRY_BACKOFF_BASE_SECONDS * (1 << max(retries_so_far, 0))
    return min(delay, INFRA_RETRY_BACKOFF_MAX_SECONDS)


@dataclass(frozen=True)
class ProcessResult:
    """The outcome of one :func:`process_estimation` attempt.

    ``should_retry`` is ``True`` only when this attempt failed transiently and
    attempts remain, or when an infra failure with nothing interpreted left the event
    in the honest still-working state (FTY-372); the caller (the Celery task) is
    responsible for scheduling the retry. ``run_id`` is ``None`` for an idempotent no-op
    (terminal job). ``retry_countdown_seconds`` is the worker-computed backoff to use
    before the next retry: it is set to the long infra backoff for a still-working
    re-queue and left ``None`` for a standard transient retry (the caller then uses its
    own :func:`retry_countdown` schedule), and is always ``None`` when ``should_retry`` is
    ``False``.

    ``transient_exhausted`` is set only on the **synchronous label** path (FTY-390):
    a transient (retryable) vision-provider failure that ran out of the in-request
    attempt budget did **not** land terminal ``failed`` — the event is left
    non-terminal and this flag tells the in-request caller to roll back and return a
    retryable ``503`` with nothing persisted (``label-upload.md``). It is always
    ``False`` for the asynchronous worker, whose transient exhaustion is routed by the
    FTY-372 never-fail degrade/still-working split instead.
    """

    job_status: EstimationJobStatus
    event_status: LogEventStatus | None
    run_id: uuid.UUID | None
    attempts: int
    should_retry: bool
    retry_countdown_seconds: int | None = None
    transient_exhausted: bool = False


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


def _load_answered_clarifications(
    session: Session, log_event_id: uuid.UUID
) -> list[AnsweredClarification]:
    """Return the event's answered (question, answer) pairs, oldest question first.

    The clarification answer flow (FTY-171) accumulates one
    ``clarification_answers`` row per resolved question; a re-estimate consumes
    **every** detail answered so far as structured input alongside the unchanged
    raw text. Empty on a first estimate. The pairs are untrusted user text and
    must never be copied into the sanitized run ``trace``/``error``.
    """

    rows = session.execute(
        select(ClarificationQuestion.question_text, ClarificationAnswer.answer_text)
        .join(ClarificationAnswer, ClarificationAnswer.question_id == ClarificationQuestion.id)
        .where(ClarificationAnswer.log_event_id == log_event_id)
        .order_by(ClarificationAnswer.created_at.asc(), ClarificationQuestion.position.asc())
    ).all()
    return [
        AnsweredClarification(question_text=question, answer_text=answer)
        for question, answer in rows
    ]


def _record_run_metadata(run: EstimationRun, context: EstimationContext) -> None:
    """Copy the sanitized run metadata the pipeline accumulated onto the run row."""

    run.provider = context.provider
    run.model = context.model
    run.schema_version = context.schema_version
    run.tool_names = list(context.tool_names)
    run.source_refs = list(context.source_refs)
    run.assumptions = list(context.assumptions)
    run.validation_errors = list(context.validation_errors)
    run.trace = list(context.trace)


def _apply_event_name(event: LogEvent, context: EstimationContext) -> None:
    """Persist the model-generated meal name onto the event (FTY-422).

    Written on a terminal completing transition (``completed`` / ``partially_resolved``),
    atomically with the derived items through the single ``transition_event`` commit — the
    same terminal write that persists the items. Only a **non-null** name is written, so an
    exercise-only/empty event keeps ``name`` ``null`` and an answer-triggered re-estimate
    never clobbers an earlier round's good name with a null. The value was already
    sanitized/bounded at the parse trust boundary (``sanitize_event_name``).
    """

    if context.event_name:
        event.name = context.event_name


def _load_event_food_items(session: Session, log_event_id: uuid.UUID) -> list[DerivedFoodItem]:
    """Return every ``derived_food_items`` row already committed for the event.

    Non-empty only on an answer-triggered re-estimate of a previously-committed
    (``partially_resolved``) event — a first pass and an event-level
    ``needs_clarification`` re-estimate persist no food rows — so its presence is the
    scoped-re-estimate discriminator.
    """

    return list(
        session.scalars(
            select(DerivedFoodItem)
            .where(DerivedFoodItem.log_event_id == log_event_id)
            .order_by(DerivedFoodItem.created_at.asc(), DerivedFoodItem.id.asc())
        )
    )


def _load_answered_open_components(
    session: Session, log_event_id: uuid.UUID, prior_food: list[DerivedFoodItem]
) -> list[tuple[DerivedFoodItem, list[AnsweredClarification]]]:
    """Return each still-``unresolved`` component that has ≥1 answered question.

    Groups the event's answered (question, answer) pairs by the item-scoped
    ``derived_food_item_id`` carrier and pairs each with its still-``unresolved``
    component row, oldest answer first. A component whose question is not yet answered —
    or that already resolved — is excluded, so a scoped re-estimate re-costs exactly the
    open, newly-answered components and leaves every sibling untouched. The pairs are
    untrusted user text, never copied into the run ``trace``/``error``.
    """

    unresolved_by_id = {
        item.id: item for item in prior_food if item.status == DerivedItemStatus.UNRESOLVED
    }
    if not unresolved_by_id:
        return []
    rows = session.execute(
        select(
            ClarificationQuestion.derived_food_item_id,
            ClarificationQuestion.question_text,
            ClarificationAnswer.answer_text,
        )
        .join(ClarificationAnswer, ClarificationAnswer.question_id == ClarificationQuestion.id)
        .where(
            ClarificationQuestion.log_event_id == log_event_id,
            ClarificationQuestion.derived_food_item_id.in_(unresolved_by_id.keys()),
        )
        .order_by(ClarificationAnswer.created_at.asc(), ClarificationQuestion.position.asc())
    ).all()
    answers_by_component: dict[uuid.UUID, list[AnsweredClarification]] = {}
    for component_id, question_text, answer_text in rows:
        answers_by_component.setdefault(component_id, []).append(
            AnsweredClarification(question_text=question_text, answer_text=answer_text)
        )
    return [
        (unresolved_by_id[component_id], answers)
        for component_id, answers in answers_by_component.items()
    ]


def _has_open_item_scoped_question(session: Session, log_event_id: uuid.UUID) -> bool:
    """Whether any still-``unresolved`` component still owns an item-scoped question.

    Mirrors the daily-summary / read-model finalized gate
    (:func:`app.services.daily_summary._has_open_item_scoped_question`): while one holds,
    the event stays ``partially_resolved``; once every component with a question has
    resolved, the event reaches ``completed``.
    """

    return (
        session.scalars(
            select(ClarificationQuestion.id)
            .join(DerivedFoodItem, DerivedFoodItem.id == ClarificationQuestion.derived_food_item_id)
            .where(
                ClarificationQuestion.log_event_id == log_event_id,
                DerivedFoodItem.status == DerivedItemStatus.UNRESOLVED,
            )
            .limit(1)
        ).first()
        is not None
    )


def _scoped_failure_question(component: DerivedFoodItem) -> ClarificationDraft:
    """A fresh, answerable item-scoped ask for a scoped re-estimate that failed closed.

    A deterministic (or retry-exhausted) scoped failure must not leave the component's
    only question already answered — that is an inert ``partially_resolved`` state the
    user cannot act on. This re-opens an answerable ask naming the component by its
    bounded, schema-validated parse ``name`` (already the ``derived_food_items.name`` the
    user sees, never raw diary text — the carrier's ``before_insert`` guard fails closed
    otherwise), so a new answer can drive a fresh scoped re-estimate.
    """

    name = component.name.strip() or "that item"
    return ClarificationDraft(
        text=f'We couldn\'t work out "{name}" from that answer. Which food was it, and how much?'
    )


def _component_candidate(component: DerivedFoodItem) -> CandidateDraft:
    """Rebuild the parsed candidate shape from an open component's own row (FTY-372).

    A scoped re-estimate degrade re-costs the answered component from its bounded,
    schema-validated parse fields (already the ``derived_food_items`` columns the user
    sees, never raw diary text), so the budget-free degrade producer can produce a rough
    estimate for exactly that component without re-parsing the whole entry.
    """

    return CandidateDraft(
        name=component.name,
        quantity_text=component.quantity_text or "",
        unit=component.unit,
        amount=component.amount,
    )


def _apply_scoped_component_outcome(
    session: Session,
    run: EstimationRun,
    component: DerivedFoodItem,
    context: EstimationContext,
    result: PipelineResult,
) -> None:
    """Fold one open component's scoped pipeline outcome back onto its own row.

    Resolved → advance the row in place to ``resolved`` with the newly-costed values +
    evidence (:func:`apply_scoped_resolution`). Still un-costable → keep the row
    ``unresolved`` and replace its open ask with the fresh component-named question
    (:func:`replace_component_question`). A deterministic (or retry-exhausted) failure is
    *not* left inert: the answered question is replaced with a fresh answerable ask and
    the failure is recorded in the sanitized trace, so the event never becomes a
    ``partially_resolved`` dead end with no answerable question. Each branch emits the
    ``scoped_reestimate`` per-component trace vocabulary (FTY-329).
    """

    if context.resolved_food_items:
        apply_scoped_resolution(session, run, component, context.resolved_food_items[0])
        context.record_decision(
            "scoped_reestimate",
            "outcome",
            outcome="component_resolved",
            source_ref=context.resolved_food_items[0].source_ref,
        )
    elif context.item_scoped_clarifications:
        replace_component_question(
            session, run, component, context.item_scoped_clarifications[0].question
        )
        context.record_decision("scoped_reestimate", "outcome", outcome="component_clarified")
    elif result.outcome is PipelineOutcome.NEEDS_CLARIFICATION and context.clarification_questions:
        # A parse-level safety gate (e.g. implausible re-read) asked whole-event; keep
        # the component open with that question re-scoped to its carrier.
        fresh = ClarificationDraft(text=context.clarification_questions[0].text)
        replace_component_question(session, run, component, fresh)
        context.record_decision("scoped_reestimate", "outcome", outcome="component_clarified")
    else:
        # Any terminal scoped outcome that did **not** resolve the component and did not
        # re-open a scoped question above — a deterministic :class:`StepFailed` (or a
        # retry-exhausted failure; the retry-with-attempts-left and run-budget-breach cases
        # are handled by the caller), or a rare re-estimate that costed nothing — must not
        # be left untouched: the component's only question is now answered and the read
        # filters it out, so re-open an answerable ask instead of an inert partial.
        outcome = (
            "component_reestimate_failed"
            if result.outcome is PipelineOutcome.FAILED
            else "component_reestimate_unresolved"
        )
        replace_component_question(session, run, component, _scoped_failure_question(component))
        context.record_decision("scoped_reestimate", "outcome", outcome=outcome)


def _finalize_scoped_reestimate(
    session: Session,
    pipeline: Pipeline,
    job: EstimationJob,
    event: LogEvent,
    run: EstimationRun,
    prior_food: list[DerivedFoodItem],
    *,
    user_id: uuid.UUID,
    images: EventImageLoad,
    degrade_producer: DegradeProducer | None = None,
) -> ProcessResult:
    """Re-cost only the answered open component(s), preserving every resolved sibling.

    Each open component is re-interpreted from its own sanitized identity plus its
    answered clarifications — never the whole raw entry — so the model makes **no**
    provider call about a sibling. The costable siblings stay their original committed
    ``resolved`` rows; the answered component's row is advanced in place. The event lands
    ``completed`` once no ``unresolved`` component still owns an item-scoped question, and
    otherwise stays ``partially_resolved`` (a still-open component keeps a fresh
    item-scoped question). Persistence + the terminal status transition commit atomically
    in the single :func:`transition_event` commit, exactly like :func:`_finalize`.
    """

    open_components = _load_answered_open_components(session, event.id, prior_food)
    weight_kg = _load_user_weight_kg(session, user_id)
    contexts: list[EstimationContext] = []
    for component, answered in open_components:
        context = EstimationContext(
            log_event_id=event.id,
            user_id=user_id,
            # The scoped identity only — the committed sibling names never re-enter
            # interpretation, so no provider call is made about them.
            raw_text=component.name,
            weight_kg=weight_kg,
            answered_clarifications=answered,
            # The event's still-retained image evidence rides the scoped round
            # too (``estimation-jobs.md`` v6: a clarify loop never loses it).
            images=images.images,
            image_evidence_degraded_reason=images.degraded_reason,
        )
        result = _run_pipeline(pipeline, context)
        if result.outcome is PipelineOutcome.FAILED and is_run_budget_breach(result.error):
            # FTY-372 never-fail: a per-run ceiling breach (FTY-363) must not fail the whole
            # event. Degrade **this** answered component to a rough, budget-free estimate in
            # place (no additional provider call); every already-``resolved`` sibling — never
            # re-costed here — stays preserved and is never double-counted. We do **not** roll
            # back: earlier components applied in this loop are kept, and the component row is
            # advanced directly, so partial in-flight context state from the breached run does
            # not reach persistence.
            degraded = (degrade_producer or _default_degrade_producer()).degrade_food_candidate(
                context,
                _component_candidate(component),
                reason=_degrade_reason(result.error),
                index=None,
                budget_free=True,
            )
            apply_scoped_resolution(session, run, component, degraded)
            context.record_decision("scoped_reestimate", "outcome", outcome="component_degraded")
            contexts.append(context)
            continue
        if (
            result.outcome is PipelineOutcome.FAILED
            and result.retryable
            and job.attempts < job.max_attempts
        ):
            # A transient failure with retries left: discard any in-place applications from
            # this round and ask the caller to retry the whole scoped re-estimate, exactly as
            # the full path retries a :class:`StepError`. Re-answering the (already-recorded)
            # question is a no-op, so without this the event would stick ``partially_resolved``.
            session.rollback()
            job.status = EstimationJobStatus.RUNNING
            run.status = EstimationRunStatus.FAILED
            run.error = result.error
            session.add_all([run, job])
            session.commit()
            return _result(job, event, run, should_retry=True)
        _apply_scoped_component_outcome(session, run, component, context, result)
        contexts.append(context)

    if contexts:
        _record_run_metadata(run, contexts[-1])
        # ``_record_run_metadata`` copies only the last context's trace; concatenate every
        # scoped component's sanitized trace so a ``component_clarified`` /
        # ``component_reestimate_failed`` outcome on a non-last component is still recorded.
        merged: list[dict[str, Any]] = []
        for scoped in contexts:
            merged.extend(scoped.trace)
        run.trace = merged[:MAX_TRACE_ENTRIES]

    # The session runs ``autoflush=False``, so flush the in-place component status
    # updates before the completion query reads them — otherwise it sees the stale
    # ``unresolved`` rows and never completes.
    session.flush()
    if _has_open_item_scoped_question(session, event.id):
        run.status = EstimationRunStatus.NEEDS_CLARIFICATION
        job.status = EstimationJobStatus.NEEDS_CLARIFICATION
        session.add_all([run, job])
        transition_event(session, event, LogEventStatus.PARTIALLY_RESOLVED)
        return _result(job, event, run, should_retry=False)

    run.status = EstimationRunStatus.COMPLETED
    job.status = EstimationJobStatus.SUCCEEDED
    session.add_all([run, job])
    # Event-terminal: the clarify loop is over, so the retained transient images
    # are purged atomically with the completion (``log-attachments.md`` v3).
    purge_transient_for_event(session, event.id)
    transition_event(session, event, LogEventStatus.COMPLETED)
    return _result(job, event, run, should_retry=False)


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
    degrade_producer: DegradeProducer | None = None,
    synchronous_label: bool = False,
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

    ``synchronous_label`` marks the in-request label-upload seam (FTY-390): a
    transient (retryable) provider failure that exhausts ``max_attempts`` is **not**
    committed as terminal ``failed`` but surfaced via
    :attr:`ProcessResult.transient_exhausted`, so the route rolls back and returns a
    retryable ``503``. It is ``False`` (and irrelevant) for the asynchronous worker.
    """

    if pipeline is None:
        # Pipeline selection + construction (extracted to ``worker_pipeline.py``):
        # a label event runs ``label_pipeline``; everything else — image-bearing
        # unified submissions included (FTY-376) — runs ``default_pipeline``.
        pipeline = build_worker_pipeline(session, label_upload)

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

    # Image-bearing events (FTY-376): load the event's image attachments by id —
    # the ids-only job payload never carries image data; the database is the only
    # channel from create to worker — gated on vision capability. Transient rows
    # are retained across the clarify loop (``log-attachments.md`` v3), so an
    # answer-triggered re-estimate reloads them here identically.
    image_load = (
        load_event_images(session, log_event_id, user_id)
        if label_upload is None
        else EventImageLoad()
    )

    # FTY-329 scoped re-estimate: a previously-``partially_resolved`` event carries
    # committed food items from an earlier round, so this re-estimate re-costs **only**
    # the open, newly-answered component(s) and leaves the already-``resolved`` siblings
    # untouched — never re-parsing the whole entry, so no sibling is re-costed,
    # duplicated, or double-counted. A first pass and an event-level
    # ``needs_clarification`` re-estimate carry no prior food items and run the full
    # pipeline unchanged; a label re-estimate is out of scope.
    prior_food = _load_event_food_items(session, log_event_id)
    if label_upload is None and prior_food:
        return _finalize_scoped_reestimate(
            session,
            pipeline,
            job,
            event,
            run,
            prior_food,
            user_id=user_id,
            images=image_load,
            degrade_producer=degrade_producer,
        )

    context = EstimationContext(
        log_event_id=log_event_id,
        user_id=user_id,
        raw_text=event.raw_text,
        weight_kg=_load_user_weight_kg(session, user_id),
        label_input=label_upload,
        answered_clarifications=_load_answered_clarifications(session, log_event_id),
        images=image_load.images,
        image_evidence_degraded_reason=image_load.degraded_reason,
    )
    result = _run_pipeline(pipeline, context)

    # Persist the sanitized run metadata regardless of outcome.
    _record_run_metadata(run, context)

    process_result = _finalize(
        session,
        job,
        event,
        run,
        result,
        context,
        degrade_producer=degrade_producer,
        # The async NL worker applies the FTY-372 never-fail degrade/still-working
        # routing on infra exhaustion; the synchronous label path opts out of that
        # (no scheduler) and instead surfaces a transient exhaustion for the route to
        # turn into a retryable ``503`` (FTY-390).
        allow_infra_never_fail=label_upload is None,
        synchronous_label=synchronous_label,
    )

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
    except Exception as exc:
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
    *,
    degrade_producer: DegradeProducer | None = None,
    allow_infra_never_fail: bool = True,
    synchronous_label: bool = False,
) -> ProcessResult:
    """Apply the pipeline outcome to the run, job, and event, and commit.

    Each terminal outcome commits **atomically**: the parse step's structured
    products (candidates / questions accumulated on ``context``), the run/job
    status writes, and the event's status transition are all staged on the
    session and flushed by a **single** commit — the one inside
    :func:`~app.services.log_events.transition_event`. There is no intermediate
    commit before the transition, so a crash or redelivery either sees the whole
    finalized state or none of it; resolved rows can never be durably committed
    while the event is still ``processing``. The transition is validated against
    the legal-transition table before that commit runs, so an illegal transition
    fails closed with nothing persisted. A failed (retry) outcome persists no
    derived data — the step failed closed — and commits once directly.

    ``allow_infra_never_fail`` gates the FTY-372 never-fail infra routing. It is
    ``True`` for the asynchronous NL food/exercise worker (a per-run ceiling breach or a
    transient-exhaustion degrades to a rough estimate or stays still-working). It is
    ``False`` for the **synchronous label upload** path (no async scheduler): a
    still-working ``processing`` state would be a dead end the client polls forever.

    ``synchronous_label`` (FTY-390) then routes that path's transient exhaustion: rather
    than the old terminal ``failed`` (the infrastructure-rejects-good-faith-input sin on
    the label-photo path), a transient (retryable) exhaustion leaves the event
    non-terminal and is surfaced via :attr:`ProcessResult.transient_exhausted`, so the
    in-request route rolls back and returns a retryable ``503`` with nothing persisted
    (``label-upload.md``). Terminal ``failed`` stays reserved for genuinely-not-a-label
    input and the fail-closed validation gates (FTY-370). A label-path per-run budget
    breach — not a transient error — still lands terminal ``failed`` here.
    """

    outcome = result.outcome

    if outcome is PipelineOutcome.COMPLETED:
        _persist_candidates(session, run, context)
        _apply_event_name(event, context)
        run.status = EstimationRunStatus.COMPLETED
        job.status = EstimationJobStatus.SUCCEEDED
        session.add_all([run, job])
        # Event-terminal: hard-delete the event's transient, unsaved images in
        # the same transaction as the terminal status write (FTY-376,
        # ``log-attachments.md`` v3). Saved rows are never touched; a no-op for
        # an event without transient attachments.
        purge_transient_for_event(session, event.id)
        transition_event(session, event, LogEventStatus.COMPLETED)
        return _result(job, event, run, should_retry=False)

    if outcome is PipelineOutcome.NEEDS_CLARIFICATION:
        _persist_clarification_questions(session, run, context)
        run.status = EstimationRunStatus.NEEDS_CLARIFICATION
        job.status = EstimationJobStatus.NEEDS_CLARIFICATION
        session.add_all([run, job])
        transition_event(session, event, LogEventStatus.NEEDS_CLARIFICATION)
        return _result(job, event, run, should_retry=False)

    if outcome is PipelineOutcome.PARTIALLY_RESOLVED:
        # Item-scoped partial resolution (FTY-278/FTY-329): commit the costable
        # siblings (``resolved`` rows + evidence/products) and persist each un-costable
        # component as an ``unresolved`` row owning its item-scoped question, then land
        # the event ``partially_resolved`` — all in the single terminal transaction. The
        # run/job stay ``needs_clarification`` (the worker-terminal awaiting-answer
        # status, re-opened only by the clarification resolve — ``estimation-jobs.md``
        # v3); only the *event* transition differs from the whole-event case.
        _persist_candidates(session, run, context)
        _persist_item_scoped_clarifications(session, run, context)
        _apply_event_name(event, context)
        run.status = EstimationRunStatus.NEEDS_CLARIFICATION
        job.status = EstimationJobStatus.NEEDS_CLARIFICATION
        session.add_all([run, job])
        transition_event(session, event, LogEventStatus.PARTIALLY_RESOLVED)
        return _result(job, event, run, should_retry=False)

    # Failed: routed by failure class in a dedicated helper (keeps this dispatcher small).
    return _finalize_failed(
        session,
        job,
        event,
        run,
        result,
        context,
        degrade_producer=degrade_producer,
        allow_infra_never_fail=allow_infra_never_fail,
        synchronous_label=synchronous_label,
    )


def _finalize_failed(
    session: Session,
    job: EstimationJob,
    event: LogEvent,
    run: EstimationRun,
    result: PipelineResult,
    context: EstimationContext,
    *,
    degrade_producer: DegradeProducer | None,
    allow_infra_never_fail: bool,
    synchronous_label: bool,
) -> ProcessResult:
    """Route a ``FAILED`` pipeline outcome by failure class (FTY-372 + FTY-390).

    - on the **async worker** an infrastructure failure — a per-run ceiling breach
      (FTY-363) or a transient failure that exhausted the attempt-level bound — never
      lands terminal ``failed``: it degrades to a rough estimate when the run interpreted
      anything, else keeps the event in the honest still-working ``processing`` state;
    - on the **synchronous label** path a transient exhaustion likewise never lands
      terminal ``failed`` (FTY-390): the event is left non-terminal and the exhaustion is
      surfaced (``transient_exhausted``) so the in-request route rolls back and returns a
      retryable ``503`` with nothing persisted (``label-upload.md``);
    - a transient failure with attempts remaining takes a standard bounded retry;
    - a deterministic, non-retryable, non-budget failure (``empty_input`` / the narrowed
      ``unparseable_input`` / a fail-closed validation gate, or a label-path per-run
      budget breach) is terminal ``failed``.
    """

    transient_exhausted = result.retryable and job.attempts >= job.max_attempts
    infra_exhaustion = is_run_budget_breach(result.error) or transient_exhausted
    if allow_infra_never_fail and infra_exhaustion:
        return _degrade_or_still_working(
            session, job, event, run, result, context, degrade_producer=degrade_producer
        )

    if synchronous_label and transient_exhausted:
        # The synchronous label upload ran out of its bounded in-request retry budget on a
        # transient (retryable) vision-provider error. Keep the event non-terminal (a failed
        # retry outcome persists no derived data — the step failed closed) and surface the
        # exhaustion; the route discards this event and returns a retryable ``503`` so the
        # client, which still holds the image locally, can retry without a dead ``failed``
        # entry (FTY-390). Terminal ``failed`` stays reserved for genuinely-not-a-label
        # input (FTY-370).
        run.status = EstimationRunStatus.FAILED
        run.error = result.error
        job.status = EstimationJobStatus.RUNNING
        session.add_all([run, job])
        session.commit()
        return _result(job, event, run, should_retry=False, transient_exhausted=True)

    if result.retryable and job.attempts < job.max_attempts:
        # Retries remain: keep the job ``running`` and the event ``processing``.
        run.status = EstimationRunStatus.FAILED
        run.error = result.error
        job.status = EstimationJobStatus.RUNNING
        session.add_all([run, job])
        session.commit()
        return _result(job, event, run, should_retry=True)

    # Deterministic non-food/empty input (or a fail-closed validation gate, or a label-path
    # per-run budget breach): terminal ``failed`` with nothing persisted. Purge transient
    # images atomically with the write.
    run.status = EstimationRunStatus.FAILED
    run.error = result.error
    job.status = EstimationJobStatus.FAILED
    session.add_all([run, job])
    purge_transient_for_event(session, event.id)
    transition_event(session, event, LogEventStatus.FAILED)
    return _result(job, event, run, should_retry=False)


def _degrade_or_still_working(
    session: Session,
    job: EstimationJob,
    event: LogEvent,
    run: EstimationRun,
    result: PipelineResult,
    context: EstimationContext,
    *,
    degrade_producer: DegradeProducer | None,
) -> ProcessResult:
    """Route an infra-exhausted run to a rough degrade or the honest still-working state.

    The never-fail split (FTY-370/FTY-372): when the run interpreted ≥1 candidate the
    worker commits a rough, budget-free estimate and lands ``completed``; when it
    interpreted nothing the event stays ``processing`` with a bounded, long-backoff
    auto-retry. Neither branch ever lands terminal ``failed`` for the infra reason.
    """

    if _has_interpreted_candidates(context):
        return _degrade_and_complete(
            session, job, event, run, context, _degrade_reason(result.error), degrade_producer
        )
    return _still_working(session, job, event, run, result)


def _has_interpreted_candidates(context: EstimationContext) -> bool:
    """Whether the run interpreted ≥1 food/exercise candidate before the infra failure.

    The degrade-vs-still-working discriminator (FTY-372): a parsed food/exercise candidate
    (or an item the earlier tiers already costed) means the user described something the
    worker can commit a rough estimate for; nothing interpreted (e.g. the breach fired
    during parse) means there is nothing to estimate, so the event stays still-working.
    """

    return bool(
        context.food_candidates
        or context.exercise_candidates
        or context.resolved_food_items
        or context.resolved_exercise_items
    )


def _degrade_reason(error: str | None) -> str:
    """The content-free degrade label for an infra failure ``error`` (FTY-372).

    A per-run ceiling breach carries its own fixed :data:`RUN_BUDGET_REASONS` label
    verbatim; anything else reaching this path is a transient-exhaustion, recorded under
    the fixed ``provider_transient_error`` label. Either way the degrade producer only
    ever sees a closed, content-free reason — never a raw transient ``StepError`` message.
    """

    if error is not None and is_run_budget_breach(error):
        return error
    return PROVIDER_TRANSIENT_EXHAUSTED


def _degrade_and_complete(
    session: Session,
    job: EstimationJob,
    event: LogEvent,
    run: EstimationRun,
    context: EstimationContext,
    reason: str,
    degrade_producer: DegradeProducer | None,
) -> ProcessResult:
    """Commit a rough, budget-free estimate for every interpreted food candidate.

    Uniform worker safety net (FTY-372): a residual hard breach terminated the run
    mid-flight, so rather than reconcile a partial mix, every interpreted food candidate
    is re-cast as one rough, honestly-labelled ``resolved`` row via the FTY-371 degrade
    producer in **budget-free** mode (``budget_free=True`` — **no** additional provider
    call). Exercise items were costed deterministically without provider budget, so they
    are preserved untouched. The degraded rows, the run/job status writes, and the
    ``processing → completed`` transition commit **atomically** in the single
    :func:`transition_event` commit, exactly like the completed path.
    """

    producer = degrade_producer or _default_degrade_producer()
    food_candidates = list(context.food_candidates)
    # Discard any partial food resolution and its leftover buckets: every interpreted
    # food candidate becomes exactly one degraded ``resolved`` row, so nothing is dropped
    # or double-represented.
    context.resolved_food_items = []
    context.pending_official_candidates = []
    context.unresolved_food_candidates = []
    context.item_scoped_clarifications = []
    context.clarification_questions = []
    for index, candidate in enumerate(food_candidates):
        context.resolved_food_items.append(
            producer.degrade_food_candidate(
                context, candidate, reason=reason, index=index, budget_free=True
            )
        )

    # Re-copy the sanitized metadata: the degrade appended its own trace/assumptions after
    # ``process_estimation`` first recorded the (pre-degrade) run metadata.
    _record_run_metadata(run, context)
    _persist_candidates(session, run, context)
    # The meal name (FTY-422) is derived by the parse step before the infra breach, so
    # a degraded-but-completing event is still named from what was interpreted.
    _apply_event_name(event, context)
    run.status = EstimationRunStatus.COMPLETED
    # A degrade lands ``completed``, not failed — no ``error`` on the run.
    run.error = None
    job.status = EstimationJobStatus.SUCCEEDED
    session.add_all([run, job])
    # Event-terminal: purge transient images atomically with the completion.
    purge_transient_for_event(session, event.id)
    transition_event(session, event, LogEventStatus.COMPLETED)
    return _result(job, event, run, should_retry=False)


def _still_working(
    session: Session,
    job: EstimationJob,
    event: LogEvent,
    run: EstimationRun,
    result: PipelineResult,
) -> ProcessResult:
    """Keep the event in the honest still-working / will-retry state (FTY-372).

    The run attempt failed for infrastructure reasons **with nothing interpreted**, so
    there is nothing to estimate — but the entry the user typed in good faith must not
    come back ``failed``. The event stays ``processing`` and the job stays ``running``
    (non-terminal, exactly like the retries-remain branch), re-queued with a bounded,
    long-backoff auto-retry up to :data:`DEFAULT_MAX_INFRA_RETRY_ATTEMPTS`. Once even that
    extended budget is exhausted the event **stays** in this deferred still-working state
    (``should_retry`` False, still ``processing``) — the user's manual retry re-opens it —
    and never becomes terminal ``failed``. ``run.error`` carries the content-free failure
    label only.
    """

    run.status = EstimationRunStatus.FAILED
    run.error = result.error
    job.status = EstimationJobStatus.RUNNING
    session.add_all([run, job])
    session.commit()
    if job.attempts < DEFAULT_MAX_INFRA_RETRY_ATTEMPTS:
        return _result(
            job,
            event,
            run,
            should_retry=True,
            retry_countdown_seconds=infra_retry_countdown(job.attempts),
        )
    return _result(job, event, run, should_retry=False)


def _default_degrade_producer() -> DegradeProducer:
    """Build the worker's default budget-free degrade producer (FTY-372).

    Used only on the rare residual hard-exhaustion path when no producer was injected.
    Budget-free degradation makes **no** provider call, so the bare provider held here is
    never invoked; it is constructed the same cheap, network-free way the worker pipeline
    builds its provider. The estimate-first rough-fallback config mirrors the pipeline's.
    """

    from app.llm import build_provider, load_llm_settings  # noqa: PLC0415 — lazy: heavy import
    from app.settings import load_settings  # noqa: PLC0415 — lazy: only the degrade path

    app_settings = load_settings()
    return DegradeProducer(
        provider=build_provider(load_llm_settings()),
        clarify_mode=app_settings.estimator_clarify_mode,
        model_prior_confidence_floor=app_settings.estimator_model_prior_confidence_floor,
    )


def _result(
    job: EstimationJob,
    event: LogEvent,
    run: EstimationRun,
    *,
    should_retry: bool,
    retry_countdown_seconds: int | None = None,
    transient_exhausted: bool = False,
) -> ProcessResult:
    """Build a :class:`ProcessResult` snapshot from the post-commit state."""

    return ProcessResult(
        job_status=EstimationJobStatus(job.status),
        event_status=LogEventStatus(event.status),
        run_id=run.id,
        attempts=job.attempts,
        should_retry=should_retry,
        retry_countdown_seconds=retry_countdown_seconds,
        transient_exhausted=transient_exhausted,
    )
