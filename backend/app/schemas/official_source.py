"""LLM structured-output schema for official-source resolution (FTY-062).

This is the *untrusted-analyst* contract the official-source resolver
(:mod:`app.estimator.official_step`) uses for **two** calls, both validated before
any of it is trusted:

1. **Extraction** — read the sanitized, active-content-stripped text of a fetched
   official-source page (FTY-078) and transcribe the nutrition facts it prints into
   structured per-serving / per-100g values. The page text is *untrusted data*: any
   instructions embedded in it are never followed, the reply is trusted only insofar
   as it validates here, and the deterministic calculators
   (:mod:`app.estimator.food_serving`) — never the model — produce the stored
   calories/macros.
2. **Model-prior estimate** — when no official source can be searched/fetched, fall
   back to a model-prior estimate of the same shape for a *named* product, from the
   sanitized item identity and structured consumed-portion fields. This carries an
   explicit source status (``model_prior``) and ``assumptions`` so the entry stays
   user-editable; it is the gated last-resort fallback, never a silent guess (see
   ``docs/contracts/evidence-retrieval.md`` Fallback Rule).

Defence in depth against prompt injection lives in the schema shape, mirroring
:mod:`app.schemas.parse` and :mod:`app.schemas.nutrition_panel`:

- ``extra="forbid"`` on every model rejects smuggled keys.
- Every numeric field is bounded (``ge`` / ``le`` / ``gt``); string fields are
  length-bounded; the assumptions list is count- and length-bounded.
- The vocabularies are closed (:class:`EstimateDisposition` / :class:`FactBasis`),
  so how the facts were obtained is a value the resolver routes on, never an
  instruction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

#: Schema version recorded on the estimation run for reproducibility. Bump when the
#: estimate shape changes so old runs remain interpretable.
OFFICIAL_SOURCE_SCHEMA_VERSION = "official_source/v1"

#: Upper bounds that cap an adversarial or runaway model reply. Generous enough for
#: any real product yet small enough that a malicious reply cannot persist nonsense.
MAX_PRODUCT_NAME_LEN = 200
MAX_UNIT_LEN = 32
MAX_ASSUMPTIONS = 8
MAX_ASSUMPTION_LEN = 200
#: A single serving / 100 g never realistically exceeds these; a fail-closed ceiling
#: on the transcribed numbers, not a nutrition judgement.
MAX_ENERGY_KCAL = 10_000.0
MAX_MACRO_G = 1_000.0
MAX_SERVING_AMOUNT = 100_000.0


class EstimateDisposition(StrEnum):
    """Whether the model produced usable nutrition facts.

    - :attr:`RESOLVED` — usable facts are present in ``facts`` (a legible page
      transcription, or a confident model-prior estimate).
    - :attr:`UNRESOLVED` — no usable facts could be produced (the page carried none,
      or the model could not estimate the named product); the resolver falls through
      (page → model-prior; model-prior → ``needs_clarification``), never guessing.
    """

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class FactBasis(StrEnum):
    """What the transcribed/estimated facts are expressed against.

    - :attr:`PER_100G` — facts are per 100 grams; used directly by the serving math.
    - :attr:`PER_SERVING` — facts are per single serving; the resolver converts them
      to per-100g using ``serving_size_amount`` / ``serving_size_unit`` (which must
      resolve to grams), exactly as the nutrition-label step does.
    - :attr:`AS_LOGGED` — facts are a bounded rough total for the structured logged
      portion itself. This is allowed only for model-prior fallback when grams cannot
      honestly be inferred; it is stored as ``model_prior`` with assumptions and is
      never presented as source-backed per-100g evidence.
    """

    PER_100G = "per_100g"
    PER_SERVING = "per_serving"
    AS_LOGGED = "as_logged"


class EstimatedFacts(BaseModel):
    """The transcribed or estimated nutrition facts for one named product.

    Energy/macros are expressed against ``basis``. For ``per_100g`` /
    ``per_serving`` facts, the backend — never the model — converts them to canonical
    per-100g facts and scales them to the consumed quantity
    (:mod:`app.estimator.food_serving`). ``serving_size_amount`` /
    ``serving_size_unit`` are the source's serving size; they are **required** to
    canonicalise ``per_serving`` facts and otherwise enable count-unit serving math.
    ``as_logged`` facts are already the rough consumed-portion total, so they are
    stored directly with ``basis = as_logged`` and model-prior provenance.
    """

    model_config = ConfigDict(extra="forbid")

    #: Optional product name from the source; used only as the display name.
    product_name: str | None = Field(default=None, max_length=MAX_PRODUCT_NAME_LEN)
    basis: FactBasis
    calories: float = Field(ge=0.0, le=MAX_ENERGY_KCAL)
    protein_g: float = Field(default=0.0, ge=0.0, le=MAX_MACRO_G)
    carbs_g: float = Field(default=0.0, ge=0.0, le=MAX_MACRO_G)
    fat_g: float = Field(default=0.0, ge=0.0, le=MAX_MACRO_G)
    serving_size_amount: float | None = Field(default=None, gt=0.0, le=MAX_SERVING_AMOUNT)
    serving_size_unit: str | None = Field(default=None, max_length=MAX_UNIT_LEN)


class NamedFoodEstimate(BaseModel):
    """The strict structured reply the official-source resolver validates.

    Treated as untrusted until it validates: a schema-invalid reply is rejected and
    never persisted (fail closed). ``facts`` is required when ``disposition`` is
    ``resolved`` and ignored otherwise — the resolver enforces that pairing when it
    routes. ``assumptions`` carries documented caveats (model-prior reason, density,
    default serving) recorded with the resolved item.
    """

    model_config = ConfigDict(extra="forbid")

    disposition: EstimateDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    facts: EstimatedFacts | None = None
    assumptions: list[Annotated[str, Field(max_length=MAX_ASSUMPTION_LEN)]] = Field(
        default_factory=list, max_length=MAX_ASSUMPTIONS
    )
