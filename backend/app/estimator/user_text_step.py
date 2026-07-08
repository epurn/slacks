"""User-stated nutrition resolution step (FTY-279 contract; FTY-280 implementation).

The rank-1 ``user_text`` evidence tier: when the user *states* an explicit calorie
total for a recognizable item in the log text ("Sobeys buffalo chicken lime wrap
(580 cals idk the breakdown)"), the parser extracts it into the candidate's
``stated_*`` fields (``parse-candidates.md`` v6) and this step resolves the item
**directly** from that user-provided evidence — counting the calories immediately,
``as_logged`` (never re-scaled) — instead of sending the entry back for a serving
clarification (``food-resolution.md`` → User-Stated Resolution; the no-second-
follow-up rule).

It runs **before** the USDA/OFF food step and *claims* every candidate carrying a
usable stated calorie total, removing it from ``context.food_candidates`` so the
food step only resolves the rest. ``user_text`` outranks USDA/OFF/official/
model-prior for the field(s) the user gave.

For each claimed candidate the step:

1. **Validates** the stated facts as untrusted evidence (``evidence-retrieval.md``):
   finite, non-negative, under the **as-logged abuse cap** (not the per-100g
   plausibility bound — there is no mass), and internally consistent (an Atwater
   cross-check on any co-stated macros). A negative / non-finite / absurd or
   self-contradictory claim **fails closed** to ``needs_clarification`` — never a
   committed impossible total.
2. **Records** a ``resolved`` item whose ``calories`` is the stated total, with a
   ``user_text`` evidence row (``source_ref = user_text:<content_hash>``, ``basis =
   as_logged``, ``field_provenance`` marking ``calories`` ``user_stated``). No global
   ``products`` cache row is written.
3. **Fills missing macros honestly** (:class:`UserTextMacroEstimator`, optional):
   a macro the user did not state is estimated from the item identity in the fixed
   order **single-source reference lookup → comparable-reference aggregate (FTY-281)
   → model-prior cold-pass**, recorded ``field_provenance = estimated`` with the source
   in ``assumptions``, or left **unknown/``None``** — **never** a silent ``0``. When the
   exact lookup misses, several *compatible* public reference items (brand-dropped search,
   compatibility-checked, outlier-filtered, median-aggregated —
   :mod:`app.estimator.comparable_reference`) fill the macros as **rough** evidence before
   any model prior. A stated macro is preserved exactly (``user_stated``). Wherever an LLM
   participates — the comparable-page transcription and the model-prior estimate alike —
   it is drawn over **N independent cold passes** gated on sampling agreement (never a
   one-shot verbalized confidence); disagreeing passes leave the macro unknown, never a
   re-ask.

Security: the raw diary phrase is never persisted — the evidence row stores only the
extracted, validated facts, a hash over them, and the timestamp. The LLM extracts
the stated numbers (upstream, schema-validated); no instruction embedded in the text
is executed, and trusted backend code owns every persisted number.
"""

from __future__ import annotations

import hashlib
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from app.estimator.clarify_policy import (
    BASIS_DOCUMENTED_TUNABLE,
    ClarifyPolicy,
)
from app.estimator.comparable_reference import (
    COMPARABLE_REFERENCE_SOURCE,
    ComparableAggregate,
    ComparableCandidate,
    aggregate,
    build_missing_macro_fill,
    compatibility,
)
from app.estimator.evidence_utils import _record_source_ref
from app.estimator.food_serving import NutritionFacts
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.official_step import (
    _EXTRACT_PROMPT,
    _MODEL_PRIOR_PROMPT,
    _REFERENCE_PAGE_KIND,
    EXTRACT_CONFIDENCE_THRESHOLD,
    MAX_PAGE_TEXT_CHARS,
    MAX_SOURCE_REF_LEN,
    MODEL_PRIOR_SOURCE,
    REFERENCE_SEARCH_INTENT,
    REFERENCE_SOURCE,
    REFERENCE_SOURCE_TYPE,
    FetchReference,
    _identity_query,
    _to_per_100g,
)
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    ResolvedFoodItem,
)
from app.estimator.reference_fetch import ReferenceFetchSettings, fetch_searched_result
from app.estimator.search import SearchProvider, SearchStatus
from app.llm.base import Provider
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.schemas.official_source import (
    EstimateDisposition,
    NamedFoodEstimate,
)

