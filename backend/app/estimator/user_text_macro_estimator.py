"""Missing-macro estimation engine for a user-stated calorie item (FTY-280/281/314).

The macro-estimation half of the ``user_text`` evidence tier, extracted from
``user_text_step.py`` (FTY-319). :class:`UserTextResolveStep` owns validating the
stated facts and persisting the resolved item; this module owns *filling the
macros the user did not state*.

When a user states a calorie total but omits one or more macros, the
:class:`UserTextMacroEstimator` fills each missing macro honestly, from evidence,
in the fixed preference order (``evidence-retrieval.md`` → Estimating a missing
field):

1. **single-source reference lookup** — a sanitized identity-with-brand search →
   hardened searched-result fetch → schema-validated transcription →
   plausibility-gated per-100g composition (FTY-166 path, snippet-compatibility
   gated per FTY-314);
2. **comparable-reference aggregate** (FTY-281) — a brand-dropped search for
   *compatible* public references, per-page compatibility/plausibility filtering,
   Atwater-space outlier rejection, and median grams-per-kcal aggregation
   (``app.estimator.comparable_reference``);
3. **model-prior cold-pass** — N independent estimates gated on their sampling
   agreement (never a one-shot verbalized confidence);

else the macro is left **unknown** (``None``) — never a silent ``0``.

A macro is only ever *estimated* from a per-100g composition scaled to the user's
stated calorie total (grams = macro_per_100g × stated_calories / calories_per_100g),
so the estimate is consistent with the number the user gave; ``calories`` itself is
never re-estimated. Wherever an LLM participates — the comparable-page
transcription and the model-prior estimate alike — it is drawn over N independent
cold passes gated on sampling agreement; disagreeing passes leave the macro
unknown, never a re-ask.

Security: the estimator carries the fail-closed evidence gates (empty sanitized
identity, snippet compatibility, cold-pass agreement) that bound what untrusted
external text can become a stored fact. All egress flows through the injected
``search_provider`` and ``reference_fetch_fn`` (FTY-079/FTY-166); the estimator
opens no socket of its own, and no raw diary phrase / page text / snippet leaks
into assumptions, source refs, or logs.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.enums import ESTIMATE_BASIS_ASSUMPTION_PREFIX, MacroEstimateBasis
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
    cold_pass_identity,
    compatibility,
)
from app.estimator.evidence_utils import _record_source_ref
from app.estimator.food_serving import NutritionFacts
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.identity_sanitizer import sanitized_identity
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
)
from app.estimator.reference_fetch import ReferenceFetchSettings, fetch_searched_result
from app.estimator.search import SearchProvider, SearchStatus
from app.estimator.search_sanitization import sanitize_query
from app.estimator.searched_reference import (
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
    SNIPPET_ASSUMPTION,
    FetchReference,
    SearchedReferenceFacts,
    _identity_query,
    _to_per_100g,
    searched_reference_per_100g,
)
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
            per_100g, source_ref, snippet_derived = reference
            estimated = self._scale_missing(
                per_100g, calories, missing, source_ref, tier="reference_source"
            )
            if snippet_derived and estimated.values:
                # Snippet-derived reference evidence keeps its content-free
                # snippet label on the persisted assumptions (FTY-314), so a
                # macro fill backed by a search-result snippet is always
                # distinguishable from one backed by a fetched page.
                estimated = _EstimatedMacros(
                    values=estimated.values,
                    source_ref=estimated.source_ref,
                    assumptions=(*estimated.assumptions, SNIPPET_ASSUMPTION),
                )
            return estimated

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
        # Read-model estimate-basis marker (FTY-350): the reference-lookup and model-prior
        # macro-fills additionally carry the ESTIMATE_BASIS_ASSUMPTION_PREFIX marker the
        # comparable-reference tier already writes (build_missing_macro_fill), so the FTY-092
        # read-model can surface ItemSourceDTO.estimate_basis for these tiers too — the same
        # derive-don't-store mechanism, no new persisted column. ``tier`` is exactly a
        # MacroEstimateBasis value; the marker suffix is that plain enum value only —
        # content-free, never the source_ref, URL, or provider output — and it rides
        # alongside the unchanged human-readable prose assumption.
        basis_marker = f"{ESTIMATE_BASIS_ASSUMPTION_PREFIX}{MacroEstimateBasis(tier).value}"
        return _EstimatedMacros(
            values=values, source_ref=source_ref, assumptions=(basis_marker, assumption)
        )

    def _reference_composition(
        self, context: EstimationContext, candidate: CandidateDraft
    ) -> tuple[NutritionFacts, str, bool] | None:
        """Search + fetch + transcribe a public reference page's per-100g composition.

        Reuses the FTY-166 searched-result path (sanitized identity + fixed nutrition
        intent → hardened searched-result fetch → schema-validated transcription →
        plausibility-gated canonicalisation). Returns ``(per_100g_facts, source_ref,
        snippet_derived)`` for the first confident, plausible, accepted result, or
        ``None`` to fall through. A snippet-derived result (FTY-314) is additionally
        gated on product compatibility: this single-source path commits the first
        accepted result, so a snippet whose transcribed product identity does not
        name a comparable of the item (:func:`compatibility`) is rejected rather
        than filling the macros from an unrelated search result.
        """

        if not (self.search_provider.enabled and self.search_provider.available):
            return None
        if not self.reference_fetch_settings.is_available:
            return None

        # Exact reference lookup: item identity **with** its brand (so a brand-exact page
        # can win) plus the fixed nutrition intent — but the brand-inclusive identity is
        # reduced to bounded ``[a-z0-9]+`` tokens with instruction/personal-context tokens
        # stripped (:func:`sanitized_identity`) and passed through the ``sanitize_query``
        # chokepoint, exactly like the comparable tier, so prompt-like parser output in the
        # name never egresses to the provider.
        identity = sanitized_identity(_identity_query(candidate))
        if not identity:
            # Fail closed on an empty sanitized identity (FTY-281 recognizable-item /
            # sanitized-identity boundary). With no surviving item-identity token the query
            # degenerates to the broad fixed intent (``nutrition facts``) alone, and this
            # single-source path has **no** per-page compatibility gate — it would commit
            # the first plausible unrelated page as a source-backed match. Fall through to
            # the comparable / model-prior / unknown tiers instead of issuing a broad
            # source-backed lookup.
            return None
        query = sanitize_query(f"{identity} {REFERENCE_SEARCH_INTENT}")

        def _accept(found: SearchedReferenceFacts) -> bool:
            if found.facts.calories <= 0:
                return False
            if SNIPPET_ASSUMPTION not in found.assumptions:
                return True
            # FTY-314 fail-closed gate: a snippet-derived result has no fetched
            # page behind it, so its transcribed product identity must name a
            # comparable of the item — the same deterministic check the
            # comparable tier applies. A snippet whose facts name no product,
            # a conflicting food form, or no shared content term never fills
            # missing macros.
            return compatibility(candidate.name, found.product_name) is not None

        found = searched_reference_per_100g(
            provider=self.provider,
            search_provider=self.search_provider,
            fetch=self._fetch_reference,
            query=query,
            page_kind=_REFERENCE_PAGE_KIND,
            source_type=REFERENCE_SOURCE_TYPE,
            before_fetch=lambda _source_ref: _record_source_ref(context, REFERENCE_SOURCE),
            accept_result=_accept,
        )
        if found is None:
            return None
        return found.facts, found.source_ref, SNIPPET_ASSUMPTION in found.assumptions

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
        # surface — item identity + the fixed nutrition intent only, never a raw diary
        # phrase or personal context. The brand-dropped identity is reduced to its bounded
        # ``[a-z0-9]+`` identity tokens (:func:`sanitized_identity`) so punctuation and
        # structural framing a prompt injection would smuggle through the parser-derived
        # name cannot ride along, and the whole string is passed through the
        # ``sanitize_query`` chokepoint (control-char strip + length bound) before egress.
        identity = sanitized_identity(candidate.name)
        if not identity:
            # Fail closed on an empty sanitized identity, as the exact tier does: with no
            # item-identity token the brand-dropped query degenerates to the broad fixed
            # intent alone, so aggregate over pages the resolver can no longer tie to the
            # item. Fall through to the model-prior / unknown tiers instead.
            return None
        query = sanitize_query(f"{identity} {REFERENCE_SEARCH_INTENT}")
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

    def _extract_comparable(self, page_text: str) -> tuple[NutritionFacts, str] | None:
        """Cold-pass transcription of one comparable page → ``(per-100g facts, product name)``.

        FTY-281 keeps a lone over-confident transcription out of the aggregate: the page is
        transcribed over ``MACRO_ESTIMATE_NUM_SAMPLES`` passes and both halves of the
        transcription must agree before it becomes a comparable candidate — the committed
        **macro density** (the same gate the model-prior fallback uses) *and* the LLM-derived
        **product identity** that feeds the downstream compatibility check
        (:func:`cold_pass_identity`). ``None`` when too few passes canonicalise to plausible
        per-100g facts, the macro densities disagree, or the passes disagree on the product's
        food form / share no content term — so a page whose passes name conflicting forms
        cannot enter on the strength of a single compatible pass.
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
        product_name = cold_pass_identity([name for _, name in pairs])
        if product_name is None:
            return None
        return _mean_composition(compositions), product_name

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
