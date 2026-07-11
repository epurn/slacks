"""The pluggable estimation pipeline contract (FTY-040).

This module defines the **step interface** the estimator step stories
(FTY-042 parse, FTY-043 exercise math, FTY-044 food resolution) implement, and
the runner that drives an ordered list of steps to a single terminal outcome.
FTY-040 ships only *stub* steps so the worker, idempotency, retry, and state
machine can be exercised end-to-end before any real parsing or calculation
exists.

Design
------

A step receives a mutable :class:`EstimationContext` and records what it did onto
it (tool names, source references, assumptions, validation errors, a sanitized
trace). A step signals a non-success outcome by raising:

- :class:`NeedsClarification` — terminal, **not** retryable: the input is
  ambiguous and only the user can resolve it.
- :class:`StepFailed` — terminal, **not** retryable: the input is deterministically
  unprocessable (empty/garbage/unparseable, or model output that failed schema
  validation), so retrying the same input cannot help. The worker fails the event
  immediately instead of burning retries.
- :class:`StepError` — a *retryable* failure (transient provider/tool error); the
  worker retries up to the bounded limit before giving up.

Anything written to the context must be **sanitized**: no raw prompts, no
secrets, no raw user text. The context carries ids and structured facts only,
matching ``docs/security/data-retention.md``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.estimator.decision_trace import (
    MAX_TRACE_ENTRIES,
    TRACE_TRUNCATED_DECISION,
    build_decision_entry,
)

if TYPE_CHECKING:
    from app.estimator.food_resolvers import BarcodeResolver, FoodResolver
    from app.estimator.interpretation import InterpretationSession
    from app.estimator.label_step import LabelInput
    from app.estimator.official_step import OfficialSourceResolveStep
    from app.estimator.parse_policy import ParsePolicySettings
    from app.estimator.user_text_step import UserTextResolveStep
    from app.llm.base import Provider


class NeedsClarification(Exception):
    """Raised by a step when the input is ambiguous and needs the user.

    Terminal and non-retryable: retrying the same ambiguous input cannot succeed,
    so the worker drives the event to ``needs_clarification`` rather than burning
    retries. ``reason`` is a short, sanitized label (never raw user text).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StepFailed(Exception):
    """Raised by a step on a deterministic, terminal failure (non-retryable).

    Unlike :class:`StepError`, retrying the same input cannot succeed: the input is
    empty/garbage/unparseable, or the model's output failed schema validation and
    is rejected (fail closed). The worker drives the event straight to ``failed``
    without consuming retries. ``reason`` is a short, sanitized label — never raw
    prompts, secrets, or raw user text — because it is persisted on the run.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StepError(Exception):
    """Raised by a step on a retryable failure (e.g. a transient tool error).

    ``message`` must be sanitized — a short description or error class, never raw
    prompts, secrets, or raw user text — because it is persisted on the run.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PipelineOutcome(StrEnum):
    """The single terminal outcome of running the pipeline over one event."""

    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    #: Item-scoped partial resolution (FTY-278/FTY-329): at least one component was
    #: costed and committed while at least one other component owns an item-scoped
    #: clarification. The event lands ``partially_resolved`` (``log-events.md`` v6);
    #: the run/job status stays ``needs_clarification`` (``estimation-jobs.md`` v3).
    PARTIALLY_RESOLVED = "partially_resolved"
    FAILED = "failed"


