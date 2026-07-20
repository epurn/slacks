"""Item re-match boundary DTOs (FTY-093).

The "Change match" lever's request/response shapes, consumed by the correction
sheet (FTY-100):

- :class:`ListAlternativesRequest` — the optional caller-supplied query override
  (the corrected term, e.g. "turkey"). A single item-identity string; the service
  passes it through the FTY-079 ``sanitize_query`` chokepoint before any egress.
- :class:`SourceCandidateDTO` — one alternative source match the client can offer:
  its source classification + stable reference, a display name, the basis its facts
  are expressed against, and a compact per-basis facts preview.
- :class:`AlternativesResponse` — the bounded candidate list.
- :class:`ReResolveRequest` — the chosen candidate **reference** only. ``extra =
  forbid`` is load-bearing: the client cannot smuggle nutrition values through this
  path (that would be the FTY-051 override lever); re-resolve re-derives the facts
  server-side from the reference.

The re-resolved item is returned through the existing
:class:`~app.schemas.corrections.DerivedFoodItemDTO`, so its new source reaches the
client via FTY-092's read-model with no DTO change of its own.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import SourceType

#: Upper bound on the query override / chosen reference crossing the boundary. Item
#: identity and a source ref are both short; a longer string is a sign of smuggled
#: context and is rejected (the override is further length-bounded at the sanitize
#: chokepoint, ≤ 256 chars).
MAX_QUERY_OVERRIDE_LENGTH = 256
MAX_SOURCE_REF_LENGTH = 128


class ListAlternativesRequest(BaseModel):
    """Request body for listing a food item's alternative source candidates.

    ``query`` is an optional item-identity override (the corrected term) so the user
    can re-aim to a different food, not just re-rank the original name. It is item
    identity only — the service sends it through ``sanitize_query`` (control-stripped,
    length-bounded) before any provider egress; profile, history, and metrics have no
    channel here. Omitted ⇒ the providers are queried with the item's own name.
    """

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=MAX_QUERY_OVERRIDE_LENGTH)

    @field_validator("query")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ReResolveRequest(BaseModel):
    """Request body for re-resolving a food item to a chosen candidate.

    ``source_ref`` is the opaque candidate reference the listing step surfaced — a
    **reference only**, never nutrition values. ``extra = forbid`` rejects any attempt
    to pass facts directly, so a client cannot inject calories/macros through this
    path; the server re-derives the facts from the reference.
    """

    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1, max_length=MAX_SOURCE_REF_LENGTH)

    @field_validator("source_ref")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("source_ref must not be empty or whitespace only")
        return stripped


class SourceCandidateDTO(BaseModel):
    """One alternative source match offered for an item (FTY-093).

    The client renders these as "Change match" choices: ``source_type`` (the evidence
    classification driving the source icon), ``source_ref`` (the opaque id echoed back
    on re-resolve — never facts), a display ``name``, the ``basis`` the facts preview
    is expressed against, and the canonical per-basis facts (``calories`` + macros) as
    a compact preview. A rough/`partial` or energy-less match is never offered.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    source_ref: str
    name: str
    basis: Literal["per_100g", "per_100ml", "per_serving"]
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class PriorCorrectionCandidateDTO(BaseModel):
    """A prior-correction match offered for an item (FTY-411).

    The acting user's own confident correction for this item's normalized name, rendered
    as a top-ranked "Your correction" choice above the guessed-source ``candidates``.
    ``source_type`` is always ``prior_correction`` (drives the "Your correction"
    provenance icon); ``source_ref`` is the opaque ``prior_correction:<content_hash>`` id
    echoed back on re-resolve (never facts); ``basis`` is ``as_logged`` — the
    ``calories``/macros are the corrected **total** for the item's portion, not a per-100g
    density — and a macro the correction never supplied is honestly ``null`` (unknown),
    never a fabricated ``0``. ``rescaled`` marks a value carried from a different-portion
    prior via per-gram rescale.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    source_ref: str
    name: str
    basis: Literal["as_logged"]
    calories: float
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    rescaled: bool


class AlternativesResponse(BaseModel):
    """The alternative source candidates for a food item.

    ``candidates`` are the guessed-source (USDA today) matches, unchanged. ``prior_corrections``
    (FTY-411) are the acting user's own confident prior corrections for the item's
    normalized name — a bounded, top-ranked "Your correction" surface the client renders
    **above** ``candidates`` (prior corrections outrank guessed sources, mirroring the
    FTY-406 estimate-time precedence). Empty when the user has no matching prior
    correction, so an item with none returns the ordinary candidate list unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    candidates: list[SourceCandidateDTO]
    prior_corrections: list[PriorCorrectionCandidateDTO] = Field(default_factory=list)
