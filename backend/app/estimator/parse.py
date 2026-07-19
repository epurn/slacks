"""The structured NL parse step (FTY-042; calibrated clarify gate FTY-159).

This is the first *real* estimation pipeline step. Since FTY-325 it delegates
interpretation to the :class:`~app.estimator.interpretation.InterpretationSession`:
the session draws the N schema-validated parse samples (the FTY-158
self-consistency sampler — parallel, with a unanimous-first-window early stop so
easy inputs stay cheap), forms the run's initial item *hypothesis* from them —
re-interpreting once, budget-capped, when the samples structurally disagree on
item count/identity/brand instead of freezing a degenerate aggregate — and is
carried on the context for later steps (FTY-326). This step then routes on the
session's hypothesis plus the calibrated consistency signal:

- **parsed, calibrated-confident** → record food/exercise candidates onto the
  context; the worker persists them ``unresolved`` (no calories — FTY-043/044
  cost them).
- **needs clarification** (empty/no recognizable identity, deterministic safety
  gate, or stricter operator mode asks) → raise
  :class:`~app.estimator.pipeline.NeedsClarification`; the worker persists the
  questions and moves the event to ``needs_clarification``.
- **unparseable / empty / garbage** (unanimously) → raise
  :class:`~app.estimator.pipeline.StepFailed`; the event fails closed with a
  sanitized reason and *no* candidates are persisted.

The default operator mode is FTY-298/FTY-300 **estimate_first**: provider-raised
clarification and a low FTY-159 hybrid score are advisory when a validated reply
contains recognizable candidate identity, so the routed items continue to
deterministic safety gates and downstream rough resolution. ``balanced`` keeps
the calibrated operating point without re-asking for already-stated details, and
``strict`` keeps old-style abstention. The deterministic gates are unchanged:
the FTY-156 plausibility validator and FTY-279 stated-nutrition stability check
still run before any candidate is trusted. Under FTY-325 those gates are
*validators over the session's hypothesis*: their fail-closed authority is
unchanged, and they perform no interpretation of their own — a hypothesis they
reject routes to clarification or failure, never to a silently patched item.

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

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.enums import CandidateType
from app.estimator.detail_signals import (
    has_food_detail,
    has_stated_nutrition,
    parse_leading_count,
    parse_range_midpoint,
)
from app.estimator.event_images import (
    IMAGE_EVIDENCE_UNAVAILABLE_ASSUMPTION,
    PHOTO_ONLY_MARKER_TEXT,
    PHOTO_WITHOUT_VISION_QUESTION,
)
from app.estimator.exercise import has_exercise_detail
from app.estimator.interpretation import InterpretationSession, representative_sample
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.parse_prompt import build_parse_prompt
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    StepFailed,
)
from app.estimator.plausibility import check_candidate
from app.estimator.self_consistency import SelfConsistencySignal
from app.llm.base import Provider
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

#: Retired generic fallback question. The parse step no longer silently persists
#: this for low-quality provider clarification output; it is kept as a sentinel
#: so tests and quality checks can reject accidental fallback regressions.
DEFAULT_CLARIFICATION_QUESTION = "Could you clarify what you logged and how much?"

_MIN_CLARIFICATION_OPTIONS = 2
_MAX_CLARIFICATION_OPTIONS = 5
_FOOD_AMOUNT_OPTIONS = ["1 serving", "2 servings", "3 servings"]
_FOOD_COUNT_OPTIONS = ["1", "2", "3"]
_CUP_AMOUNT_OPTIONS = ["1/2 cup", "1 cup", "2 cups"]
_SPREAD_AMOUNT_OPTIONS = ["1 tsp", "1 tbsp", "2 tbsp"]
_FOOD_UNIT_OPTIONS = ["grams", "cups", "servings"]
_EXERCISE_DURATION_OPTIONS = ["15 minutes", "30 minutes", "60 minutes"]
_CUP_OPTION_FOODS = {
    "cereal",
    "chili",
    "curry",
    "ice cream",
    "oatmeal",
    "pasta",
    "rice",
    "soup",
}
_SPREAD_OPTION_FOODS = {
    "butter",
    "cream cheese",
    "hummus",
    "jam",
    "jelly",
    "margarine",
    "nutella",
    "peanut butter",
}
_GENERIC_QUESTIONS = {
    "can you clarify",
    "could you clarify",
    "could you clarify what you logged and how much",
    "how much was it",
    "we need a detail to count this entry",
}
_GENERIC_QUESTION_PATTERNS = (
    re.compile(r"^(?:how much|what amount) did you (?:have|eat|drink|consume)$"),
    re.compile(r"^what did you (?:have|eat|drink|consume)$"),
    re.compile(r"^what was (?:it|that|this)$"),
    re.compile(r"^(?:what|which) (?:kind|type|brand|flavor|size) did you (?:have|mean)$"),
)

#: Minimum ``min/max`` ratio between two samples' stated calorie totals for the *same*
#: item before the extraction is trusted (FTY-279/FTY-280). A calorie total the user
#: typed should reproduce near-exactly across parse samples; a materially divergent
#: total — or a total a strict majority of the samples that recognised the item failed
#: to extract — is unstable extraction and must not be persisted as rank-1 ``user_text``
#: evidence. Such an item fails closed to a targeted calorie clarification rather than
#: committing one arbitrarily-chosen total. Documented tunable: a stated number, not an
#: estimate, so the bar is tight while still tolerating rounding ("about 580" → 580/600).
_STATED_CALORIE_STABILITY_RATIO = 0.8

#: Quick-pick suggestions for a backend-routed stated-calorie clarification (the answer
#: endpoint always accepts free text; these are display-only anchors).
_CALORIE_AMOUNT_OPTIONS = ["Under 300", "300–600", "Over 600"]


@dataclass(frozen=True)
class ParseStep:
    """Parse a log event's text into schema-validated candidates via the provider."""

    provider: Provider
    policy: ParsePolicySettings = field(default_factory=ParsePolicySettings)
    name: str = "parse"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        # Record the configured provider selector and model string so an
        # estimator audit can tell exactly which backend produced this run
        # (first-party vs. OpenAI-compatible/OpenRouter — FTY-255). Both are
        # operator configuration, never secrets.
        context.provider = self.provider.name
        context.model = self.provider.model
        context.schema_version = PARSE_SCHEMA_VERSION

        raw = context.raw_text.strip()
        if not raw:
            # Empty/whitespace input is deterministically unprocessable; do not
            # spend an LLM call on it.
            raise StepFailed("empty_input")

        if context.image_evidence_degraded_reason is not None:
            self._degrade_image_surface(context, raw)

        # The session owns interpretation for the run's lifetime (FTY-325): it
        # draws the sample set, forms the initial hypothesis, re-interprets on
        # structural sample disagreement, and stays on the context so later
        # steps (FTY-326) can consult it. Provider failures surface from it
        # with the same step-signal mapping as before. The event's image
        # evidence surfaces (FTY-376) ride every interpretation call.
        session = InterpretationSession(
            self.provider,
            raw,
            policy=self.policy,
            answered=context.answered_clarifications,
            images=[event_image.image for event_image in context.images],
            step_name=self.name,
        )
        context.interpretation_session = session
        signal = session.interpret_initial(context)
        self._route(context, session, signal)
        context.record_step(self.name, "ok")

    @staticmethod
    def _degrade_image_surface(context: EstimationContext, raw: str) -> None:
        """Degrade honestly when the event has images a non-vision model can't read.

        The estimate-first / never-reject clause for a configuration limit
        (``estimation-jobs.md`` v6): with a usable text surface the run simply
        proceeds text-only, recording a content-free assumption so the estimate
        is honestly labelled as missing its image evidence. An image-only event
        (the fixed photo-marker ``raw_text``, no usable text surface) routes to
        a clarifying question — never a terminal failure — with no provider
        call spent on the bare marker.
        """

        if raw == PHOTO_ONLY_MARKER_TEXT:
            context.clarification_questions = [
                ClarificationDraft(text=PHOTO_WITHOUT_VISION_QUESTION)
            ]
            raise NeedsClarification("photo_without_vision")
        if IMAGE_EVIDENCE_UNAVAILABLE_ASSUMPTION not in context.assumptions:
            context.assumptions.append(IMAGE_EVIDENCE_UNAVAILABLE_ASSUMPTION)

    def _route(
        self,
        context: EstimationContext,
        session: InterpretationSession,
        signal: SelfConsistencySignal,
    ) -> None:
        """Apply the calibrated decision to the session's hypothesis, or raise."""

        samples = signal.samples
        if all(sample.disposition is ParseDisposition.UNPARSEABLE for sample in samples):
            # Widened bar (FTY-370/FTY-371): terminal ``unparseable_input`` fires only
            # when the samples *unanimously* judge the input genuinely not
            # food/exercise/consumable at all (e.g. "asdf", "how's the weather"). An
            # informal/homemade/compositional/borderline-consumable description is
            # recognized as food (the widened parse prompt), so a mixed set — even one
            # ``unparseable`` sample beside recognized ones — never reaches here and
            # routes to an estimate or a clarifying question below. The fixed label stays
            # coarse; the model's ``reason`` remains untrusted text.
            raise StepFailed("unparseable_input")

        result = session.result

        # The calibrated gate still identifies conservative sample sets, but the
        # active operator mode decides what that means. In default estimate_first
        # mode, provider questions and low hybrid scores are advisory when the
        # validated reply has recognizable candidates: the event continues to the
        # deterministic safety gates and downstream rough resolution. Balanced keeps
        # the calibrated threshold except for details the user already stated, while
        # strict keeps old-style abstention.
        conservative = signal.all_non_parsed or self.policy.should_clarify(signal.hybrid)
        if conservative:
            result = _conservative_result_or_raise(
                self.policy.mode,
                context,
                session,
                signal,
                default=result,
            )
            # Routing may have settled on a different validated sample than the
            # session's pick; the session stays the hypothesis owner.
            session.adopt_result(context, result)

        # A sample set that claims "parsed" yet routes nothing to persist is
        # treated as unparseable (fail closed) rather than silently completing
        # with no candidates.
        if not result.items:
            raise StepFailed("no_candidates")

        if not _all_candidates_have_recognizable_identity(result.items):
            questions = _clarification_questions(samples)
            context.clarification_questions = questions
            session.note_pending_questions(context, questions, outcome="deterministic_gate_failed")
            raise NeedsClarification("missing_identity")

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
            session.note_pending_questions(
                context, [implausible], outcome="deterministic_gate_failed"
            )
            raise NeedsClarification("implausible_candidate")

        # User-stated nutrition stability gate (FTY-279/FTY-280): a stated calorie
        # total becomes rank-1 ``user_text`` evidence, so it must not be persisted
        # when the parse samples materially disagree on it (a contradictory duplicate
        # total, or a majority of samples not extracting it at all). The verbalized/
        # detail-override routing can otherwise let one arbitrary total through even
        # when the samples conflict — this deterministic check fails such an item
        # closed to a targeted calorie question instead of trusting a shaky number.
        unstable = _first_unstable_stated_item(signal.samples, result.items)
        if unstable is not None:
            question = ClarificationDraft(
                text=f"How many calories were in the {unstable.name}?",
                options=list(_CALORIE_AMOUNT_OPTIONS),
            )
            context.clarification_questions = [question]
            session.note_pending_questions(context, [question], outcome="deterministic_gate_failed")
            raise NeedsClarification("unstable_stated_nutrition")

        # Write the deterministically-completed amounts (range midpoint / bare
        # count) back into the session hypothesis so the resolver-facing draft
        # (interpretation_tools.current_food_candidate reads session.result) carries
        # the recovered count/portion instead of the frozen amountless hypothesis.
        session.apply_effective_items([item for item, _ in effective])

        for item, assumption in effective:
            if assumption is not None and assumption not in context.assumptions:
                context.assumptions.append(assumption)
            draft = _to_draft(item)
            if item.type is CandidateType.FOOD:
                context.food_candidates.append(draft)
            else:
                context.exercise_candidates.append(draft)


