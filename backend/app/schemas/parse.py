"""LLM structured-output schema for the parse step (FTY-042).

This is the *untrusted-analyst* contract: the strict schema the parse step asks
:meth:`app.llm.base.Provider.structured_completion` to enforce, and the validator
every model response must pass before any of it is persisted. The model is told
to extract food/exercise candidates from a log event's raw text; its reply is
trusted only insofar as it validates against these models.

Defence in depth against prompt injection lives in the schema shape itself:

- ``extra="forbid"`` on every model rejects smuggled keys, so a reply cannot
  carry fields the step never asked for.
- String fields are length-bounded and list fields are count-bounded, so an
  adversarial reply cannot persist unbounded blobs.
- The vocabulary is closed (``CandidateType`` / :class:`ParseDisposition`), so the
  disposition and item kind are values, never free-form instructions.

The schema names a *disposition* the step routes on (parsed / needs clarification
/ unparseable) plus a confidence the step gates on a documented threshold. None of
this is executed — it is data the step validates, classifies, and stores.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.enums import CandidateType

#: Schema version recorded on the estimation run for reproducibility. Bump when
#: the candidate shape changes so old runs remain interpretable.
PARSE_SCHEMA_VERSION = "parse/v1"

#: Upper bounds that cap an adversarial or runaway model reply. Generous enough
#: for real logs ("eggs, toast, coffee, a run") yet small enough that a malicious
#: reply cannot persist unbounded data.
MAX_CANDIDATES = 32
MAX_QUESTIONS = 8
MAX_NAME_LEN = 200
MAX_BRAND_LEN = 120
MAX_QUANTITY_LEN = 120
MAX_UNIT_LEN = 32
MAX_QUESTION_LEN = 300
MAX_REASON_LEN = 120
MAX_BARCODE_LEN = 14


class ParseDisposition(StrEnum):
    """How the model classified the log text as a whole.

    - :attr:`PARSED` — at least one confident food/exercise candidate.
    - :attr:`NEEDS_CLARIFICATION` — recognisably a food/exercise log, but too
      ambiguous to parse confidently; the model supplies clarifying questions.
    - :attr:`UNPARSEABLE` — empty, garbage, or not a food/exercise log at all.
    """

    PARSED = "parsed"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNPARSEABLE = "unparseable"


class ParsedCandidate(BaseModel):
    """One extracted food or exercise candidate (minimal, unresolved).

    ``quantity_text`` is the raw portion phrase as written ("two", "150g", "a
    bowl"); ``unit``/``amount`` are an optional best-effort normalisation. The
    downstream calculators (FTY-043/044) own resolving these into canonical units
    and calories, so nothing here carries energy.
    """

    model_config = ConfigDict(extra="forbid")

    type: CandidateType
    name: str = Field(min_length=1, max_length=MAX_NAME_LEN)
    #: Restaurant, manufacturer, or packaged-product brand when the item names a
    #: *specific* branded/named product ("Big Mac" → "McDonald's", "Greek yogurt" →
    #: "Chobani"), as opposed to a generic food ("white rice"). It is the signal the
    #: food step uses to route an unresolved item to the official-source resolver
    #: (FTY-062): a branded item USDA/OFF cannot resolve falls through to
    #: search + hardened fetch, then a model-prior estimate, instead of stopping at
    #: ``needs_clarification``. ``None``/blank ⇒ a generic food (USDA only). Stored as
    #: data, never interpreted as an instruction.
    brand: str | None = Field(default=None, max_length=MAX_BRAND_LEN)
    quantity_text: str = Field(default="", max_length=MAX_QUANTITY_LEN)
    unit: str | None = Field(default=None, max_length=MAX_UNIT_LEN)
    amount: float | None = Field(default=None, ge=0)
    #: A UPC/EAN barcode only when the user explicitly provided one (e.g. a scanned
    #: packaged product, FTY-063). Never invented by the model; an unparseable or
    #: out-of-range value is normalized away by the food step (FTY-060), which then
    #: routes deterministically rather than guessing. Digits only, length-bounded.
    barcode: str | None = Field(default=None, max_length=MAX_BARCODE_LEN, pattern=r"^\d+$")


class ParseResult(BaseModel):
    """The strict structured reply the parse step validates before trusting it.

    Treated as untrusted until it validates: schema-invalid replies are rejected
    and never persisted (see ``docs/contracts/parse-candidates.md``).
    """

    model_config = ConfigDict(extra="forbid")

    disposition: ParseDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    items: list[ParsedCandidate] = Field(default_factory=list, max_length=MAX_CANDIDATES)
    clarification_questions: list[str] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    #: Short, sanitized label set when ``disposition`` is ``unparseable`` — never
    #: echoed raw user text; used only for the run's failure reason.
    reason: str | None = Field(default=None, max_length=MAX_REASON_LEN)
