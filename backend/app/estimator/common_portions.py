"""Common count/household portion defaults for everyday generic foods (FTY-254).

A closed, documented table of typical per-unit gram weights for the small set of
common foods a casual log counts by piece — ``one banana``, ``2 large eggs``,
``1 slice wheat toast``, ``a pat of butter``. USDA Foundation/SR-Legacy rows
often carry no ``servingSize``, so a trusted per-100g match used to stall at
"count with no known serving size" and fall to the rough model-prior tiers even
though the portion is common knowledge with published USDA household weights.

This module supplies that missing default **as an explicit, labelled
assumption** — never silently: the resolver records the returned
``assumption`` label (``estimated_common_portion:banana medium 118 g``) on the
item's evidence row, so the number stays visibly rough at the portion level and
user-editable, while the per-100g facts keep their trusted-database provenance.

Every gram value is a settled published household measure, not a guess (USDA
FoodData Central household weights / FDA RACC vicinity):

- banana: small 101 g, medium 118 g, large 136 g (USDA household weights for a
  6-7" / 7-8" / 8-9" banana, edible portion);
- egg (whole, without shell): small 38 g, medium 44 g, large 50 g, jumbo 63 g
  (USDA egg size weights); ``large`` is the US default egg;
- bread: one regular sandwich slice ≈ 30 g (USDA commercially-prepared bread
  slices run ~25-36 g);
- toast: one slice ≈ 25 g (the same slice after toasting moisture loss);
- butter: one pat ≈ 5 g, one stick ≈ 113 g (USDA household weights).

Pure functions, no I/O, no LLM, bounded vocabulary — the same character as the
serving math it backstops (:mod:`app.estimator.food_serving`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.estimator.food_serving import _COUNT_UNITS

#: Sanity cap on the counted units a common-portion default may multiply; a
#: larger count is not a casual counted snack and fails closed to the existing
#: routing (rough tiers or clarification per the active policy).
MAX_COMMON_PORTION_COUNT: Final[float] = 50.0

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class CommonPortionSpec:
    """Per-unit gram weights for one common food, keyed by a size/serving cue."""

    #: Cue token (a size adjective or serving noun) → grams for one such unit.
    cue_grams: Mapping[str, float]
    #: Cue assumed when the log states none ("one banana" → medium).
    default_cue: str


#: The closed v1 table, keyed by the food's singular head noun. A bounded
#: documented tunable: exactly the everyday counted foods the FTY-254 dogfood
#: set covers. Richer portion inference (``portion_memories``) stays a later
#: story; this is not a general food-density database.
COMMON_PORTIONS: Final[Mapping[str, CommonPortionSpec]] = {
    "banana": CommonPortionSpec(
        cue_grams={"small": 101.0, "medium": 118.0, "large": 136.0},
        default_cue="medium",
    ),
    "egg": CommonPortionSpec(
        cue_grams={"small": 38.0, "medium": 44.0, "large": 50.0, "jumbo": 63.0},
        default_cue="large",
    ),
    "bread": CommonPortionSpec(cue_grams={"slice": 30.0}, default_cue="slice"),
    "toast": CommonPortionSpec(cue_grams={"slice": 25.0}, default_cue="slice"),
    "butter": CommonPortionSpec(cue_grams={"pat": 5.0, "stick": 113.0}, default_cue="pat"),
}


@dataclass(frozen=True)
class CommonPortion:
    """A resolved common-portion quantity: total consumed grams + its label.

    ``assumption`` is a content-free label built solely from table constants
    (never raw diary text), recorded on the evidence row so the portion default
    is explicit and the item stays honestly editable.
    """

    grams: float
    assumption: str


#: A stripped root shorter than this is noise, not a word stem.
_MIN_STEM_CHARS: Final[int] = 3


def _singular(token: str) -> str:
    """Naive singular form for table matching (``eggs`` → ``egg``)."""

    for suffix, replacement in (("ies", "y"), ("s", "")):
        if (
            token.endswith(suffix)
            and not token.endswith("ss")
            and len(token) - len(suffix) >= _MIN_STEM_CHARS
        ):
            return token[: -len(suffix)] + replacement
    return token


def _tokens(text: str | None) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall((text or "").lower()))


def _match_spec(name: str, unit: str | None) -> tuple[str, CommonPortionSpec] | None:
    """The table entry for a candidate, matched on the name's head noun.

    The head noun is the food identity (``wheat toast`` → ``toast``; ``egg
    salad`` → ``salad``, deliberately no match — a composite dish is not a
    counted egg). A bare count-noun unit that is itself the food (``2 eggs``
    parsed as unit ``eggs``) matches too.
    """

    name_tokens = _tokens(name)
    if name_tokens:
        head = _singular(name_tokens[-1])
        spec = COMMON_PORTIONS.get(head)
        if spec is not None:
            return head, spec
    for token in _tokens(unit):
        head = _singular(token)
        spec = COMMON_PORTIONS.get(head)
        if spec is not None:
            return head, spec
    return None


def _unit_is_countable(unit: str | None, food: str, spec: CommonPortionSpec) -> bool:
    """Whether the parsed unit is a plain count of this food's common portions.

    Accepts no unit, the generic count vocabulary (``slice``, ``piece``, …), the
    food noun itself (``eggs``), or one of this food's own cue nouns (``pat``).
    A measured unit (``cup``, ``g``) never reaches this fallback — the
    deterministic serving math already resolved it — but an unrecognised
    non-count unit fails closed here rather than guessing.
    """

    normalized = re.sub(r"\s+", " ", (unit or "").strip().lower())
    if normalized in _COUNT_UNITS:
        return True
    tokens = _tokens(normalized)
    if not tokens:
        return False
    return all(
        _singular(token) == food or _singular(token) in spec.cue_grams or token in _COUNT_UNITS
        for token in tokens
    )


def resolve_common_portion_grams(
    *,
    name: str,
    unit: str | None,
    amount: float | None,
    quantity_text: str,
) -> CommonPortion | None:
    """Resolve a counted common food to grams from the documented portion table.

    Applied only after :func:`~app.estimator.food_serving.resolve_grams` fails
    (the source stated no usable serving size), and only for a **stated count**
    of a table food: a positive structured ``amount`` with a count-like unit.
    The size/serving cue (``large``, ``slice``, ``pat``) is read from the name,
    unit, or quantity phrase; absent a cue the food's documented default
    applies. Returns ``None`` whenever any part does not match, so the caller
    keeps its existing routing (rough tiers or clarification per policy).
    """

    if amount is None or not math.isfinite(amount):
        return None
    if amount <= 0 or amount > MAX_COMMON_PORTION_COUNT:
        return None
    matched = _match_spec(name, unit)
    if matched is None:
        return None
    food, spec = matched
    if not _unit_is_countable(unit, food, spec):
        return None

    cue = spec.default_cue
    for token in (*_tokens(unit), *_tokens(name), *_tokens(quantity_text)):
        candidate = _singular(token)
        if candidate in spec.cue_grams:
            cue = candidate
            break
    grams_per_unit = spec.cue_grams[cue]
    return CommonPortion(
        grams=round(amount * grams_per_unit, 3),
        assumption=f"estimated_common_portion:{food} {cue} {grams_per_unit:g} g",
    )