def _conservative_result_or_raise(
    mode: str,
    context: EstimationContext,
    session: InterpretationSession,
    signal: SelfConsistencySignal,
    *,
    default: ParseResult,
) -> ParseResult:
    policy_result = _policy_allowed_result(mode, signal.samples, default=default)
    if policy_result is not None:
        return policy_result
    fallback_items = (
        default.items
        if not signal.all_non_parsed and _all_candidates_have_recognizable_identity(default.items)
        else ()
    )
    questions = _clarification_questions(
        signal.samples,
        fallback_items=fallback_items,
        prefer_backend_missing_detail=mode == "balanced",
    )
    context.clarification_questions = questions
    session.note_pending_questions(context, questions, outcome="clarification_needed")
    raise NeedsClarification("low_confidence_or_ambiguous")


def _policy_allowed_result(
    mode: str, samples: Sequence[ParseResult], *, default: ParseResult
) -> ParseResult | None:
    """Pick the sample to route when conservative policy still permits estimating."""

    if _policy_allows_estimate(mode, default.items):
        return default
    candidates = [sample for sample in samples if _policy_allows_estimate(mode, sample.items)]
    if not candidates:
        return None
    return representative_sample(candidates)


def _effective_candidate(item: ParsedCandidate) -> tuple[ParsedCandidate, str | None]:
    """Fill a food candidate's effective amount from a range midpoint or bare count.

    When a food candidate has no structured amount but ``quantity_text`` states a
    numeric range ("5-10"), the range's midpoint is filled deterministically so the
    serving math can estimate a single portion (FTY-167). When it instead states a
    bare count the model stranded in the phrase ("(i had 4)", "2 large"), that count
    is lifted into ``amount`` (FTY-362) so a supplied count reaches the count /
    common-portion / model-prior scaling rather than being silently dropped and
    re-asked as a quantity question. Both fills happen *before* the plausibility
    gate so the recovered amount is subject to the same count caps as an explicit
    amount — a gross range ("500-1000") must not bypass FTY-156. A measured
    quantity ("100 g", "1 tbsp") is owned by the serving math and is never
    recovered as a count. Returns the effective candidate plus the content-free
    assumption string (numbers only — never raw diary text) to record if the event
    is accepted.
    """

    amount = item.amount
    if item.type is CandidateType.FOOD and (amount is None or amount <= 0):
        parsed_range = parse_range_midpoint(item.quantity_text)
        if parsed_range is not None:
            low, high, midpoint = parsed_range
            assumption = f"range_midpoint: {low:g}-{high:g} → {midpoint:g}"
            return item.model_copy(update={"amount": midpoint}), assumption
        count = parse_leading_count(item.quantity_text)
        if count is not None:
            assumption = f"stated_count: {count:g}"
            return item.model_copy(update={"amount": count}), assumption
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
        stated_calories=item.stated_calories,
        stated_protein_g=item.stated_protein_g,
        stated_carbs_g=item.stated_carbs_g,
        stated_fat_g=item.stated_fat_g,
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