@dataclass(frozen=True)
class CandidateDraft:
    """A parsed, unresolved food/exercise candidate accumulated by the parse step.

    A neutral value object the parse step (FTY-042) fills and the worker persists
    into ``derived_food_items`` / ``derived_exercise_items``. It carries the
    structured parse only — name and raw portion phrase plus an optional
    best-effort unit/amount — and never any energy value (resolution is
    FTY-043/044). It is *not* sanitized run metadata: it is product data persisted
    to its own user-owned table, never copied into the run ``trace``.
    """

    name: str
    quantity_text: str = ""
    unit: str | None = None
    amount: float | None = None
    #: Normalized UPC/EAN barcode for a packaged product, when one was supplied
    #: (e.g. a future scan, FTY-063). Present ⇒ the food step prefers the Open Food
    #: Facts barcode source over generic USDA lookup (FTY-060). ``None`` for a
    #: plain generic-food candidate.
    barcode: str | None = None
    #: Restaurant / manufacturer / packaged-product brand when the parse step
    #: classified this as a *named* product (FTY-062). Present ⇒ a USDA/OFF miss
    #: routes the candidate to the official-source resolver (search + hardened fetch,
    #: then a model-prior fallback) instead of stopping at ``needs_clarification``.
    #: ``None`` for a generic food.
    brand: str | None = None
    #: Explicit nutrition facts the user stated in the entry text for this item
    #: (FTY-279/FTY-280): an as-logged calorie total and/or macro grams, carried
    #: verbatim from the parse (``stated_*`` on the schema candidate) as untrusted
    #: evidence. A candidate whose ``stated_calories`` is present resolves from the
    #: rank-1 ``user_text`` tier (``user_text_step.py``) rather than USDA/OFF; the
    #: food step validates plausibility before any of it backs a persisted number.
    #: ``None`` when the user stated no such fact.
    stated_calories: float | None = None
    stated_protein_g: float | None = None
    stated_carbs_g: float | None = None
    stated_fat_g: float | None = None


@dataclass(frozen=True)
class ClarificationDraft:
    """A clarification question the worker will persist for the answer flow.

    ``text`` is the specific missing detail shown to the user. ``options`` are
    display-only quick-pick candidates; they never constrain the answer endpoint,
    which always accepts free text.
    """

    text: str
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComponentClarification:
    """One food component the resolver could not cost, with its two question shapes.

    The item-scoped partial-resolution carrier (FTY-329): a resolution step collects
    this instead of raising a whole-event :class:`NeedsClarification` when a single
    component is un-costable. ``candidate`` is the parsed component the worker persists
    as an ``unresolved`` ``derived_food_items`` row; ``question`` is the **item-scoped**
    draft naming that component by its sanitized parse name (linked to the row via the
    ``derived_food_item_id`` carrier when the event lands ``partially_resolved``);
    ``event_level_question`` is the original generic draft the step built, used verbatim
    only in the whole-event ``needs_clarification`` fallback (no component costable), so
    that path's wording is unchanged. Neither draft ever carries raw diary text — the
    component name is bounded, schema-validated parse data.
    """

    candidate: CandidateDraft
    question: ClarificationDraft
    event_level_question: ClarificationDraft


def component_scoped_question(
    candidate: CandidateDraft, event_level: ClarificationDraft, reason: str
) -> ClarificationDraft:
    """Build the item-scoped question naming ``candidate`` by its sanitized parse name.

    The component's ``name`` is bounded, schema-validated parse data (already the
    ``derived_food_items.name`` the user sees), never raw diary text, so embedding it
    keeps the question specific without leaking the entry phrase. ``reason`` is the
    resolver's sanitized :class:`NeedsClarification` reason and selects the question
    intent (a quantity ask vs. an unknown-food ask); the display ``options`` are carried
    over from the step's original generic draft unchanged.
    """

    name = candidate.name.strip() or "that item"
    if reason == "unresolvable_quantity":
        text = f"How much {name} did you have (for example, in grams, millilitres, or servings)?"
    elif reason == "barcode_unknown":
        text = f"We couldn't find that barcode's product. Which food was \"{name}\", and how much?"
    else:
        text = f'Which food was "{name}"? We couldn\'t find a nutrition match.'
    return ClarificationDraft(text=text, options=list(event_level.options))


