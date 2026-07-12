"""Nutrition-label exact-evidence proposal generation for an existing item (FTY-309).

The **label** source-specific generator for the ``Make it exact`` lever
(``docs/contracts/evidence-retrieval.md`` — **Exact Evidence Upgrade — FTY-306**;
``docs/contracts/food-resolution.md`` — **Exact Evidence Upgrade Routing**), the sibling
of the barcode generator (FTY-308). FTY-307 owns the generic apply half (the signed
``proposal_ref`` trust anchor + in-place source replacement); this module owns turning a
user-provided nutrition-**label image** and an existing low-trust food item into a
**proposal** the user previews and applies:

- A legible, usable panel — extracted through the *existing* schema-validated label
  extraction (the shared :data:`~app.estimator.label_step.LABEL_EXTRACTION_PROMPT` +
  :class:`~app.schemas.nutrition_panel.NutritionPanel` schema, then the FTY-044
  deterministic per-serving → per-100g serving math) — yields an **exact**
  ``user_label`` proposal.
- When the panel is unreadable, not a label, or the model's reply fails schema
  validation, the item's own identity is handed to the injected estimator
  :class:`~app.estimator.barcode_proposal.IdentityFallbackSource`; if it can produce a
  low-trust estimate the result is a clearly-labelled **fallback** proposal carrying its
  honest ``reference_source`` / ``model_prior`` provenance and a content-free
  ``failure_reason`` naming the label problem — never masquerading as exact.
- When neither an exact reading nor a fallback can be produced, the outcome carries no
  proposal (a calm, content-free reason) — the caller returns a no-proposal response.

The division between a **fallback** and a retryable ``503`` mirrors the barcode
generator and the contract's Errors table (``food-resolution.md`` — Exact Evidence
Upgrade Routing): a *usable response from the provider that is unusable content* (not a
label, unreadable, schema-invalid) is an honest fallback, while *no usable response* (a
transient timeout/5xx or a non-conforming provider reply) raises
:class:`LabelProviderError` so the route surfaces a retryable ``503`` rather than
disguising a provider outage as a rough estimate that throws away the user's photo.

This module is pure generation: it loads no item, persists nothing, and **never
mutates** the target item — the item changes only when the user applies the returned
proposal through FTY-307, and the raw image's retention (discard-by-default vs an
explicit ``save``) is the propose service's concern, not this generator's. The image is
validated as data at the route boundary *before* any model call; here it is transcribed
by a fixed untrusted-data prompt whose only trusted output is the schema-validated,
deterministically-costed panel, so prompt-injection text printed on the label is data,
never instructions (``docs/security/security-baseline.md``).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from app.enums import ExactEvidenceKind, ExactEvidenceQuality, SourceType
from app.estimator.barcode_proposal import FallbackFacts, IdentityFallbackSource
from app.estimator.clarify_policy import LABEL_CLARIFY_POLICY
from app.estimator.exact_evidence import (
    PER_100G_BASIS,
    PROPOSAL_TTL_SECONDS,
    ExactEvidenceProposal,
    ProposalFacts,
    build_proposal,
)
from app.estimator.food_serving import (
    NutritionFacts,
    per_serving_to_per_100g,
    serving_size_grams,
)
from app.estimator.identity_sanitizer import sanitized_identity
from app.estimator.label_step import LABEL_EXTRACTION_PROMPT
from app.llm.base import ImageInput, Provider
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.models.derived import DerivedFoodItem
from app.schemas.nutrition_panel import NutritionPanel, PanelDisposition

#: Closed, content-free ``failure_reason`` labels a label fallback / no-proposal outcome
#: carries, naming *why* the exact label reading was not usable
#: (``docs/contracts/evidence-retrieval.md`` — Exact Evidence Upgrade; the label
#: vocabulary is fixed here per FTY-306/FTY-309). They never carry raw image bytes, OCR
#: text, the model's reply, or any nutrition value — only the bounded reason class.
#:
#: - ``not_a_label`` — the image is not a nutrition label at all (unusable input);
#: - ``label_unreadable`` — a nutrition label the model could not transcribe confidently
#:   (blur/glare/crop, a confidence below the clarify operating point, missing facts, or
#:   a serving size that does not resolve to grams);
#: - ``label_provider_failed`` — the provider answered, but its reply failed the
#:   ``NutritionPanel`` schema validation (a usable response carrying unusable content);
#: - ``source_unavailable`` — the vision provider is not configured/available.
#:
#: A *transient* provider failure (timeout/5xx) or a *non-conforming* provider response
#: is **not** a ``failure_reason`` here: it raises :class:`LabelProviderError` so the
#: route surfaces a retryable ``503`` rather than disguising a provider outage as an
#: honest miss/fallback (``docs/contracts/food-resolution.md`` — Exact Evidence Upgrade
#: Routing, Errors), mirroring the barcode generator's OFF-error posture (FTY-308).
FAILURE_NOT_A_LABEL: Final = "not_a_label"
FAILURE_UNREADABLE: Final = "label_unreadable"
FAILURE_PROVIDER_FAILED: Final = "label_provider_failed"
FAILURE_SOURCE_UNAVAILABLE: Final = "source_unavailable"


class LabelProviderError(Exception):
    """Raised when the vision provider transport fails, so the route renders ``503``.

    A transient failure (timeout / connection error / 5xx) or a non-conforming provider
    response means we got **no usable response** — retrying may still yield the exact
    label reading, so it must surface as a retryable ``503`` rather than be disguised as
    a rough fallback that discards the user's photo (``docs/contracts/food-resolution.md``
    — Exact Evidence Upgrade Routing, Errors). Mirrors the barcode generator propagating
    an OFF ``OffTransientError`` / ``OffResponseError``. Carries no provider output.
    """


@dataclass(frozen=True)
class LabelExactFacts:
    """The per-100g facts a legible nutrition panel deterministically produced.

    Server-generated by :class:`VisionLabelExactSource`: the panel's per-serving facts
    canonicalised to per-100g by the FTY-044 serving math, plus the label's serving size
    in grams (so a count amount can be costed) and the stable evidence
    ``content_hash`` — the SHA-256 of the image bytes, which a saved ``log_attachments``
    row shares and which never exposes the raw image (``docs/contracts/label-upload.md``).
    """

    facts: NutritionFacts
    content_hash: str
    default_serving_g: float | None


@runtime_checkable
class LabelExactSource(Protocol):
    """The schema-validated label extraction the generator queries for an exact reading.

    Modelled as a Protocol so tests inject a network-free fake with the same shape as the
    real :class:`VisionLabelExactSource`.
    """

    def extract(
        self, *, data: bytes, content_type: str
    ) -> tuple[LabelExactFacts | None, str | None]:
        """Return ``(facts, None)`` for a legible panel, or ``(None, reason)`` for a miss.

        The miss ``reason`` is one of the closed :data:`FAILURE_NOT_A_LABEL` /
        :data:`FAILURE_UNREADABLE` / :data:`FAILURE_PROVIDER_FAILED` /
        :data:`FAILURE_SOURCE_UNAVAILABLE` labels. Raises :class:`LabelProviderError` on a
        transient / non-conforming provider transport failure so the route renders ``503``.
        """
        ...


@dataclass(frozen=True)
class VisionLabelExactSource:
    """Extract a nutrition label into per-100g facts via the vision provider.

    Reuses the *existing* FTY-061 extraction contract unchanged — the shared
    untrusted-data transcriber prompt, the strict :class:`NutritionPanel` schema, the
    label clarify operating point, and the deterministic per-serving → per-100g serving
    math — so this generator adds no new model path or nutrition mapping. The image bytes
    are already validated as data (size / type / signature) at the route boundary; here
    they are only transcribed. Opens no socket beyond the injected ``provider``.
    """

    provider: Provider

    def extract(
        self, *, data: bytes, content_type: str
    ) -> tuple[LabelExactFacts | None, str | None]:
        """Transcribe + cost the label, mapping provider failures to the right posture.

        A validated legible panel returns ``(LabelExactFacts, None)``; an unusable
        disposition, low confidence, missing facts, an unresolvable serving size, or a
        schema-invalid reply returns ``(None, reason)`` (the caller falls to the identity
        fallback); a transient / non-conforming provider transport failure raises
        :class:`LabelProviderError` (→ ``503``).
        """

        try:
            image = ImageInput(data=data, media_type=content_type)
        except LLMConfigurationError:  # pragma: no cover - the route validated the type
            return None, FAILURE_SOURCE_UNAVAILABLE
        try:
            panel = self.provider.structured_completion(
                LABEL_EXTRACTION_PROMPT, NutritionPanel, images=[image]
            )
        except StructuredOutputValidationError:
            # The provider answered but its reply failed schema validation — an unusable
            # response, not an outage: fall to the identity fallback, never persisted.
            return None, FAILURE_PROVIDER_FAILED
        except LLMConfigurationError:
            # No configured/available vision provider: honest miss, not a retry signal.
            return None, FAILURE_SOURCE_UNAVAILABLE
        except (LLMTransientError, LLMResponseError) as exc:
            # No usable response (timeout/5xx/non-conforming): retry may yield the exact
            # reading, so surface a retryable 503 rather than a disguised fallback.
            raise LabelProviderError("label vision provider failed") from exc
        return self._cost(panel, data)

    @staticmethod
    def _cost(panel: NutritionPanel, data: bytes) -> tuple[LabelExactFacts | None, str | None]:
        """Deterministically cost a validated panel to per-100g facts, or classify the miss.

        The panel is untrusted until it validates; a ``not_a_label`` / unreadable /
        low-confidence / factless / unresolvable-serving-size panel produces no exact
        reading. A legible panel's per-serving facts are canonicalised to per-100g by the
        FTY-044 serving math (the model never supplies the stored math), and the label's
        serving size in grams is kept so a count amount can be costed at apply/preview.
        """

        if panel.disposition is PanelDisposition.NOT_A_LABEL:
            return None, FAILURE_NOT_A_LABEL
        facts = panel.facts
        if (
            panel.disposition is PanelDisposition.UNREADABLE
            or LABEL_CLARIFY_POLICY.should_clarify(panel.confidence)
            or facts is None
        ):
            return None, FAILURE_UNREADABLE

        serving_g = serving_size_grams(facts.serving_size_amount, facts.serving_size_unit)
        if serving_g is None:
            # A serving size that does not resolve to grams cannot canonicalise to
            # per-100g facts: treat the label as unreadable rather than guess.
            return None, FAILURE_UNREADABLE

        per_serving = NutritionFacts(
            calories=facts.energy_kcal_per_serving,
            protein_g=facts.protein_g_per_serving,
            carbs_g=facts.carbs_g_per_serving,
            fat_g=facts.fat_g_per_serving,
        )
        per_100g = per_serving_to_per_100g(per_serving, serving_g)
        rounded = NutritionFacts(
            calories=round(per_100g.calories, 4),
            protein_g=round(per_100g.protein_g, 4),
            carbs_g=round(per_100g.carbs_g, 4),
            fat_g=round(per_100g.fat_g, 4),
        )
        content_hash = hashlib.sha256(data).hexdigest()
        return (
            LabelExactFacts(facts=rounded, content_hash=content_hash, default_serving_g=serving_g),
            None,
        )


@dataclass(frozen=True)
class LabelProposalOutcome:
    """The result of a label proposal attempt.

    ``proposal`` is the server-held exact/fallback proposal the caller signs into an
    opaque reference and previews (``None`` for a no-proposal outcome).
    ``failure_reason`` is the content-free label-problem label a fallback / no-proposal
    carries (``None`` for an exact reading).
    """

    proposal: ExactEvidenceProposal | None
    failure_reason: str | None


@dataclass(frozen=True)
class LabelProposalGenerator:
    """Generate an exact-or-fallback label proposal for an existing food item.

    Owns only the source-selection policy: try the exact label reading first (through the
    injected :class:`LabelExactSource`), then the estimator
    :class:`~app.estimator.barcode_proposal.IdentityFallbackSource` from the item's
    identity, else no proposal. It never loads or mutates the item — the caller owns
    owner-scoped loading, image retention, signing the returned proposal, and the read
    projection.
    """

    exact_source: LabelExactSource
    fallback_source: IdentityFallbackSource
    ttl_seconds: int = PROPOSAL_TTL_SECONDS

    def generate(
        self,
        *,
        owner_id: uuid.UUID,
        item: DerivedFoodItem,
        data: bytes,
        content_type: str,
        now: datetime | None = None,
    ) -> LabelProposalOutcome:
        """Build the proposal for ``item`` + the uploaded label image; never mutate ``item``.

        Returns an **exact** ``user_label`` proposal on a legible panel, a **fallback**
        proposal (with a label ``failure_reason``) when the item's identity resolves to a
        low-trust estimate instead, or a **no-proposal** outcome (proposal ``None``,
        content-free reason) when neither is available. A transient / non-conforming
        provider transport failure propagates as :class:`LabelProviderError` (→ ``503``).
        """

        exact, failure_reason = self.exact_source.extract(data=data, content_type=content_type)
        if exact is not None:
            return LabelProposalOutcome(
                proposal=self._exact_proposal(owner_id, item, exact, now), failure_reason=None
            )

        fallback = self._resolve_fallback(item)
        if fallback is not None:
            return LabelProposalOutcome(
                proposal=self._fallback_proposal(owner_id, item, fallback, now),
                failure_reason=failure_reason,
            )
        return LabelProposalOutcome(proposal=None, failure_reason=failure_reason)

    def _resolve_fallback(self, item: DerivedFoodItem) -> FallbackFacts | None:
        """Estimate from the item's sanitized identity, or ``None`` when unavailable.

        Fails closed on an empty sanitized identity (no usable food token → nothing to
        estimate from) before invoking the estimator fallback, so a nameless item never
        drives a broad, identity-free lookup.
        """

        identity = sanitized_identity(item.name)
        if not identity:
            return None
        return self.fallback_source.resolve(identity)

    def _exact_proposal(
        self,
        owner_id: uuid.UUID,
        item: DerivedFoodItem,
        exact: LabelExactFacts,
        now: datetime | None,
    ) -> ExactEvidenceProposal:
        """Build the ``exact`` ``user_label`` proposal from the extracted per-100g facts."""

        facts = ProposalFacts(
            basis=PER_100G_BASIS,
            calories=exact.facts.calories,
            protein_g=exact.facts.protein_g,
            carbs_g=exact.facts.carbs_g,
            fat_g=exact.facts.fat_g,
            default_serving_g=exact.default_serving_g,
            serving_label=None,
        )
        return build_proposal(
            owner_id=owner_id,
            item_id=item.id,
            kind=ExactEvidenceKind.LABEL,
            quality=ExactEvidenceQuality.EXACT,
            source_type=SourceType.USER_LABEL.value,
            source_ref=f"{SourceType.USER_LABEL.value}:{exact.content_hash}",
            content_hash=exact.content_hash,
            facts=facts,
            now=now,
            ttl_seconds=self.ttl_seconds,
        )

    def _fallback_proposal(
        self,
        owner_id: uuid.UUID,
        item: DerivedFoodItem,
        fallback: FallbackFacts,
        now: datetime | None,
    ) -> ExactEvidenceProposal:
        """Build the ``fallback`` proposal, preserving the estimate's honest provenance."""

        facts = ProposalFacts(
            basis=PER_100G_BASIS,
            calories=fallback.facts.calories,
            protein_g=fallback.facts.protein_g,
            carbs_g=fallback.facts.carbs_g,
            fat_g=fallback.facts.fat_g,
            default_serving_g=fallback.default_serving_g,
            serving_label=fallback.serving_label,
        )
        return build_proposal(
            owner_id=owner_id,
            item_id=item.id,
            kind=ExactEvidenceKind.LABEL,
            quality=ExactEvidenceQuality.FALLBACK,
            source_type=fallback.source_type,
            source_ref=fallback.source_ref,
            content_hash=fallback.content_hash,
            facts=facts,
            assumptions=list(fallback.assumptions) or None,
            field_provenance=fallback.field_provenance,
            now=now,
            ttl_seconds=self.ttl_seconds,
        )