def _policy_allows_estimate(mode: str, items: list[ParsedCandidate]) -> bool:
    """Whether the active policy lets a conservative sample set estimate."""

    if mode == "estimate_first":
        return _has_recognizable_candidates(items)
    if mode == "balanced":
        return _reply_has_sufficient_detail(items)
    return False


_GENERIC_IDENTITY_NAMES = frozenset(
    {
        "activity",
        "drink",
        "exercise",
        "food",
        "meal",
        "sport",
        "sports",
        "something",
        "stuff",
        "thing",
        "workout",
    }
)


def _has_recognizable_candidates(items: Sequence[ParsedCandidate]) -> bool:
    """Whether the validated reply contains a concrete food/exercise identity."""

    return any(_is_recognizable_identity(item.name) for item in items)


def _all_candidates_have_recognizable_identity(items: Sequence[ParsedCandidate]) -> bool:
    """Whether every extracted item names a concrete food/exercise identity."""

    return bool(items) and all(_is_recognizable_identity(item.name) for item in items)


def _is_recognizable_identity(name: str) -> bool:
    key = " ".join(name.casefold().split())
    return bool(key) and key not in _GENERIC_IDENTITY_NAMES


def _candidate_has_detail(item: ParsedCandidate) -> bool:
    """Whether one candidate carries a detail signal appropriate to its kind."""

    if item.type is CandidateType.EXERCISE:
        return has_exercise_detail(item.unit, item.amount, item.quantity_text)
    return has_food_detail(item.amount, item.quantity_text, item.unit) or has_stated_nutrition(
        item.stated_calories,
        item.stated_protein_g,
        item.stated_carbs_g,
        item.stated_fat_g,
    )


