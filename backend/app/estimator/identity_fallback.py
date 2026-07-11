"""Estimator fallback for a barcode proposal from an item's identity (FTY-308).

The production :class:`~app.estimator.barcode_proposal.IdentityFallbackSource`: when a
barcode has no usable exact Open Food Facts match, the item's sanitized identity is
estimated through the *existing* evidence fallback tiers, in the contract order
(``docs/contracts/evidence-retrieval.md`` — Fallback Rule):

1. **Reference source** (FTY-166) — search the sanitized identity + the fixed
   nutrition intent through the pluggable search adapter, fetch each result page
   through the searched-result hardened fetcher, and transcribe/validate the stated
   facts (reusing :func:`~app.estimator.searched_reference.searched_reference_per_100g`).
2. **Model prior** (gated last resort) — estimate typical published facts from the
   sanitized identity alone, gated by the same confidence floor as the pipeline's
   model-prior tier; recorded with honest ``model_prior`` provenance.

Both tiers are reused primitives, so this resolver adds **no** new search, fetch, or
nutrition-mapping path — it opens no socket of its own (all egress flows through the
injected ``search_provider`` and ``reference_fetch_fn``), sends only sanitized item
identity (never profile, history, or raw log text — the same ``sanitize_query``
chokepoint the estimator uses), and only ever produces honestly low-trust per-100g
facts. A snippet-derived reference read (no fetched page behind it) is rejected here:
this single-shot proposal path has no per-page compatibility gate, so it commits only
a fetched-page transcription or the model prior. Provider-authored assumption text is
never persisted — the fallback records a fixed, content-free provenance label instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.enums import SourceType
from app.estimator.barcode_proposal import FallbackFacts
from app.estimator.evidence_utils import _content_hash
from app.estimator.exact_evidence import PER_100G_BASIS
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.identity_sanitizer import sanitized_identity
from app.estimator.reference_fetch import ReferenceFetchSettings, fetch_searched_result
from app.estimator.search import SearchProvider, sanitize_query
from app.estimator.searched_reference import (
    _MODEL_PRIOR_PROMPT,
    _REFERENCE_PAGE_KIND,
    MODEL_PRIOR_SOURCE,
    REFERENCE_SEARCH_INTENT,
    REFERENCE_SOURCE_TYPE,
    SNIPPET_ASSUMPTION,
    FetchReference,
    SearchedReferenceFacts,
    searched_reference_from_estimate,
    searched_reference_per_100g,
)
from app.llm.base import Provider
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.schemas.official_source import EstimateDisposition, NamedFoodEstimate
from app.settings import DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR

#: Content-free provenance labels the fallback records so the applied item stays
#: honestly rough: they name the fallback tier and the barcode miss in closed
#: vocabulary — never raw text, provider output, or a URL. The reference tier's own
#: URL lives in ``source_ref`` (``reference_source:<url>``), per contract.
_REFERENCE_ASSUMPTION = "barcode exact match unavailable; estimated from reference source"
_MODEL_PRIOR_ASSUMPTION = "barcode exact match unavailable; estimated from model prior"

#: The transient/response/config/validation errors one model-prior pass may raise; any
#: of them is a failed estimate (``None``), never a propagated 500.
_LLM_ERRORS = (
    StructuredOutputValidationError,
    LLMResponseError,
    LLMConfigurationError,
    LLMTransientError,
)


@dataclass(frozen=True)
class IdentityFallbackResolver:
    """Estimate a barcode fallback from item identity via reference → model prior.

    Constructed per request by the propose service with the application's configured
    LLM provider, search adapter, and searched-result fetch settings. Every field
    except ``reference_fetch_fn`` is injected; the fetcher defaults to the real
    hardened searched-result fetcher and is overridden by tests.
    """

    provider: Provider
    search_provider: SearchProvider
    reference_fetch_settings: ReferenceFetchSettings
    model_prior_confidence_floor: float = DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR
    reference_fetch_fn: FetchReference = fetch_searched_result

    def resolve(self, identity: str) -> FallbackFacts | None:
        """Estimate ``identity`` (reference source first, then model prior), or ``None``.

        ``identity`` is already sanitized by the caller; this re-sanitizes defensively
        and fails closed on an empty result. Returns the first tier that produces a
        plausible per-100g estimate, else ``None`` (the caller emits a no-proposal
        response).
        """

        sanitized = sanitized_identity(identity)
        if not sanitized:
            return None
        return self._reference(sanitized) or self._model_prior(sanitized)

    def _reference(self, identity: str) -> FallbackFacts | None:
        """Search + fetch + transcribe a public reference page's per-100g facts.

        ``None`` when search or fetch is unavailable, nothing confident is found, or the
        only accepted result is snippet-derived (rejected here, since this path has no
        per-page compatibility gate).
        """

        if not (self.search_provider.enabled and self.search_provider.available):
            return None
        if not self.reference_fetch_settings.is_available:
            return None
        query = sanitize_query(f"{identity} {REFERENCE_SEARCH_INTENT}")
        found = searched_reference_per_100g(
            provider=self.provider,
            search_provider=self.search_provider,
            fetch=self._fetch_reference,
            query=query,
            page_kind=_REFERENCE_PAGE_KIND,
            source_type=REFERENCE_SOURCE_TYPE,
            accept_result=_is_fetched_page_reference,
        )
        if found is None or found.basis != PER_100G_BASIS:
            return None
        return _fallback_facts(found, REFERENCE_SOURCE_TYPE, _REFERENCE_ASSUMPTION)

    def _model_prior(self, identity: str) -> FallbackFacts | None:
        """Estimate typical published per-100g facts from identity alone, gated on floor.

        Mirrors the pipeline's model-prior tier: a single structured completion, gated by
        the model-prior confidence floor and the shared plausibility/canonicalisation.
        ``None`` on a provider error, an unresolved/low-confidence estimate, or facts
        that do not canonicalise to a plausible per-100g basis.
        """

        prompt = _MODEL_PRIOR_PROMPT.format(identity=identity)
        try:
            estimate = self.provider.structured_completion(prompt, NamedFoodEstimate)
        except _LLM_ERRORS:
            return None
        if estimate.disposition is not EstimateDisposition.RESOLVED:
            return None
        if estimate.confidence < self.model_prior_confidence_floor:
            return None
        found = searched_reference_from_estimate(
            estimate, source_ref=MODEL_PRIOR_SOURCE, hash_key=identity
        )
        if found is None or found.basis != PER_100G_BASIS:
            return None
        return _fallback_facts(found, SourceType.MODEL_PRIOR.value, _MODEL_PRIOR_ASSUMPTION)

    def _fetch_reference(self, url: str) -> str | None:
        """Fetch ``url`` through the searched-result fetcher; ``None`` on any failure."""

        try:
            return self.reference_fetch_fn(url, self.reference_fetch_settings)
        except (FetchPolicyError, FetchTransientError, FetchResponseError):
            return None


def _is_fetched_page_reference(found: SearchedReferenceFacts) -> bool:
    """Accept a positive-calorie reference only when it came from a fetched page.

    A snippet-derived result (FTY-314) carries the ``search_result_snippet`` label and
    has no fetched page behind it; this single-shot proposal path has no per-page
    compatibility gate, so it must not commit an unrelated snippet as a source-backed
    match — reject it and fall through to the model prior.
    """

    if found.facts.calories <= 0:
        return False
    return SNIPPET_ASSUMPTION not in found.assumptions


def _fallback_facts(
    found: SearchedReferenceFacts, source_type: str, assumption: str
) -> FallbackFacts:
    """Project a validated searched-reference into a :class:`FallbackFacts`.

    Records a fixed content-free provenance ``assumption`` (never the provider's own
    free-form assumption text, which could echo raw page output) and re-derives the
    content hash from the per-100g facts + source ref.
    """

    return FallbackFacts(
        facts=found.facts,
        source_type=source_type,
        source_ref=found.source_ref,
        content_hash=_content_hash(found.source_ref, found.facts),
        default_serving_g=found.default_serving_g,
        serving_label=None,
        assumptions=(assumption,),
        field_provenance=None,
    )
