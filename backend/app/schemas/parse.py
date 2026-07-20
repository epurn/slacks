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

import re
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import CandidateType

#: Schema version recorded on the estimation run for reproducibility. Bump when
#: the candidate shape changes so old runs remain interpretable. Bumped to
#: ``parse/v3`` for the additive event-level ``event_name`` output (FTY-422).
PARSE_SCHEMA_VERSION = "parse/v3"

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
MAX_OPTIONS = 5
MAX_OPTION_LEN = 80
MAX_REASON_LEN = 120
MAX_BARCODE_LEN = 14

#: Upper bound on the model-generated event-level meal name (FTY-422). A few words
#: ("Turkey sandwich") — not the raw phrase — so a tight cap keeps it a label. The
#: value is truncated to this length rather than rejected: a cosmetic label must
#: never fail an otherwise-valid extraction.
MAX_EVENT_NAME_LEN = 80

#: C0/C1 control characters stripped from the model-produced meal name before it is
#: persisted (defence in depth over the schema shape — the name is untrusted output
#: shown back to the owner).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_event_name(value: object) -> str | None:
    """Bound and clean a model-produced meal name for persistence (FTY-422).

    The name is untrusted model output persisted to ``log_events.name`` and shown
    back to the owner, so it is stripped of control characters, whitespace-collapsed,
    length-bounded to :data:`MAX_EVENT_NAME_LEN`, and reduced to ``None`` when blank.
    A non-string reply is dropped to ``None`` rather than failing the parse: the label
    is cosmetic, so an odd value must never reject an otherwise-valid extraction.
    """

    if not isinstance(value, str):
        return None
    cleaned = " ".join(_CONTROL_CHARS_RE.sub(" ", value).split())
    if not cleaned:
        return None
    return cleaned[:MAX_EVENT_NAME_LEN].rstrip() or None


#: Fail-closed abuse caps on the user-stated nutrition facts (FTY-279/FTY-280). A
#: stated value above these — or negative / non-finite — makes the reply
#: schema-invalid and fails closed. They are *as-logged totals for one item*, so
#: the caps mirror the label path's per-entry ceilings (``nutrition_panel``:
#: ``MAX_ENERGY_KCAL``/``MAX_MACRO_G``), not the per-100g plausibility bound (which
#: needs a mass the user did not give). The food step re-validates plausibility and
#: internal consistency before any of it backs a persisted number.
MAX_STATED_ENERGY_KCAL = 10_000.0
MAX_STATED_MACRO_G = 1_000.0

OptionText = Annotated[str, Field(min_length=1, max_length=MAX_OPTION_LEN)]


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
    #: Explicit nutrition facts the user *stated in the entry text* (FTY-279/FTY-280):
    #: an as-logged calorie total ("580 cals") and/or macro grams ("35g protein"),
    #: extracted verbatim — never invented. An unstated field is ``None``. These are
    #: **as-logged totals for this item** (not per-100g / per-serving), captured as
    #: untrusted evidence: the food step validates plausibility + internal consistency
    #: (Atwater) and the as-logged abuse cap before any of it backs a persisted number
    #: (``docs/contracts/evidence-retrieval.md`` → User-Stated Nutrition Evidence). A
    #: stated calorie total drives ``user_text`` resolution (``food-resolution.md``);
    #: the model must not synthesize a number the user did not give, nor copy a value
    #: from one item onto another. Stored as data, never interpreted.
    stated_calories: float | None = Field(
        default=None, ge=0.0, le=MAX_STATED_ENERGY_KCAL, allow_inf_nan=False
    )
    stated_protein_g: float | None = Field(
        default=None, ge=0.0, le=MAX_STATED_MACRO_G, allow_inf_nan=False
    )
    stated_carbs_g: float | None = Field(
        default=None, ge=0.0, le=MAX_STATED_MACRO_G, allow_inf_nan=False
    )
    stated_fat_g: float | None = Field(
        default=None, ge=0.0, le=MAX_STATED_MACRO_G, allow_inf_nan=False
    )


class ClarificationQuestion(BaseModel):
    """One targeted clarification question plus display-only quick-pick options.

    The model output remains untrusted data. ``text`` names the missing detail,
    and ``options`` are candidate answers the client may render as chips. Options
    are not an enum: the answer endpoint always accepts free text.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_QUESTION_LEN)
    options: list[OptionText] = Field(default_factory=list, max_length=MAX_OPTIONS)

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("clarification question text must not be blank")
        return stripped

    @field_validator("options")
    @classmethod
    def _strip_options(cls, value: list[str]) -> list[str]:
        stripped = [option.strip() for option in value]
        if any(not option for option in stripped):
            raise ValueError("clarification options must not be blank")
        return stripped


class ParseResult(BaseModel):
    """The strict structured reply the parse step validates before trusting it.

    Treated as untrusted until it validates: schema-invalid replies are rejected
    and never persisted (see ``docs/contracts/parse-candidates.md``).
    """

    model_config = ConfigDict(extra="forbid")

    disposition: ParseDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    items: list[ParsedCandidate] = Field(default_factory=list, max_length=MAX_CANDIDATES)
    clarification_questions: list[ClarificationQuestion] = Field(
        default_factory=list, max_length=MAX_QUESTIONS
    )
    #: A short, human-readable meal name the model generates for the whole event
    #: (FTY-422): e.g. "Turkey sandwich" for a multi-ingredient sandwich entry — a
    #: few words summarizing the log, not the raw phrase and not one item's name.
    #: Untrusted model output: :func:`sanitize_event_name` bounds and cleans it before
    #: the estimator persists it to ``log_events.name`` (``log-events.md`` FTY-421).
    #: ``None``/blank when the model offered no sensible name; the estimator also
    #: leaves it ``None`` for an exercise-only or empty/failed event rather than
    #: inventing a label. Stored as data, never interpreted as an instruction.
    event_name: str | None = Field(default=None)
    #: Short, sanitized label set when ``disposition`` is ``unparseable`` — never
    #: echoed raw user text; used only for the run's failure reason.
    reason: str | None = Field(default=None, max_length=MAX_REASON_LEN)

    @field_validator("event_name", mode="before")
    @classmethod
    def _sanitize_event_name(cls, value: object) -> str | None:
        return sanitize_event_name(value)
