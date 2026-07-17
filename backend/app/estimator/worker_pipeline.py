"""Worker-side pipeline construction (FTY-040 … FTY-376).

Builds the production estimation pipeline for one worker attempt. Extracted
from :mod:`app.estimator.processing` so the worker module stays focused on
claim/idempotency/outcome routing; behaviour is unchanged from when this code
lived there. The food step (FTY-044/060) needs the database session for the
product cache and evidence writes, which is why the pipeline is built per call
with the session in scope. Building the clients/adapters makes no network call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.estimator.fdc import build_fdc_client
from app.estimator.food_resolvers import BarcodeResolver, FoodResolver, OffNameResolver
from app.estimator.image_facts_step import ImageFactsResolveStep
from app.estimator.off import build_off_client
from app.estimator.official_fetch import load_official_fetch_settings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.pipeline import Pipeline, default_pipeline, label_pipeline
from app.estimator.reference_fetch import load_reference_fetch_settings
from app.estimator.run_budget import BudgetedProvider
from app.estimator.search import build_search_provider
from app.estimator.user_text_macro_estimator import UserTextMacroEstimator
from app.estimator.user_text_step import UserTextResolveStep
from app.llm import build_provider, load_llm_settings
from app.settings import load_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.estimator.label_step import LabelInput


def build_worker_pipeline(session: Session, label_upload: LabelInput | None) -> Pipeline:
    """Build the pipeline one worker attempt runs, selecting label vs. NL parse.

    A standalone nutrition-label event (FTY-061, ``label_upload`` present) has an
    image rather than NL text and runs the deterministic ``label_pipeline``.
    Every other event — including an image-bearing unified text+image submission
    (FTY-374/FTY-376), which is an **NL event with image evidence surfaces**,
    never a label event — runs ``default_pipeline``: the provider-driven parse
    (with the event's images attached as vision evidence), the deterministic
    exercise calculator, the rank-1 user-text and image-label-facts tiers, USDA/
    OFF food resolution, and the official-source/reference/model-prior cascade.

    The provider is wrapped in a fresh :class:`BudgetedProvider` per attempt so
    the run's total sequential provider work is bounded (FTY-363): every step
    shares this one budgeted provider and the whole attempt fails closed on
    breach.
    """

    app_settings = load_settings()
    provider = BudgetedProvider(build_provider(load_llm_settings()))
    if label_upload is not None:
        # A label event has an image, not NL text: extract it deterministically
        # rather than running the text parse pipeline.
        return label_pipeline(provider)

    # A barcode candidate prefers the Open Food Facts source (enabled by
    # default); a generic food uses USDA FDC (disabled without a key, leaving
    # the candidate unresolved). The official-source step (FTY-062/166) runs
    # last for the candidates the food step deferred: it searches (FTY-079) and
    # fetches official pages (FTY-078), then public reference pages (FTY-166),
    # else falls through to a model-prior estimate.
    resolver = FoodResolver(session=session, source=build_fdc_client())
    # One OFF client backs both the barcode resolver (FTY-060) and the name-search
    # resolver (FTY-369); building it makes no network call.
    off_client = build_off_client()
    barcode_resolver = BarcodeResolver(session=session, source=off_client)
    off_name_resolver = OffNameResolver(session=session, source=off_client)
    search_provider = build_search_provider()
    reference_fetch_settings = load_reference_fetch_settings()
    official_step = OfficialSourceResolveStep(
        provider=provider,
        search_provider=search_provider,
        fetch_settings=load_official_fetch_settings(),
        reference_fetch_settings=reference_fetch_settings,
        off_name_resolver=off_name_resolver,
        model_prior_confidence_floor=app_settings.estimator_model_prior_confidence_floor,
        clarify_mode=app_settings.estimator_clarify_mode,
    )
    # The user-text tier (FTY-280) resolves a stated calorie total directly and
    # fills its missing macros from the same reference search/fetch path before
    # the model prior. It runs before the food step (rank 1).
    user_text_step = UserTextResolveStep(
        macro_estimator=UserTextMacroEstimator(
            provider=provider,
            search_provider=search_provider,
            reference_fetch_settings=reference_fetch_settings,
        )
    )
    return default_pipeline(
        provider,
        parse_policy=ParsePolicySettings.from_app_settings(app_settings),
        food_resolver=resolver,
        barcode_resolver=barcode_resolver,
        official_step=official_step,
        user_text_step=user_text_step,
        image_facts_step=ImageFactsResolveStep(provider),
    )
