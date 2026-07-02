"""The structured NL parse step (FTY-042; calibrated clarify gate FTY-159).

This is the first *real* estimation pipeline step. It draws N schema-validated
parse samples of a log event's raw text through the FTY-041 provider's
``structured_completion`` (the FTY-158 self-consistency sampler — parallel, with
a unanimous-first-window early stop so easy inputs stay cheap) and routes on the
validated samples plus their consistency signal:

- **parsed, calibrated-confident** → record food/exercise candidates onto the
  context; the worker persists them ``unresolved`` (no calories — FTY-043/044
  cost them).
- **needs clarification** (no sample parsed, or the hybrid consistency score
  falls below the calibrated operating point) → raise
  :class:`~app.estimator.pipeline.NeedsClarification`; the worker persists the
  questions and moves the event to ``needs_clarification``.
- **unparseable / empty / garbage** (unanimously) → raise
  :class:`~app.estimator.pipeline.StepFailed`; the event fails closed with a
  sanitized reason and *no* candidates are persisted.

The clarify decision is the FTY-159 **calibrated policy**
(:data:`app.estimator.clarify_policy.NL_PARSE_CLARIFY_POLICY`): the winning
signal from the bake-off over the labeled calibration sets (the FTY-158 hybrid
of sampling agreement and verbalized confidence) compared against a
data-derived operating point — not a self-reported confidence against a guessed
constant. The deterministic gates are unchanged: the FTY-156 plausibility
validator and the FTY-167 detail-signal override run exactly as before, on the
routed sample's items.

Trust boundary (security baseline + ``docs/security/security-baseline.md``): the
model is an untrusted analyst. Every sample is schema-validated before anything
is trusted; schema-invalid output is rejected (``StepFailed``), never persisted.
The prompt frames the user text as *data to extract from*
(:mod:`app.estimator.parse_prompt`), and the step never executes or follows
instructions embedded in that text — candidate names and questions are stored as
data through parameterized inserts. Raw text and raw model output are never
logged or copied into the run trace. Sampling N times adds no new trust
surface: each sample is the same validated call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.enums import CandidateType
from app.estimator.clarify_policy import NL_PARSE_CLARIFY_POLICY
from app.estimator.detail_signals import has_food_detail, parse_range_midpoint
from app.estimator.exercise import has_exercise_detail
from app.estimator.parse_prompt import build_parse_prompt
from app.estimator.pipeline import (
    AnsweredClarification,
    CandidateDraft,
    EstimationContext,
    NeedsClarification,
    StepError,
    StepFailed,
)
from app.estimator.plausibility import check_candidate
from app.estimator.self_consistency import (
    SelfConsistencySignal,
    collect_parse_samples,
)
from app.llm.base import Provider
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.schemas.parse import (
    PARSE_SCHEMA_VERSION,
    ParsedCandidate,
    ParseDisposition,
    ParseResult,
)

__all__ = [
    "DEFAULT_CLARIFICATION_QUESTION",
    "ParseStep",
    "build_parse_prompt",
]

#: Fallback question persisted when the samples route to ``needs_clarification``
#: but supply none — so a ``needs_clarification`` event always has at least one
#: question for the later answer flow.
DEFAULT_CLARIFICATION_QUESTION = "Could you clarify what you logged and how much?"


@dataclass(frozen=True)
class ParseStep:
    """Parse a log event's text into schema-validated candidates via the provider."""

    provider: Provider
    name: str = "parse"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        context.provider = self.provider.name
        context.schema_version = PARSE_SCHEMA_VERSION

        raw = context.raw_text.strip()
        if not raw:
            # Empty/whitespace input is deterministically unprocessable; do not
            # spend an LLM call on it.
            raise StepFailed("empty_input")

        signal = self._signal(raw, context.answered_clarifications)
        self._route(context, signal)
        context.record_step(self.name, "ok")

    def _signal(
        self, raw_text: str, answered: Sequence[AnsweredClarification]
    ) -> SelfConsistencySignal:
        """Sample the parse and compute the consistency signal, mapping failures.

        Draws the FTY-158 sample set (parallel, early-stopped when the first
        window is unanimous). ``answered`` folds the accumulated clarification
        answers into every sample's prompt as structured detail on an
        answer-triggered re-estimate (FTY-171); the raw text itself is passed
        through unchanged. Transient transport failures are retryable
        (:class:`StepError`); a schema-validation rejection or any other
        deterministic provider error is terminal and fails closed
        (:class:`StepFailed`) — a partially-failed sample set is never scored,
        and rejected output is never returned to the caller as trusted.
        """

        try:
            samples = collect_parse_samples(self.provider, raw_text, answered=answered)
        except StructuredOutputValidationError as exc:
            # Untrusted-analyst trust boundary: reject and fail closed. The label
            # is content-free — no raw output is surfaced.
            raise StepFailed("schema_validation_failed") from exc
        except LLMTransientError as exc:
            raise StepError("provider_transient_error") from exc
        except (LLMResponseError, LLMConfigurationError) as exc:
            raise StepFailed("provider_error") from exc
        return SelfConsistencySignal.from_samples(samples)

    def _route(self, context: EstimationContext, signal: SelfConsistencySignal) -> None:
        """Apply the calibrated decision to the sample set, or raise a step signal."""

        samples = signal.samples
        if all(sample.disposition is ParseDisposition.UNPARSEABLE for sample in samples):
            # The samples agree the input is not a log at all: terminal, with a
            # coarse fixed label (the model's ``reason`` stays untrusted text).
            raise StepFailed("unparseable_input")

        result = _representative(samples)

        # The calibrated clarify gate (FTY-159): a sample set that never parsed
        # is a direct fail-closed clarify decision (its agreement can be a
        # perfect 1.0 *about asking*, which must not read as estimate
        # confidence); otherwise the hybrid consistency score is compared
        # against the data-derived operating point. FTY-167: either way, the
        # decision is overridden when the routed reply's items all carry enough
        # real-world detail (a count, a range, a distance, steps, or a game
        # count) to estimate — a casual-but-detailed log should be estimated,
        # not asked about. A genuinely vague reply (no items, or any item
        # lacking an amount signal) still clarifies.
        conservative = signal.all_non_parsed or NL_PARSE_CLARIFY_POLICY.should_clarify(
            signal.hybrid
        )
        if conservative and not _reply_has_sufficient_detail(result.items):
            context.clarification_questions = _clarification_questions(samples)
            raise NeedsClarification("low_confidence_or_ambiguous")

        # A sample set that claims "parsed" yet routes nothing to persist is
        # treated as unparseable (fail closed) rather than silently completing
        # with no candidates.
        if not result.items:
            raise StepFailed("no_candidates")

        # Deterministic plausibility gate (FTY-156): check each *food* candidate's
        # quantity/unit against physical sanity ranges before trusting the parse.
        # The gate runs on each candidate's *effective* amount — a range midpoint
        # ("500-1000" → 750) is filled first so it is bounded by the same count
        # caps as an explicit amount rather than bypassing the gate (FTY-167).
        # A single implausible candidate makes the whole event's total
        # untrustworthy, so route the event to clarification with a targeted
        # question naming the offending item. Exercise candidates are excluded:
        # their quantities are durations (minutes/hours), not mass/volume/count,
        # so the food-portion bounds and unit vocabulary do not apply — exercise
        # plausibility/duration parsing is FTY-043's concern (exercise-burn.md).
        effective = [_effective_candidate(item) for item in result.items]

        implausible = _first_implausible([item for item, _ in effective])
        if implausible is not None:
            context.clarification_questions = [implausible]
            raise NeedsClarification("implausible_candidate")

        for item, assumption in effective:
            if assumption is not None and assumption not in context.assumptions:
                context.assumptions.append(assumption)
            draft = _to_draft(item)
            if item.type is CandidateType.FOOD:
                context.food_candidates.append(draft)
            else:
                context.exercise_candidates.append(draft)