#: Source-system id / classification for a user-stated nutrition fact (rank 1, the
#: user-provided tier — ``evidence-retrieval.md``). Distinct from ``user_label`` so a
#: client tells a number the user *typed into a log* from one *scanned off a label*.
USER_TEXT_SOURCE = "user_text"
USER_TEXT_SOURCE_TYPE = "user_text"

#: The fact basis for a user-stated total: it is the value for the exact logged item,
#: not a per-reference-quantity fact, and is never re-scaled by the serving math.
AS_LOGGED_BASIS = "as_logged"

#: Per-field provenance values recorded in ``evidence_sources.field_provenance``.
PROVENANCE_USER_STATED = "user_stated"
PROVENANCE_ESTIMATED = "estimated"
PROVENANCE_UNKNOWN = "unknown"

#: Abuse cap on an as-logged calorie total (a single logged item). Mirrors the label
#: path's ``MAX_ENERGY_KCAL`` per-entry ceiling — **not** the per-100g plausibility
#: bound, which needs a mass the user did not give. A stated total above this is
#: absurd for one item and fails closed.
MAX_AS_LOGGED_KCAL = 10_000.0

#: Atwater energy per gram (protein/carb 4, fat 9). Used only for an internal-
#: consistency lower bound: co-stated macros imply *at least* this much energy, so an
#: implied energy grossly exceeding the stated calorie total is self-contradictory.
_KCAL_PER_G_PROTEIN = 4.0
_KCAL_PER_G_CARB = 4.0
_KCAL_PER_G_FAT = 9.0

#: How far the macro-implied Atwater energy may exceed the stated calorie total before
#: the claim is treated as self-contradictory. Generous (macros are approximate and
#: rounding/fibre/alcohol move the sum) so only a *gross* contradiction fails closed:
#: a small ratio slack plus an absolute kcal slack.
_ATWATER_MAX_RATIO = 1.3
_ATWATER_ABS_SLACK_KCAL = 25.0

#: Number of independent model-prior cold passes drawn for a missing-macro estimate,
#: mirroring the parse self-consistency sample count (FTY-158). The estimate is gated
#: on their **agreement**, never a single verbalized confidence.
MACRO_ESTIMATE_NUM_SAMPLES = 3

#: The missing-macro model-prior estimate's decision, as a documented tunable (there
#: is no labelled macro-estimate calibration set to derive an operating point from —
#: the same honesty rule the label gate follows, ``clarify_policy.py``). The signal is
#: the cold-pass sampling agreement over the committed macro density (grams per kcal,
#: which folds in the calorie density used to scale to the stated total); an agreement
#: below the operating point leaves the macro unknown rather than committing a shaky
#: invented number.
USER_TEXT_MACRO_ESTIMATE_POLICY = ClarifyPolicy(
    signal="macro_sampling_agreement",
    threshold=0.6,
    basis=BASIS_DOCUMENTED_TUNABLE,
)

#: Fixed, sanitized clarification question for a self-contradictory / implausible
#: stated fact — carries no raw diary text.
CONTRADICTORY_FACTS_QUESTION = (
    "Those numbers don't add up for that item. What did you have, and how much?"
)

#: Ordering of the three macros for the estimate/provenance helpers.
_MACRO_NAMES = ("protein_g", "carbs_g", "fat_g")

#: Minimum cold-pass samples required before agreement can be attested (a single
#: sample trivially agrees with itself and says nothing about consistency).
_MIN_SAMPLES_FOR_AGREEMENT = 2

#: The transient/response/config/validation errors one LLM pass may raise; a pass that
#: raises any of them is treated as a failed (``None``) sample rather than propagating.
_LLM_SAMPLE_ERRORS = (
    StructuredOutputValidationError,
    LLMResponseError,
    LLMConfigurationError,
    LLMTransientError,
)