def collect_component_clarification(
    context: EstimationContext, candidate: CandidateDraft, reason: str, *, step: str
) -> None:
    """Record ``candidate``'s item-scoped clarification instead of aborting the run.

    A food resolution step (``food_step`` / ``official_step``) set a generic draft on
    ``context.clarification_questions`` just before raising :class:`NeedsClarification`
    for one component. This captures that draft as the event-level fallback, clears the
    event-level slot (so a later fully-costed candidate does not inherit it), builds the
    item-scoped question naming the component, and appends the pair to
    ``context.item_scoped_clarifications`` for the worker to finalize.

    ``step`` names the resolution step that could not cost the component; it labels the
    sanitized ``component_clarified`` per-component trace outcome (FTY-329) so the partial
    route is explainable without the trace ever carrying the component name or raw text.
    """

    event_level = (
        context.clarification_questions[-1]
        if context.clarification_questions
        else ClarificationDraft(text=f'Which food was "{candidate.name}"?')
    )
    context.clarification_questions = []
    context.item_scoped_clarifications.append(
        ComponentClarification(
            candidate=candidate,
            question=component_scoped_question(candidate, event_level, reason),
            event_level_question=event_level,
        )
    )
    context.record_decision(step, "outcome", outcome="component_clarified")


@dataclass(frozen=True)
class AnsweredClarification:
    """One answered (question, answer) pair carried into a re-estimate (FTY-171).

    The clarification answer flow (``log-events.md`` v4) re-estimates a
    ``needs_clarification`` event with every detail answered so far as
    **structured input** — the raw phrase is never mutated. Both fields are
    untrusted user-tied text: the parse step folds them into the prompt as
    delimited data, and they are never copied into the sanitized run ``trace``.
    """

    question_text: str
    answer_text: str


@dataclass(frozen=True)
class ResolvedExerciseItem:
    """A costed exercise candidate produced by the exercise calculator (FTY-043).

    Carries the parsed shape (``name`` and raw portion phrase plus the best-effort
    ``unit``/``amount``) alongside the deterministic burn: the matched MET value, the
    duration in minutes the burn was computed over, and the net ``active_calories``
    (the ``MET − 1`` convention). The worker persists it as a **resolved**
    ``derived_exercise_items`` row. Like :class:`CandidateDraft` it is product data,
    never copied into the sanitized run ``trace``.
    """

    name: str
    quantity_text: str
    unit: str | None
    amount: float | None
    met: float
    duration_minutes: float
    active_calories: float


@dataclass(frozen=True)
class ResolvedFoodItem:
    """A costed generic-food candidate produced by the food resolver (FTY-044).

    Carries the parsed shape (``name`` and raw portion phrase plus the best-effort
    ``unit``/``amount``) alongside the deterministic resolution: the portion ``grams``
    and the canonical ``calories``/macros computed from a source's per-100g facts. It
    also carries the provenance the worker writes as an ``evidence_sources`` row — the
    source classification/reference, the content hash, the fetch time, and the
    per-100g facts snapshot. ``product_id`` links the global ``products`` cache row for
    a database source (USDA FDC / Open Food Facts) and is ``None`` for a source with no
    global cache row — an official-source page (FTY-062) or a model-prior estimate
    (FTY-062), which are per-resolution, not shared. ``assumptions`` records the
    documented assumptions behind the number (e.g. the model-prior fallback reason),
    persisted on the evidence row and surfaced so the entry stays user-editable. Like
    :class:`CandidateDraft` it is product data persisted to its own user-owned table,
    never copied into the sanitized run ``trace``.
    """

    name: str
    quantity_text: str
    unit: str | None
    amount: float | None
    #: Resolved portion mass; ``None`` for a ``user_text`` ``as_logged`` item, which
    #: has no mass (the user gave a calorie total, not a quantity — FTY-280).
    grams: float | None
    calories: float
    #: Canonical macros; ``None`` when *unknown* — a ``user_text`` macro the user did
    #: not state and the estimator did not fill (FTY-279), kept distinct from a real
    #: ``0 g``. A database/label/official/reference source always supplies all three.
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    product_id: uuid.UUID | None
    source_type: str
    source_ref: str
    content_hash: str
    fetched_at: datetime
    calories_per_100g: float | None
    protein_per_100g: float | None
    carbs_per_100g: float | None
    fat_per_100g: float | None
    #: Documented assumptions behind this resolution (e.g. the model-prior fallback
    #: reason). Empty for a deterministic database source.
    assumptions: tuple[str, ...] = ()
    #: What the immutable fact snapshot is expressed against (``evidence-retrieval.md``
    #: normalized-fact schema): ``per_100g`` for a database/label/official/reference
    #: source (the default, scaled by the serving math), ``per_serving`` for a
    #: count-serving source (FTY-252) whose snapshot holds the source's per-counted-
    #: serving facts, or ``as_logged`` for a user-stated total (FTY-279/FTY-280) that
    #: is *already* the consumed-quantity total and must **not** be re-scaled. On an
    #: ``as_logged`` item the snapshot columns hold the as-logged totals (calories the
    #: user stated; a macro is the estimated total or ``None`` when unknown),
    #: disambiguated by this basis — never reinterpreted as a per-100g density.
    basis: str = "per_100g"
    #: Per-field provenance when a record's fields have heterogeneous origins
    #: (FTY-279): maps ``calories`` / ``protein_g`` / ``carbs_g`` / ``fat_g`` to
    #: ``user_stated`` / ``estimated`` / ``unknown``. ``None`` when every present field
    #: shares this record's ``source_type`` (the database/label/official/reference
    #: case, unchanged).
    field_provenance: dict[str, str] | None = None