def _representative(samples: Sequence[ParseResult]) -> ParseResult:
    """The sample whose candidates are routed when the set is trusted.

    Preference order: the most self-confident ``parsed`` sample (every parsed
    sample is an equally schema-valid parse; the verbalized score is the only
    within-set ranking the model expresses), then — for non-parsed sets that may
    still estimate via the FTY-167 detail override — the most confident sample
    that extracted items, then the first sample. ``max`` keeps the earliest of
    equally-confident samples, so the choice is deterministic for a recorded
    sample set.
    """

    parsed = [s for s in samples if s.disposition is ParseDisposition.PARSED]
    pool = parsed or [s for s in samples if s.items] or list(samples)
    return max(pool, key=lambda sample: sample.confidence)


def _effective_candidate(item: ParsedCandidate) -> tuple[ParsedCandidate, str | None]:
    """Fill a food candidate's effective amount from a range midpoint, if any.

    When a food candidate has no structured amount but ``quantity_text`` states a
    numeric range ("5-10"), the range's midpoint is filled deterministically so the
    serving math can estimate a single portion. The fill happens *before* the
    plausibility gate so the midpoint is subject to the same count caps as an
    explicit amount — a gross range ("500-1000") must not bypass FTY-156. Returns
    the effective candidate plus the content-free assumption string (numbers only —
    never raw diary text) to record if the event is accepted. FTY-167.
    """

    amount = item.amount
    if item.type is CandidateType.FOOD and (amount is None or amount <= 0):
        parsed_range = parse_range_midpoint(item.quantity_text)
        if parsed_range is not None:
            low, high, midpoint = parsed_range
            assumption = f"range_midpoint: {low:g}-{high:g} → {midpoint:g}"
            return item.model_copy(update={"amount": midpoint}), assumption
    return item, None