def _clarification_questions(
    samples: Sequence[ParseResult],
    *,
    fallback_items: Sequence[ParsedCandidate] = (),
    prefer_backend_missing_detail: bool = False,
) -> list[ClarificationDraft]:
    """Return distinct high-quality clarification questions across samples.

    Every sample expresses the same event's ambiguity, so their questions are
    pooled (first occurrence wins — duplicates across samples are the common
    case) rather than taken from one arbitrary sample. FTY-172 makes a provider
    clarification with a missing/generic question or fewer than two options a
    low-quality structured output: fail closed instead of persisting a generic
    fallback the user cannot act on. A low-confidence ``parsed`` result without
    provider questions is a backend-routed clarification, not provider-raised
    clarification output, so it gets a deterministic targeted question derived
    from the first item that lacks a detail signal. In balanced parsed-item
    clarifications with both stated and missing details, prefer that deterministic
    missing-detail question over provider text so the sheet cannot re-ask a detail
    the user already supplied.
    """

    if prefer_backend_missing_detail and _has_stated_and_missing_detail(fallback_items):
        return [_backend_clarification_question(fallback_items, require_recognizable=True)]

    questions: list[ClarificationDraft] = []
    seen: set[str] = set()
    for sample in samples:
        for question in sample.clarification_questions:
            text = question.text.strip()
            options = _clean_options(question.options)
            _validate_provider_clarification(text, options)
            key = _normalise_question(text)
            if key not in seen:
                seen.add(key)
                questions.append(ClarificationDraft(text=text, options=options))
    if not questions:
        if fallback_items:
            return [_backend_clarification_question(fallback_items)]
        raise StepFailed("clarification_quality_failed")
    return questions


