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

if TYPE_CHECKING:
    from app.estimator.food_step import BarcodeResolver, FoodResolver
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

    def record_step(self, name: str, status: str) -> None:
        """Append a sanitized trace entry for a completed step.

        Only the step name and a status label are recorded — never inputs,
        outputs, prompts, or user text.
        """

        self.trace.append({"step": name, "status": status})


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

    The steps run in order. The first :class:`NeedsClarification` ends the run as
    ``needs_clarification``; the first :class:`StepFailed` ends it as ``failed``
    (terminal, non-retryable); the first :class:`StepError` ends it as ``failed``
    (retryable). If every step completes, the outcome is ``completed``. The
    runner never inspects or copies ``context.raw_text`` into the result.
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
        return PipelineResult(PipelineOutcome.COMPLETED, None)


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