def _to_draft(item: ParsedCandidate) -> CandidateDraft:
    """Map a validated (effective) schema candidate to the neutral persistence draft."""

    return CandidateDraft(
        name=item.name,
        quantity_text=item.quantity_text,
        unit=item.unit,
        amount=item.amount,
        barcode=item.barcode,
        brand=item.brand,
    )


def _reply_has_sufficient_detail(items: list[ParsedCandidate]) -> bool:
    """Whether every extracted item carries enough amount detail to estimate.

    Empty ``items`` is insufficient (nothing to estimate). Otherwise each item must
    carry a detail signal for its kind — a food count/range/measure, or an exercise
    duration/distance/step/game signal — so that a single vague item in an otherwise
    detailed reply still routes the whole event to clarification (its portion is
    genuinely unknown).
    """

    if not items:
        return False
    return all(_candidate_has_detail(item) for item in items)


def _candidate_has_detail(item: ParsedCandidate) -> bool:
    """Whether one candidate carries a detail signal appropriate to its kind."""

    if item.type is CandidateType.EXERCISE:
        return has_exercise_detail(item.unit, item.amount, item.quantity_text)
    return has_food_detail(item.amount, item.quantity_text)


def _clarification_questions(samples: Sequence[ParseResult]) -> list[str]:
    """The distinct non-empty questions across the samples, or a single default.

    Every sample expresses the same event's ambiguity, so their questions are
    pooled (first occurrence wins — duplicates across samples are the common
    case) rather than taken from one arbitrary sample.
    """

    questions: list[str] = []
    for sample in samples:
        for question in sample.clarification_questions:
            cleaned = question.strip()
            if cleaned and cleaned not in questions:
                questions.append(cleaned)
    return questions or [DEFAULT_CLARIFICATION_QUESTION]


def _first_implausible(items: list[ParsedCandidate]) -> str | None:
    """Return a clarification question for the first implausible food candidate, or None.

    Checks each *food* candidate in order; returns the targeted question from the
    first failure so the user can correct the most prominent implausible entry
    first. Exercise candidates are skipped — the plausibility validator's bounds
    and unit vocabulary are food-portion specific (mass/volume/count), whereas an
    exercise quantity is a duration (minutes/hours); running it through the gate
    would falsely reject ordinary exercise durations. Returns ``None`` when all
    food candidates are plausible.
    """

    for item in items:
        if item.type is not CandidateType.FOOD:
            continue
        result = check_candidate(item)
        if not result.plausible:
            return result.clarification_question
    return None