@dataclass(frozen=True)
class ResolvedLabelItem:
    """A costed food item extracted from a user-provided nutrition label (FTY-061).

    Carries the deterministic resolution of a label scan: the consumed portion
    ``grams`` and the canonical ``calories``/macros the backend computed from the
    schema-validated panel facts plus the serving/quantity, never from the model.
    It also carries the provenance the worker writes as an ``evidence_sources`` row
    with ``source_type = user_label`` (rank 1, above any database lookup): the
    content hash of the image the facts were extracted from, the extraction
    timestamp, and the immutable per-100g facts snapshot. There is **no**
    ``product_id`` — a label is user-provided evidence, not a global cache row. Like
    :class:`ResolvedFoodItem` it is product data persisted to a user-owned table,
    never copied into the sanitized run ``trace``.
    """

    name: str
    quantity_text: str
    unit: str | None
    amount: float | None
    grams: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    source_type: str
    source_ref: str
    content_hash: str
    extracted_at: datetime
    calories_per_100g: float
    protein_per_100g: float
    carbs_per_100g: float
    fat_per_100g: float


@dataclass
class EstimationContext:
    """Mutable accumulator threaded through the pipeline steps.

    ``raw_text`` is the untrusted user input the steps parse; it is **never**
    copied into ``trace`` or any persisted *run* field. ``food_candidates`` /
    ``exercise_candidates`` / ``clarification_questions`` are the structured parse
    products the worker persists into their own user-owned tables on a successful
    or needs-clarification outcome. The remaining fields are the sanitized,
    structured record the worker writes onto the :class:`EstimationRun`.
    """

    log_event_id: uuid.UUID
    user_id: uuid.UUID
    raw_text: str
    #: The user's canonical body weight (kg) from their profile, loaded by the
    #: worker for the exercise calculator (FTY-043). ``None`` when the profile has
    #: no weight yet; the calculator fails closed rather than guessing a burn.
    weight_kg: float | None = None
    #: The untrusted nutrition-label image (plus consumed quantity) the label step
    #: (FTY-061) extracts from, when this event carries one. ``None`` for a plain
    #: text estimation; the label step is a no-op without it.
    label_input: LabelInput | None = None
    #: Every answered (question, answer) pair persisted for this event, oldest
    #: first (FTY-171). Empty on a first estimate; on an answer-triggered
    #: re-estimate the parse step applies these as structured detail alongside the
    #: unchanged ``raw_text``. Untrusted user text — never copied into ``trace``.
    answered_clarifications: list[AnsweredClarification] = field(default_factory=list)
    #: The run's interpretation session (FTY-324/FTY-325): owns the raw text and
    #: the revisable item hypothesis for the run's lifetime. Set by the parse
    #: step; later steps (FTY-326) may consult it to re-open interpretation with
    #: accumulated evidence. In-memory only — never persisted, never copied into
    #: ``trace`` or any run field (it holds raw user text).
    interpretation_session: InterpretationSession | None = None
    provider: str | None = None
    model: str | None = None
    schema_version: str | None = None
    tool_names: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    food_candidates: list[CandidateDraft] = field(default_factory=list)
    exercise_candidates: list[CandidateDraft] = field(default_factory=list)
    #: Branded food candidates the USDA/OFF food step could not resolve and handed
    #: to the official-source resolver (FTY-062). The official step consumes this
    #: list (clearing it once processed); a candidate left here when no official step
    #: runs is persisted ``unresolved`` like any other leftover.
    pending_official_candidates: list[CandidateDraft] = field(default_factory=list)
    #: Food candidates the food step saw but left ``unresolved`` (no applicable
    #: enabled source, and not official-source eligible). The worker persists these
    #: as ``unresolved`` rows alongside any resolved items, so a mixed batch never
    #: silently drops a candidate.
    unresolved_food_candidates: list[CandidateDraft] = field(default_factory=list)
    resolved_exercise_items: list[ResolvedExerciseItem] = field(default_factory=list)
    resolved_food_items: list[ResolvedFoodItem] = field(default_factory=list)
    resolved_label_items: list[ResolvedLabelItem] = field(default_factory=list)
    clarification_questions: list[ClarificationDraft] = field(default_factory=list)
    #: Item-scoped partial outcomes (FTY-329): one per food component the resolver
    #: could not cost. Collected by the food/official steps instead of raising a
    #: whole-event :class:`NeedsClarification`, so costable siblings still resolve. On
    #: a mixed run (≥1 costable) the worker commits the siblings, persists each of these
    #: as an ``unresolved`` row owning its item-scoped question, and lands the event
    #: ``partially_resolved``; when nothing else is costable these fall back to
    #: whole-event ``needs_clarification`` questions.
    item_scoped_clarifications: list[ComponentClarification] = field(default_factory=list)

    def record_step(self, name: str, status: str) -> None:
        """Append a sanitized trace entry for a completed step.

        Only the step name and a status label are recorded — never inputs,
        outputs, prompts, or user text.
        """

        self.trace.append({"step": name, "status": status})

    def record_decision(self, step: str, decision: str, **fields: object) -> None:
        """Append a bounded, sanitized structured decision entry (FTY-255).

        Every field passes the :mod:`app.estimator.decision_trace` sanitizers —
        bounded labels, non-secret source refs, clamped counts — so the trace can
        explain source routing (which tier saw a candidate, what reference was
        considered, why it was accepted/rejected/deferred/clarified) without ever
        carrying raw event text, prompts, page content, or secrets. Once the
        per-run bound is reached a single ``trace_truncated`` marker is appended
        and further decisions are dropped.
        """

        if len(self.trace) >= MAX_TRACE_ENTRIES:
            last = self.trace[-1]
            if last.get("decision") != TRACE_TRUNCATED_DECISION:
                self.trace.append({"step": step, "decision": TRACE_TRUNCATED_DECISION})
            return
        self.trace.append(build_decision_entry(step, decision, **fields))