def _user_text_content_hash(
    calories: float, protein_g: float | None, carbs_g: float | None, fat_g: float | None
) -> str:
    """A reproducible fingerprint of the extracted as-logged facts (no raw text).

    Fingerprints only the bounded, validated numbers (a missing macro renders as
    ``null``), so the provenance is auditable without ever retaining the raw diary
    phrase (``evidence-retrieval.md`` → Privacy and Retention).
    """

    def _fmt(value: float | None) -> str:
        return "null" if value is None else f"{value}"

    canonical = (
        f"{USER_TEXT_SOURCE}|{AS_LOGGED_BASIS}|{calories}|"
        f"{_fmt(protein_g)}|{_fmt(carbs_g)}|{_fmt(fat_g)}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _has_stated_calorie_total(candidate: CandidateDraft) -> bool:
    """Whether ``candidate`` carries a usable stated calorie total (a positive value)."""

    return candidate.stated_calories is not None and candidate.stated_calories > 0


def _validate_stated_facts(candidate: CandidateDraft) -> str | None:
    """Return a sanitized failure reason if the stated facts cannot back a number.

    Deterministic, fail-closed checks (``evidence-retrieval.md`` → Validation): every
    stated value finite and non-negative, the as-logged total under the abuse cap, and
    the co-stated macros not implying an energy that grossly exceeds the stated total
    (an Atwater cross-check). Returns ``None`` when the facts are trustworthy.
    """

    calories = candidate.stated_calories
    values = (
        calories,
        candidate.stated_protein_g,
        candidate.stated_carbs_g,
        candidate.stated_fat_g,
    )
    for value in values:
        if value is not None and (not math.isfinite(value) or value < 0):
            return "non_finite_or_negative_stated_fact"

    if calories is None or calories <= 0:
        # This step is only entered for a positive stated calorie total.
        return "no_stated_calorie_total"
    if calories > MAX_AS_LOGGED_KCAL:
        return "stated_calories_over_abuse_cap"

    implied = (
        _KCAL_PER_G_PROTEIN * (candidate.stated_protein_g or 0.0)
        + _KCAL_PER_G_CARB * (candidate.stated_carbs_g or 0.0)
        + _KCAL_PER_G_FAT * (candidate.stated_fat_g or 0.0)
    )
    if implied > calories * _ATWATER_MAX_RATIO + _ATWATER_ABS_SLACK_KCAL:
        return "stated_macros_contradict_calories"
    return None


def _round_macro(value: float) -> float:
    """Round a macro gram value to 0.1, matching the serving math precision."""

    return round(value, 1)


@dataclass(frozen=True)
class _EstimatedMacros:
    """The outcome of filling a user-stated item's missing macros.

    ``values`` maps each *estimated* macro name to its as-logged gram total;
    ``source_ref`` is the estimate's provenance (``reference_source:<url>`` or
    ``model_prior``) recorded on the evidence row's assumptions; ``assumptions`` are
    the sanitized documented reasons. A macro absent from ``values`` stays unknown.
    """

    values: dict[str, float]
    source_ref: str | None
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class UserTextMacroEstimator:
    """Fills a user-stated calorie item's *missing* macros from evidence, honestly.

    Fixed preference order (``evidence-retrieval.md`` → Estimating a missing field):
    a **source-backed reference lookup** on the sanitized item identity first, then a
    **model-prior cold-pass** (N independent samples gated on their agreement, never a
    one-shot confidence), else the macro is left **unknown**. All egress flows through
    the injected ``search_provider`` and ``reference_fetch_fn`` (FTY-079/FTY-166); the
    estimator opens no socket of its own.

    A macro is only ever *estimated* from a per-100g composition scaled to the user's
    stated calorie total (grams = macro_per_100g × stated_calories / calories_per_100g),
    so the estimate is consistent with the number the user gave; ``calories`` itself is
    never re-estimated.
    """

    provider: Provider
    search_provider: SearchProvider
    reference_fetch_settings: ReferenceFetchSettings
    reference_fetch_fn: FetchReference = fetch_searched_result

    def estimate(
        self,
        context: EstimationContext,
        candidate: CandidateDraft,
        calories: float,
        missing: tuple[str, ...],
    ) -> _EstimatedMacros:
        """Estimate the ``missing`` macros for ``candidate`` at its stated ``calories``.

        Returns an empty result (every missing macro left unknown) when no evidence
        tier produces a confident, plausible composition.
        """

        if not missing:
            return _EstimatedMacros(values={}, source_ref=None, assumptions=())

        reference = self._reference_composition(context, candidate)
        if reference is not None:
            per_100g, source_ref = reference
            return self._scale_missing(
                per_100g, calories, missing, source_ref, tier="reference_source"
            )

        comparable = self._comparable_aggregate(context, candidate)
        if comparable is not None:
            values, assumptions = build_missing_macro_fill(comparable, calories, missing)
            return _EstimatedMacros(
                values=values, source_ref=COMPARABLE_REFERENCE_SOURCE, assumptions=assumptions
            )

        cold = self._model_prior_composition(candidate)
        if cold is not None:
            return self._scale_missing(
                cold, calories, missing, MODEL_PRIOR_SOURCE, tier="model_prior"
            )

        return _EstimatedMacros(values={}, source_ref=None, assumptions=())

    def _scale_missing(
        self,
        per_100g: NutritionFacts,
        calories: float,
        missing: tuple[str, ...],
        source_ref: str,
        *,
        tier: str,
    ) -> _EstimatedMacros:
        """Scale a per-100g composition to the stated calorie total for missing macros."""

        if per_100g.calories <= 0:
            return _EstimatedMacros(values={}, source_ref=None, assumptions=())
        factor = calories / per_100g.calories
        per_100g_by_name = {
            "protein_g": per_100g.protein_g,
            "carbs_g": per_100g.carbs_g,
            "fat_g": per_100g.fat_g,
        }
        values = {name: _round_macro(per_100g_by_name[name] * factor) for name in missing}
        filled = ", ".join(missing)
        assumption = (
            f"{filled} estimated from {tier} ({source_ref}) scaled to the stated {calories:g} kcal"
        )
        return _EstimatedMacros(values=values, source_ref=source_ref, assumptions=(assumption,))

    def _reference_composition(
        self, context: EstimationContext, candidate: CandidateDraft
    ) -> tuple[NutritionFacts, str] | None:
        """Search + fetch + transcribe a public reference page's per-100g composition.

        Reuses the FTY-166 searched-result path (sanitized identity + fixed nutrition
        intent → hardened searched-result fetch → schema-validated transcription →
        plausibility-gated canonicalisation). Returns ``(per_100g_facts, source_ref)``
        for the first confident, plausible page, or ``None`` to fall through.
        """

        if not (self.search_provider.enabled and self.search_provider.available):
            return None
        if not self.reference_fetch_settings.is_available:
            return None

        query = f"{_identity_query(candidate)} {REFERENCE_SEARCH_INTENT}"
        result = self.search_provider.search(query)
        if result.status is not SearchStatus.SUCCESS:
            return None

        recorded = False
        for search_candidate in result.candidates:
            source_ref = f"{REFERENCE_SOURCE_TYPE}:{search_candidate.url}"
            if len(source_ref) > MAX_SOURCE_REF_LEN:
                continue
            if not recorded:
                _record_source_ref(context, REFERENCE_SOURCE)
                recorded = True
            text = self._fetch_reference(search_candidate.url)
            if text is None:
                continue
            # Single-source authoritative lookup: one transcription pass, plausibility-gated.
            per_100g = self._composition(self._one_estimate(self._extract_prompt(text)))
            if per_100g is None:
                continue
            return per_100g, source_ref
        return None

    def _comparable_aggregate(
        self, context: EstimationContext, candidate: CandidateDraft
    ) -> ComparableAggregate | None:
        """Search relaxed identity for compatible references and median-aggregate them.

        The FTY-281 tier between the single-source reference match and the model prior:
        when the exact (identity + brand) reference lookup missed, search the
        **brand-dropped** item identity plus the fixed nutrition intent for *comparable*
        public reference pages, transcribe each page's facts + product name, keep only
        the compatible, plausible ones (:func:`compatibility` + ``_to_per_100g``), and
        median-aggregate the survivors dropping outliers (:func:`aggregate`). Returns
        ``None`` when the tier is unavailable, nothing confident is found, too few
        compatible sources survive, or they materially disagree. All egress flows
        through the injected search + reference-fetch seams; the step opens no socket.
        """

        if not (self.search_provider.enabled and self.search_provider.available):
            return None
        if not self.reference_fetch_settings.is_available:
            return None

        # Relaxed query: drop the brand so *comparable* (not brand-exact) references
        # surface — still item identity + the fixed nutrition intent only, no raw diary
        # text or personal context (the search adapter's sanitize_query chokepoint
        # applies as ever).
        query = f"{candidate.name} {REFERENCE_SEARCH_INTENT}"
        result = self.search_provider.search(query)
        if result.status is not SearchStatus.SUCCESS:
            return None

        candidates: list[ComparableCandidate] = []
        recorded = False
        for search_candidate in result.candidates:
            source_ref = f"{REFERENCE_SOURCE_TYPE}:{search_candidate.url}"
            if len(source_ref) > MAX_SOURCE_REF_LEN:
                continue
            if not recorded:
                _record_source_ref(context, COMPARABLE_REFERENCE_SOURCE)
                recorded = True
            found = self._comparable_from_url(candidate, search_candidate.url, source_ref)
            if found is not None:
                candidates.append(found)

        return aggregate(candidates)

    def _comparable_from_url(
        self, candidate: CandidateDraft, url: str, source_ref: str
    ) -> ComparableCandidate | None:
        """Fetch + cold-pass-transcribe one reference URL into a comparable, or ``None``.

        ``None`` when the page fails to fetch, its cold-pass transcription does not agree
        (:meth:`_extract_comparable`), its item is **not a comparable** (wrong food form
        or no ingredient/flavor overlap — :func:`compatibility`), or its facts are
        implausible / not canonicalisable to a positive-calorie per-100g basis.
        """

        text = self._fetch_reference(url)
        if text is None:
            return None
        extracted = self._extract_comparable(text)
        if extracted is None:
            return None
        per_100g, product_name = extracted
        match = compatibility(candidate.name, product_name)
        if match is None:
            return None
        return ComparableCandidate(
            facts=per_100g,
            source_ref=source_ref,
            shared_terms=match.shared_terms,
            form=match.form,
        )

    def _model_prior_composition(self, candidate: CandidateDraft) -> NutritionFacts | None:
        """Estimate a per-100g composition from model prior via N cold passes.

        Gates ``MACRO_ESTIMATE_NUM_SAMPLES`` independent estimates on their **sampling
        agreement** over the committed macro density (grams per kcal, so calorie density
        is part of the gate — ``USER_TEXT_MACRO_ESTIMATE_POLICY``) and returns their mean
        only when the passes agree; a single over-confident sample never finalizes a
        fabricated number.
        """

        prompt = _MODEL_PRIOR_PROMPT.format(identity=_identity_query(candidate))
        samples = self._draw_estimates(prompt, "user-text-macro")
        # A failed/unresolved/implausible pass is disagreement: fail closed below.
        usable = [c for c in (self._composition(s) for s in samples) if c is not None]
        if len(usable) < MACRO_ESTIMATE_NUM_SAMPLES:
            return None
        if USER_TEXT_MACRO_ESTIMATE_POLICY.should_clarify(_macro_agreement(usable)):
            return None
        return _mean_composition(usable)

    def _one_estimate(self, prompt: str) -> NamedFoodEstimate | None:
        """One LLM estimate for ``prompt``; a transient/schema-invalid pass is ``None``."""

        try:
            return self.provider.structured_completion(prompt, NamedFoodEstimate)
        except _LLM_SAMPLE_ERRORS:
            return None

    def _draw_estimates(
        self, prompt: str, thread_prefix: str
    ) -> tuple[NamedFoodEstimate | None, ...]:
        """Draw ``MACRO_ESTIMATE_NUM_SAMPLES`` independent estimates concurrently — the
        shared cold-pass sampler behind both LLM steps in this tier (model-prior fallback
        and comparable-page transcription); the caller gates on the survivors' agreement.
        """

        with ThreadPoolExecutor(
            max_workers=MACRO_ESTIMATE_NUM_SAMPLES, thread_name_prefix=thread_prefix
        ) as pool:
            futures = [
                pool.submit(self._one_estimate, prompt) for _ in range(MACRO_ESTIMATE_NUM_SAMPLES)
            ]
            return tuple(future.result() for future in futures)

    def _extract_comparable(self, page_text: str) -> tuple[NutritionFacts, str | None] | None:
        """Cold-pass transcription of one comparable page → ``(per-100g facts, product name)``.

        FTY-281 keeps a lone over-confident transcription out of the aggregate: the page is
        transcribed over ``MACRO_ESTIMATE_NUM_SAMPLES`` passes and gated on the same
        committed-macro-density agreement the model-prior fallback uses — ``None`` when too
        few canonicalise to plausible per-100g facts or they disagree.
        """

        samples = self._draw_estimates(self._extract_prompt(page_text), "user-text-extract")
        pairs: list[tuple[NutritionFacts, str | None]] = []
        for sample in samples:
            facts = self._composition(sample)
            if facts is not None and sample is not None and sample.facts is not None:
                pairs.append((facts, sample.facts.product_name))
        if len(pairs) < MACRO_ESTIMATE_NUM_SAMPLES:
            return None
        compositions = [facts for facts, _ in pairs]
        if USER_TEXT_MACRO_ESTIMATE_POLICY.should_clarify(_macro_agreement(compositions)):
            return None
        return _mean_composition(compositions), pairs[0][1]

    @staticmethod
    def _composition(estimate: NamedFoodEstimate | None) -> NutritionFacts | None:
        """Canonicalise one resolved LLM estimate/transcription to plausible per-100g facts."""

        if estimate is None or estimate.disposition is not EstimateDisposition.RESOLVED:
            return None
        if estimate.facts is None or estimate.confidence < EXTRACT_CONFIDENCE_THRESHOLD:
            return None
        canonical = _to_per_100g(estimate.facts)
        if canonical is None:
            return None
        per_100g, _serving_g = canonical
        if per_100g.calories <= 0:
            return None
        return per_100g

    def _fetch_reference(self, url: str) -> str | None:
        try:
            return self.reference_fetch_fn(url, self.reference_fetch_settings)
        except (FetchPolicyError, FetchTransientError, FetchResponseError):
            return None

    @staticmethod
    def _extract_prompt(page_text: str) -> str:
        return _EXTRACT_PROMPT.format(
            page_kind=_REFERENCE_PAGE_KIND, page_text=page_text[:MAX_PAGE_TEXT_CHARS]
        )


def _macro_agreement(compositions: list[NutritionFacts]) -> float:
    """Mean pairwise agreement of the *committed* macro density, in [0, 1].

    For each macro the pairwise agreement is the ``min/max`` ratio of its grams
    **per kcal** (1.0 when equal, both-zero counts as full agreement); the score is
    the mean over the three macros and all sample pairs. Comparing grams-per-kcal
    (not raw per-100g grams) folds in the calorie density that ``_scale_missing``
    uses — two samples that agree on the macro mix but disagree on caloric density
    scale to materially different committed grams, so they must not read as
    agreement. A composition whose samples diverge scores low and the estimate
    fails closed.
    """

    if len(compositions) < _MIN_SAMPLES_FOR_AGREEMENT:
        return 1.0
    pair_scores = [
        _composition_pair_agreement(compositions[i], compositions[j])
        for i in range(len(compositions))
        for j in range(i + 1, len(compositions))
    ]
    return sum(pair_scores) / len(pair_scores)


def _composition_pair_agreement(a: NutritionFacts, b: NutritionFacts) -> float:
    """Mean per-macro ``min/max`` ratio of grams-per-kcal between two compositions.

    The committed gram total for a macro is ``macro_per_100g × stated_calories /
    calories_per_100g``, so the value actually persisted depends on the macro's grams
    *per kcal* (the shared stated-calorie factor cancels from the ratio), not on the
    raw per-100g grams. Comparing that per-kcal density makes the agreement reflect
    the calorie density: samples that would scale to materially different grams score
    low even when their raw macro grams match. ``_composition`` guarantees each
    composition's ``calories > 0``, so the division is safe.
    """

    ratios = [
        _ratio(_per_kcal(a, name), _per_kcal(b, name)) for name in ("protein_g", "carbs_g", "fat_g")
    ]
    return sum(ratios) / len(ratios)


def _per_kcal(facts: NutritionFacts, name: str) -> float:
    """Grams of the named macro per kcal — the density that survives calorie scaling."""

    grams: float = getattr(facts, name)
    return grams / facts.calories


def _ratio(x: float, y: float) -> float:
    """``min/max`` ratio in [0, 1]; both-zero is full agreement, one-zero is none."""

    if x == y:
        return 1.0
    low, high = sorted((x, y))
    if high <= 0:
        return 1.0
    if low < 0:  # pragma: no cover - canonicalised facts are non-negative
        return 0.0
    return low / high


def _mean_composition(compositions: list[NutritionFacts]) -> NutritionFacts:
    """The element-wise mean of N per-100g compositions."""

    n = float(len(compositions))
    return NutritionFacts(
        calories=sum(f.calories for f in compositions) / n,
        protein_g=sum(f.protein_g for f in compositions) / n,
        carbs_g=sum(f.carbs_g for f in compositions) / n,
        fat_g=sum(f.fat_g for f in compositions) / n,
    )


@dataclass(frozen=True)
class UserTextResolveStep:
    """Resolve user-stated calorie candidates from the rank-1 ``user_text`` tier.

    ``macro_estimator`` is optional: without it, a user-stated item's missing macros
    are simply left unknown (``None``) — the item still resolves and its calories still
    count. The worker wires the full estimator (search + reference fetch + provider) so
    a missing macro is filled from evidence before falling back to unknown.
    """

    macro_estimator: UserTextMacroEstimator | None = None
    name: str = "user_text_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)

        claimed = [c for c in context.food_candidates if _has_stated_calorie_total(c)]
        if not claimed:
            context.record_step(self.name, "skipped")
            return

        # Claim the stated-calorie candidates so the USDA/OFF food step only resolves
        # the rest; ``user_text`` outranks those sources for the stated field(s).
        context.food_candidates = [
            c for c in context.food_candidates if not _has_stated_calorie_total(c)
        ]

        for candidate in claimed:
            context.resolved_food_items.append(self._resolve(context, candidate))

        context.record_step(self.name, "ok")

    def _resolve(self, context: EstimationContext, candidate: CandidateDraft) -> ResolvedFoodItem:
        """Validate + resolve one user-stated candidate, or fail closed to clarify."""

        reason = _validate_stated_facts(candidate)
        if reason is not None:
            context.clarification_questions = [
                ClarificationDraft(text=CONTRADICTORY_FACTS_QUESTION)
            ]
            raise NeedsClarification(reason)

        _record_source_ref(context, USER_TEXT_SOURCE)
        # ``_validate_stated_facts`` has guaranteed a positive, finite calorie total.
        calories = cast(float, candidate.stated_calories)

        stated = {
            "protein_g": candidate.stated_protein_g,
            "carbs_g": candidate.stated_carbs_g,
            "fat_g": candidate.stated_fat_g,
        }
        missing = tuple(name for name, value in stated.items() if value is None)

        estimated = _EstimatedMacros(values={}, source_ref=None, assumptions=())
        if missing and self.macro_estimator is not None:
            estimated = self.macro_estimator.estimate(context, candidate, calories, missing)

        macros: dict[str, float | None] = {}
        provenance: dict[str, str] = {"calories": PROVENANCE_USER_STATED}
        for name in _MACRO_NAMES:
            if stated[name] is not None:
                macros[name] = stated[name]
                provenance[name] = PROVENANCE_USER_STATED
            elif name in estimated.values:
                macros[name] = estimated.values[name]
                provenance[name] = PROVENANCE_ESTIMATED
            else:
                macros[name] = None
                provenance[name] = PROVENANCE_UNKNOWN

        assumptions = tuple(estimated.assumptions)
        for assumption in assumptions:
            if assumption not in context.assumptions:
                context.assumptions.append(assumption)

        content_hash = _user_text_content_hash(
            calories, macros["protein_g"], macros["carbs_g"], macros["fat_g"]
        )
        return ResolvedFoodItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            grams=None,
            calories=calories,
            protein_g=macros["protein_g"],
            carbs_g=macros["carbs_g"],
            fat_g=macros["fat_g"],
            product_id=None,
            source_type=USER_TEXT_SOURCE_TYPE,
            source_ref=f"{USER_TEXT_SOURCE}:{content_hash}",
            content_hash=content_hash,
            fetched_at=datetime.now(UTC),
            calories_per_100g=calories,
            protein_per_100g=macros["protein_g"],
            carbs_per_100g=macros["carbs_g"],
            fat_per_100g=macros["fat_g"],
            assumptions=assumptions,
            basis=AS_LOGGED_BASIS,
            field_provenance=provenance,
        )
