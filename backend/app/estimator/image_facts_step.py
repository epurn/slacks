"""Image label-facts resolution for mixed text+image events (FTY-376).

The ``user_label`` surface of a unified text+image submission
(``docs/contracts/parse-candidates.md`` v12, "Images as parse evidence
surfaces"): the text supplies identity/count/context ("2 of these bars"), and a
photographed nutrition label supplies per-serving facts as rank-1 ``user_label``
evidence. This step reads each attached image through the **same** schema and
prompt as the standalone label pipeline (:mod:`app.estimator.label_step` —
:data:`~app.estimator.label_step.LABEL_EXTRACTION_PROMPT`,
:class:`~app.schemas.nutrition_panel.NutritionPanel`), then costs the matched
text candidate **deterministically** with the FTY-044 serving math: the panel's
per-serving facts canonicalise to per-100g, and the *text-stated* count/quantity
scales them (``amount = 2`` × the label's serving size). Per-surface provenance
is recorded on the evidence row: ``source_type = user_label`` with the source
image's ``content_hash``, while the item's own ``amount``/``quantity_text``
remain the text surface's; a content-free assumption labels which surface
supplied the scale.

Estimate-first / never-reject: unlike the standalone label pipeline, an image
here is **optional evidence attached to an NL entry**, so nothing in this step
is fatal. An unreadable / non-label / low-confidence image, a provider error
(transient or deterministic), an unresolvable serving size, or an ambiguous
candidate↔image association simply leaves the candidate for the ordinary
downstream tiers (USDA/OFF → official/reference → model-prior) — the run
degrades to a rough, honestly-provenanced estimate rather than failing or
asking. The one exception is the per-run ceiling
(:class:`~app.estimator.run_budget.RunBudgetExceeded`, a ``StepFailed``), which
must keep failing the run closed and is deliberately not swallowed here.

Trust boundary: the image is untrusted data sent to the vision provider only;
facts are used solely after they validate against the strict panel schema, and
prompt-injection printed on an image is data, never instructions. Nothing here
is logged, and no image bytes/hashes reach the run ``trace``/``error``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.estimator.clarify_policy import LABEL_CLARIFY_POLICY
from app.estimator.event_images import EventImage
from app.estimator.evidence_utils import _record_source_ref
from app.estimator.food_serving import (
    NutritionFacts,
    per_serving_to_per_100g,
    resolve_grams,
    scale_facts,
    serving_size_grams,
)
from app.estimator.label_step import LABEL_EXTRACTION_PROMPT, USER_LABEL_SOURCE_TYPE
from app.estimator.pipeline import (
    CandidateDraft,
    EstimationContext,
    ResolvedFoodItem,
)
from app.llm.base import Provider
from app.llm.errors import LLMError
from app.schemas.nutrition_panel import NutritionPanel, PanelDisposition, PanelFacts

#: Content-free assumptions labelling which surface supplied the portion scale
#: (per-surface provenance, ``parse-candidates.md`` v12): the facts are always
#: the image's (``user_label``); the amount is the text surface's stated
#: count/quantity, or one label serving when the text stated none.
AMOUNT_FROM_TEXT_ASSUMPTION = "user_label_facts: amount_from_text"
AMOUNT_DEFAULT_SERVING_ASSUMPTION = "user_label_facts: default_serving_assumed"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _match_candidate(
    candidates: list[CandidateDraft], facts: PanelFacts, *, require_name_match: bool
) -> CandidateDraft | None:
    """Deterministically pick the text candidate a legible panel describes.

    A single food candidate is unambiguous — the entry's "these bars" points at
    the pictured product — but only for a single-image event that has claimed
    nothing yet: a *residual* sole candidate (earlier images claimed the rest)
    or any candidate on a multi-image event must be **named** by the panel, so
    callers pass ``require_name_match=True`` there. Under the name check the
    panel's printed ``product_name`` must name exactly one candidate (best
    token overlap against the candidate's schema-validated name + brand); an
    ambiguous or empty match attributes nothing — mis-attributing label facts
    to the wrong component would be fabricated provenance, so the candidate
    falls through to the ordinary tiers instead.
    """

    if not candidates:
        return None
    if len(candidates) == 1 and not require_name_match:
        return candidates[0]
    name_tokens = _tokens(facts.product_name or "")
    if not name_tokens:
        return None
    scored = [
        (len(name_tokens & _tokens(f"{candidate.name} {candidate.brand or ''}")), candidate)
        for candidate in candidates
    ]
    best = max(score for score, _ in scored)
    if best <= 0:
        return None
    matched = [candidate for score, candidate in scored if score == best]
    return matched[0] if len(matched) == 1 else None


@dataclass(frozen=True)
class ImageFactsResolveStep:
    """Resolve text candidates from attached label images (``user_label``, rank 1)."""

    provider: Provider
    name: str = "image_facts_resolve"

    def run(self, context: EstimationContext) -> None:
        context.tool_names.append(self.name)
        if not context.images or not context.food_candidates:
            context.record_step(self.name, "skipped")
            return

        resolved_any = False
        provider_degraded = False
        multi_image = len(context.images) > 1
        for event_image in context.images:
            if not context.food_candidates:
                # Every candidate is claimed: the remaining images have nothing
                # left to describe, and reading them could only mis-attribute.
                break
            facts, failed = self._extract_panel(event_image)
            provider_degraded = provider_degraded or failed
            if facts is None:
                continue
            candidate = _match_candidate(
                context.food_candidates,
                facts,
                # A residual sole candidate (after a claim) or any candidate on
                # a multi-image event must be named by the panel — the "these
                # bars" single-image shortcut does not extend to either.
                require_name_match=multi_image or resolved_any,
            )
            if candidate is None:
                continue
            item = self._resolve(candidate, event_image, facts)
            if item is None:
                continue
            # Claim the candidate so the USDA/OFF/official tiers only resolve the
            # rest — ``user_label`` is the rank-1 tier for the pictured product.
            context.food_candidates = [c for c in context.food_candidates if c is not candidate]
            context.resolved_food_items.append(item)
            resolved_any = True

        if resolved_any:
            _record_source_ref(context, USER_LABEL_SOURCE_TYPE)
            context.record_step(self.name, "ok")
        elif provider_degraded:
            context.record_step(self.name, "degraded_provider_error")
        else:
            context.record_step(self.name, "no_usable_label")

    def _extract_panel(self, event_image: EventImage) -> tuple[PanelFacts | None, bool]:
        """Extract one image's panel facts, degrading (never failing) on trouble.

        Returns ``(facts, provider_failed)``. Every provider failure class —
        transient, deterministic, schema-invalid — degrades to ``(None, True)``
        so the run continues on its other surfaces; only the run-budget ceiling
        (a ``StepFailed``, not an ``LLMError``) propagates and keeps failing the
        run closed. A validated non-``extracted`` disposition or a
        below-operating-point confidence is an unusable label (the photo may be
        a plain food photo — hypothesis context, never invented numbers).
        """

        try:
            panel: NutritionPanel = self.provider.structured_completion(
                LABEL_EXTRACTION_PROMPT, NutritionPanel, images=[event_image.image]
            )
        except LLMError:
            return None, True
        if (
            panel.disposition is not PanelDisposition.EXTRACTED
            or panel.facts is None
            or LABEL_CLARIFY_POLICY.should_clarify(panel.confidence)
        ):
            return None, False
        return panel.facts, False

    @staticmethod
    def _resolve(
        candidate: CandidateDraft, event_image: EventImage, facts: PanelFacts
    ) -> ResolvedFoodItem | None:
        """Deterministically cost one candidate from a legible panel, or pass.

        The serving math is the label pipeline's (FTY-061): per-serving →
        per-100g via the printed serving size, scaled to the **text-stated**
        quantity (a count multiplies the label's serving size; a measured
        mass/volume converts directly). A serving size or quantity that does
        not resolve to grams returns ``None`` — the candidate falls through to
        the downstream tiers rather than clarifying or guessing.
        """

        serving_g = serving_size_grams(facts.serving_size_amount, facts.serving_size_unit)
        if serving_g is None:
            return None
        per_100g = per_serving_to_per_100g(
            NutritionFacts(
                calories=facts.energy_kcal_per_serving,
                protein_g=facts.protein_g_per_serving,
                carbs_g=facts.carbs_g_per_serving,
                fat_g=facts.fat_g_per_serving,
            ),
            serving_g,
        )
        text_stated = True
        grams = resolve_grams(
            unit=candidate.unit,
            amount=candidate.amount,
            quantity_text=candidate.quantity_text,
            default_serving_g=serving_g,
        )
        if grams is None:
            if candidate.amount is not None or candidate.quantity_text.strip():
                # A stated quantity this math cannot resolve: leave the candidate
                # for the downstream tiers rather than guessing a scale.
                return None
            # No stated quantity at all: default to one label serving — the same
            # "I logged this product" default as the standalone label pipeline.
            grams = round(serving_g, 3)
            text_stated = False
        scaled = scale_facts(per_100g, grams)
        assumption = (
            AMOUNT_FROM_TEXT_ASSUMPTION if text_stated else AMOUNT_DEFAULT_SERVING_ASSUMPTION
        )
        return ResolvedFoodItem(
            name=candidate.name,
            quantity_text=candidate.quantity_text,
            unit=candidate.unit,
            amount=candidate.amount,
            grams=scaled.grams,
            calories=scaled.calories,
            protein_g=scaled.protein_g,
            carbs_g=scaled.carbs_g,
            fat_g=scaled.fat_g,
            # A label is user-provided evidence, never a global cache row.
            product_id=None,
            source_type=USER_LABEL_SOURCE_TYPE,
            source_ref=f"{USER_LABEL_SOURCE_TYPE}:{event_image.content_hash}",
            content_hash=event_image.content_hash,
            fetched_at=datetime.now(UTC),
            calories_per_100g=round(per_100g.calories, 4),
            protein_per_100g=round(per_100g.protein_g, 4),
            carbs_per_100g=round(per_100g.carbs_g, 4),
            fat_per_100g=round(per_100g.fat_g, 4),
            assumptions=(assumption,),
        )