@runtime_checkable
class EstimationStep(Protocol):
    """A single estimation pipeline step.

    Implementations (FTY-042/043/044) carry a stable ``name`` and mutate the
    context in :meth:`run`, raising :class:`NeedsClarification` or
    :class:`StepError` to signal a non-success outcome.
    """

    @property
    def name(self) -> str:
        """A stable identifier for the step, recorded in the run trace."""
        ...

    def run(self, context: EstimationContext) -> None:
        """Execute the step against ``context``; mutate it in place."""
        ...


@dataclass(frozen=True)
class StubParseStep:
    """Placeholder for the NL parse step (FTY-042). A no-op that records itself."""

    name: str = "stub_parse"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.record_step(self.name, "ok")


@dataclass(frozen=True)
class StubCalculateStep:
    """Placeholder for the calculation step (FTY-043/044). Records itself only."""

    name: str = "stub_calculate"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.record_step(self.name, "ok")


@dataclass(frozen=True)
class PipelineResult:
    """The outcome of a pipeline run plus an optional sanitized error message.

    ``retryable`` is only meaningful for a ``FAILED`` outcome: ``True`` for a
    transient :class:`StepError` (the worker may retry within its bound) and
    ``False`` for a deterministic :class:`StepFailed` (the worker fails closed
    immediately). ``COMPLETED`` / ``NEEDS_CLARIFICATION`` are terminal regardless.
    """

    outcome: PipelineOutcome
    error: str | None = None
    retryable: bool = True