def _has_stated_and_missing_detail(items: Sequence[ParsedCandidate]) -> bool:
    """Whether a mixed parsed reply has a concrete missing detail to ask for."""

    return any(_candidate_has_detail(item) for item in items) and any(
        not _candidate_has_detail(item) and _is_recognizable_identity(item.name) for item in items
    )


def _backend_clarification_question(
    items: Sequence[ParsedCandidate], *, require_recognizable: bool = False
) -> ClarificationDraft:
    """Build a bounded question for backend-routed low-confidence parses.

    The item name comes from the schema-validated parse reply (bounded data, not
    raw log text). The options are fixed short suggestions; the answer endpoint
    still accepts arbitrary free text.
    """

    item = next(
        (
            candidate
            for candidate in items
            if not _candidate_has_detail(candidate)
            and (not require_recognizable or _is_recognizable_identity(candidate.name))
        ),
        None,
    )
    if item is None:
        raise StepFailed("clarification_quality_failed")
    if item.type is CandidateType.EXERCISE:
        return ClarificationDraft(
            text=f"How long did you do {item.name}?",
            options=list(_EXERCISE_DURATION_OPTIONS),
        )
    return ClarificationDraft(
        text=f"How much {item.name} did you have?",
        options=_backend_food_options(item),
    )


def _backend_food_options(item: ParsedCandidate) -> list[str]:
    """Return quick-pick options for backend-routed food amount questions."""

    unit = (item.unit or "").casefold()
    name = item.name.casefold()
    if unit in {"cup", "cups"} or any(food in name for food in _CUP_OPTION_FOODS):
        return list(_CUP_AMOUNT_OPTIONS)
    if unit in {"tsp", "tbsp", "teaspoon", "teaspoons", "tablespoon", "tablespoons"} or any(
        food in name for food in _SPREAD_OPTION_FOODS
    ):
        return list(_SPREAD_AMOUNT_OPTIONS)
    return list(_FOOD_AMOUNT_OPTIONS)


