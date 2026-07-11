"""Exact-evidence proposal + apply boundary DTOs (FTY-306/307).

Contracts for the ``Make it exact`` lever (``docs/contracts/evidence-retrieval.md``
— **Exact Evidence Upgrade**; ``docs/contracts/food-resolution.md`` — **Exact
Evidence Upgrade Routing**), consumed by the mobile flow (FTY-310–FTY-313) and
produced by the source-specific propose routes (barcode FTY-308, label FTY-309):

- :class:`ExactEvidenceApplyRequest` — the apply request shape. It accepts **only**
  the opaque ``proposal_ref`` plus an optional ``amount``; it forbids extra keys, so
  a client can never inject nutrition facts through this path (the only user-supplied
  numeric input is the optional amount, validated like a quantity edit).
- :class:`ExactEvidenceProposalPreviewDTO` — the would-be applied item's preview:
  the read-model ``source`` descriptor it would carry, its costed calories/macros (or
  the source facts on the proposal's basis when the current amount cannot be costed),
  the current amount, and the serving label.
- :class:`ExactEvidenceProposalDTO` — the proposal read shape: the opaque
  ``proposal_ref``, the evidence ``kind`` / ``quality`` / ``failure_reason``, the
  ``preview``, and the ``can_cost_current_amount`` flag apply enforces.

The apply endpoint's response is the existing
:class:`~app.schemas.corrections.DerivedFoodItemDTO`, so an applied item's source and
``is_edited`` are visible through the existing read model.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import ExactEvidenceKind, ExactEvidenceQuality
from app.schemas.corrections import ItemSourceDTO

#: Canonical sanity bound for a user-supplied amount, matching the corrections edit
#: range bound (``app/services/corrections.py``); a value above it is rejected.
MAX_AMOUNT = 100_000.0

#: Generous upper bound on the opaque signed ``proposal_ref`` at the apply trust
#: boundary. A real server-signed reference — even a fallback carrying assumptions
#: and per-field provenance — is well under 1 KiB; 4096 leaves ~4x headroom for any
#: legitimate proposal while capping the untrusted oversized-request path (HMAC
#: signing + base64/JSON decode) before it can burn CPU/memory. Mirrors the
#: ``max_length`` guard on the sibling trust-boundary ref ``ReResolveRequest.source_ref``.
MAX_PROPOSAL_REF_LENGTH = 4096


class ExactEvidenceApplyRequest(BaseModel):
    """Request body for ``.../food/{item_id}/exact-upgrade/apply``.

    ``proposal_ref`` is the opaque, server-generated reference the propose route
    returned — the only key apply accepts. ``amount`` is an **optional** user
    amount adjustment (in the item's canonical units), applied before costing; when
    omitted the item's current amount is preserved. ``extra="forbid"`` rejects any
    client-supplied nutrition facts or unknown keys with a ``422``.
    """

    model_config = ConfigDict(extra="forbid")

    proposal_ref: str = Field(min_length=1, max_length=MAX_PROPOSAL_REF_LENGTH)
    amount: float | None = None

    @field_validator("amount")
    @classmethod
    def _finite_positive_bounded(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("amount must be a finite number")
        if value <= 0:
            raise ValueError("amount must be positive")
        if value > MAX_AMOUNT:
            raise ValueError("amount is out of range")
        return value


class ExactEvidenceProposalPreviewDTO(BaseModel):
    """The would-be applied item, previewed before an explicit apply (FTY-306).

    A **read projection** — previewing mutates nothing. ``source`` is the read-model
    descriptor the applied item would carry (so a fallback shows its honest rough
    source label, never an exact one); the nutrition fields are the item costed at
    its current ``amount`` when possible, else the proposal's source facts on its own
    ``basis`` (see :attr:`ExactEvidenceProposalDTO.can_cost_current_amount`).
    """

    model_config = ConfigDict(extra="forbid")

    source: ItemSourceDTO
    basis: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    amount: float | None
    serving_label: str | None


class ExactEvidenceProposalDTO(BaseModel):
    """The proposal read shape a propose route returns (FTY-306).

    The client receives this preview plus the opaque ``proposal_ref`` — never a
    writable fact set. ``quality`` / ``failure_reason`` keep a fallback plainly
    distinct from an exact match: ``failure_reason`` is ``None`` for ``exact`` and a
    closed, content-free label for ``fallback`` / ``none``. ``preview`` is ``None``
    only for a ``none`` (nothing-applyable) outcome. ``can_cost_current_amount`` is
    ``false`` when apply will require an explicit amount from the user.
    """

    model_config = ConfigDict(extra="forbid")

    proposal_ref: str
    kind: ExactEvidenceKind
    quality: ExactEvidenceQuality
    failure_reason: str | None = None
    preview: ExactEvidenceProposalPreviewDTO | None = None
    can_cost_current_amount: bool