class Pipeline:
    """An ordered list of estimation steps run to a single terminal outcome.

    The steps run in order. A **whole-event** :class:`NeedsClarification` (raised by
    the parse/user-text safety gates) ends the run as ``needs_clarification``; the
    first :class:`StepFailed` ends it as ``failed`` (terminal, non-retryable); the
    first :class:`StepError` ends it as ``failed`` (retryable). If every step
    completes, the outcome depends on the item-scoped partial outcomes the food
    resolution steps collected (FTY-329): none → ``completed``; some, with ≥1 costable
    component → ``partially_resolved`` (the costable siblings are committed and each
    un-costable component owns its item-scoped question); some, with nothing costable →
    ``needs_clarification`` (the collected drafts fall back to whole-event questions).
    The runner never inspects or copies ``context.raw_text`` into the result.
    """

    def __init__(self, steps: list[EstimationStep]) -> None:
        self._steps = steps

    @property
    def steps(self) -> list[EstimationStep]:
        return list(self._steps)

    def run(self, context: EstimationContext) -> PipelineResult:
        for step in self._steps:
            try:
                step.run(context)
            except NeedsClarification as exc:
                context.record_step(step.name, "needs_clarification")
                return PipelineResult(PipelineOutcome.NEEDS_CLARIFICATION, exc.reason)
            except StepFailed as exc:
                context.record_step(step.name, "failed")
                return PipelineResult(PipelineOutcome.FAILED, exc.reason, retryable=False)
            except StepError as exc:
                context.record_step(step.name, "failed")
                return PipelineResult(PipelineOutcome.FAILED, exc.message, retryable=True)
        return _terminal_outcome(context)


def _has_costable_component(context: EstimationContext) -> bool:
    """Whether the run committed at least one costed item (food, exercise, or label).

    The mixed-vs-none discriminator for item-scoped partial resolution: a costable
    component is a committed ``resolved``/``proposed`` item that surfaces and counts, so
    a run with one costable sibling and one un-costable component is a *partial* outcome
    rather than a whole-event clarification.
    """

    return bool(
        context.resolved_food_items
        or context.resolved_exercise_items
        or context.resolved_label_items
    )


def _terminal_outcome(context: EstimationContext) -> PipelineResult:
    """Decide the terminal outcome once every step ran without a whole-event abort.

    With no collected item-scoped clarification the run is ``completed``. Otherwise the
    outcome splits on whether any component was costable (FTY-278): a mixed run commits
    the costable siblings and lands ``partially_resolved`` (each un-costable component
    keeps its item-scoped question); a run with nothing costable falls back to a
    whole-event ``needs_clarification``, promoting the collected drafts to the
    event-level questions the worker persists (no ``derived_food_item_id`` carrier).
    """

    if not context.item_scoped_clarifications:
        return PipelineResult(PipelineOutcome.COMPLETED, None)
    if _has_costable_component(context):
        # Emit the sanitized per-component partial-finalization vocabulary (FTY-329):
        # one ``component_resolved`` per committed sibling (by its non-secret source ref,
        # never its name) plus a single ``partial_finalized`` marker carrying how many
        # siblings were counted. These label the partial route so it is explainable
        # without the trace ever carrying the diary phrase or a component name.
        for item in context.resolved_food_items:
            context.record_decision(
                "partial_resolution",
                "outcome",
                outcome="component_resolved",
                source_ref=item.source_ref,
            )
        context.record_decision(
            "partial_resolution",
            "outcome",
            outcome="partial_finalized",
            result_count=len(context.resolved_food_items),
        )
        return PipelineResult(PipelineOutcome.PARTIALLY_RESOLVED, None)
    # Nothing costable → whole-event clarification. Promote the collected drafts to the
    # event-level questions the ``needs_clarification`` finalize persists (no carrier),
    # preserving the un-named generic wording that path has always used. The collected
    # ``item_scoped_clarifications`` are left in place (unused by that finalize) so a
    # scoped re-estimate — where a single component's un-costable outcome is not
    # "whole-event" — can still read back its component-named question.
    context.clarification_questions = [
        clarification.event_level_question for clarification in context.item_scoped_clarifications
    ]
    return PipelineResult(PipelineOutcome.NEEDS_CLARIFICATION, None)