def _validate_provider_clarification(text: str, options: Sequence[str]) -> None:
    """Fail closed on clarification output the sheet cannot use directly."""

    if not text or _is_generic_clarification_question(text):
        raise StepFailed("clarification_quality_failed")
    if not _MIN_CLARIFICATION_OPTIONS <= len(options) <= _MAX_CLARIFICATION_OPTIONS:
        raise StepFailed("clarification_quality_failed")


def _is_generic_clarification_question(text: str) -> bool:
    """Whether a provider question lacks a concrete missing-detail anchor."""

    key = _normalise_question(text).strip(" ?.!:")
    if key in _GENERIC_QUESTIONS:
        return True
    return any(pattern.fullmatch(key) is not None for pattern in _GENERIC_QUESTION_PATTERNS)


def _clean_options(options: Sequence[str]) -> list[str]:
    """Trim and deduplicate display options while preserving model order."""

    cleaned: list[str] = []
    seen: set[str] = set()
    for option in options:
        value = option.strip()
        key = value.casefold()
        if key and key not in seen:
            seen.add(key)
            cleaned.append(value)
    return cleaned


def _normalise_question(text: str) -> str:
    """Casefold and collapse spacing for generic-question checks and dedupe."""

    return " ".join(text.casefold().split())


def _first_implausible(items: list[ParsedCandidate]) -> ClarificationDraft | None:
    """Return a clarification draft for the first implausible food candidate, if any.

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
            if result.clarification_question is None:
                raise StepFailed("clarification_quality_failed")
            return ClarificationDraft(
                text=result.clarification_question,
                options=_implausible_candidate_options(item, result.reason),
            )
    return None


def _first_unstable_stated_item(
    samples: Sequence[ParseResult], items: Sequence[ParsedCandidate]
) -> ParsedCandidate | None:
    """Return the first routed food item whose stated calorie total is unstable.

    Only items carrying a positive stated calorie total are checked (the field that
    grants the rank-1 ``user_text`` tier); everything else is skipped. Returns the
    first item whose total is not stable across ``samples`` (see
    :func:`_stated_calories_are_stable`), or ``None`` when every stated total is
    trustworthy.
    """

    for item in items:
        if item.type is not CandidateType.FOOD:
            continue
        if item.stated_calories is None or item.stated_calories <= 0:
            continue
        if not _stated_calories_are_stable(samples, item):
            return item
    return None


def _stated_calories_are_stable(samples: Sequence[ParseResult], item: ParsedCandidate) -> bool:
    """Whether ``item``'s user-stated calorie total is stable across the parse samples.

    Gathers the stated calorie totals every sample extracted for the *same* item
    (matched on kind + normalised name). The extraction is unstable — and the total
    must not be trusted as persisted evidence — when a strict majority of the samples
    that recognised the item failed to extract a calorie total (so the model mostly did
    not see a stated total), or when two extracted totals diverge by more than
    :data:`_STATED_CALORIE_STABILITY_RATIO`. Returns ``True`` when no sample stated a
    positive total (nothing to gate).
    """

    key = _stated_item_key(item)
    totals = [
        candidate.stated_calories
        for sample in samples
        for candidate in sample.items
        if _stated_item_key(candidate) == key
    ]
    present = [total for total in totals if total is not None and total > 0]
    if not present:
        return True
    if len(present) * 2 <= len(totals):
        return False
    low, high = min(present), max(present)
    return high <= 0 or low / high >= _STATED_CALORIE_STABILITY_RATIO


def _stated_item_key(item: ParsedCandidate) -> tuple[str, str]:
    """Match key for a candidate: its kind plus casefolded, whitespace-collapsed name."""

    return (item.type.value, " ".join(item.name.casefold().split()))


def _implausible_candidate_options(item: ParsedCandidate, reason: str | None) -> list[str]:
    """Return quick-pick options for deterministic parse plausibility questions."""

    if reason == "unknown_unit":
        return list(_FOOD_UNIT_OPTIONS)
    if reason == "implausible_count":
        return list(_FOOD_COUNT_OPTIONS)
    return _backend_food_options(item)