def default_pipeline(
    provider: Provider,
    *,
    parse_policy: ParsePolicySettings | None = None,
    food_resolver: FoodResolver | None = None,
    barcode_resolver: BarcodeResolver | None = None,
    official_step: OfficialSourceResolveStep | None = None,
    user_text_step: UserTextResolveStep | None = None,
) -> Pipeline:
    """Build the v1 estimation pipeline: NL parse, exercise calc, food resolution.

    The parse step (FTY-042) turns the event text into schema-validated candidates
    using ``provider``; the exercise step (FTY-043) costs the exercise candidates
    into net active calories deterministically; the food step (FTY-044 generic +
    FTY-060 barcode) resolves food candidates into calories/macros, preferring the
    Open Food Facts barcode source over generic USDA lookup. The food step is
    appended only when a ``food_resolver`` is supplied (it needs a database session
    for the product cache and evidence writes), which the worker always provides; an
    optional ``barcode_resolver`` adds the OFF source.

    ``official_step`` (FTY-062), when supplied, runs **after** the food step as the
    last resort before model-prior: it picks up the branded candidates the food step
    deferred (a USDA/OFF miss for a named restaurant/manufacturer/packaged product),
    resolves them from official sources via search + hardened fetch, and otherwise
    falls through to a model-prior estimate that carries an explicit source status.
    A resolver-less build (e.g. unit tests of composition) keeps food candidates
    unresolved, the pre-FTY-044 behavior. The worker contract (claim → run →
    transition) is unchanged.
    """

    # Imported here rather than at module top to avoid a cycle: the steps import the
    # context/exception types defined above in this module.
    from app.estimator.exercise_step import ExerciseCalculateStep  # noqa: PLC0415 — import cycle
    from app.estimator.food_step import FoodResolveStep  # noqa: PLC0415 — import cycle
    from app.estimator.parse import ParseStep  # noqa: PLC0415 — import cycle

    parse_step = (
        ParseStep(provider) if parse_policy is None else ParseStep(provider, policy=parse_policy)
    )
    steps: list[EstimationStep] = [parse_step, ExerciseCalculateStep()]
    if food_resolver is not None:
        # The user-text step (FTY-280) runs *before* the food step: it is the rank-1
        # ``user_text`` tier, so a candidate the user stated a calorie total for is
        # resolved from that evidence and removed from the food candidates the food
        # step then resolves from USDA/OFF. Wired only alongside the food step (it
        # produces the same resolved-item/evidence shape the worker persists).
        if user_text_step is not None:
            steps.append(user_text_step)
        steps.append(
            FoodResolveStep(
                food_resolver,
                barcode_resolver=barcode_resolver,
                clarify_mode=parse_step.policy.mode,
            )
        )
        # The official-source resolver only acts on candidates the food step deferred,
        # so it is wired in only alongside the food step.
        if official_step is not None:
            steps.append(official_step)
    return Pipeline(steps)


def label_pipeline(provider: Provider) -> Pipeline:
    """Build the nutrition-label extraction pipeline (FTY-061).

    A single :class:`~app.estimator.label_step.LabelResolveStep` that reads the
    event's label image (``context.label_input``) through the v2 vision provider,
    validates the panel, and costs it deterministically. This is a *separate*
    pipeline from :func:`default_pipeline`: a label event has an image rather than
    NL text, so it does not run the text parse step. The worker selects this
    pipeline when the event carries a label image.
    """

    # Imported here rather than at module top to avoid a cycle: the step imports the
    # context/exception types defined above in this module.
    from app.estimator.label_step import LabelResolveStep  # noqa: PLC0415 — import cycle

    return Pipeline([LabelResolveStep(provider)])
