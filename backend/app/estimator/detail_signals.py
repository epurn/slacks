"""Deterministic detail-signal detection (FTY-167).

Model-free helpers that decide whether a parsed candidate carries enough
real-world structure — a numeric count, a numeric range, a distance, a step
count, or a game count — to be estimated deterministically, so a casual-but-
detailed log ("a handful (5-10) of onion rings", "ran 5 km") is not routed to
clarification just because the model's confidence was conservative.

These operate only on the schema-validated / already-bounded candidate fields
(``unit`` / ``amount`` / ``quantity_text``); they never read the raw diary text
directly and never produce a nutrition number. They gate *routing* only — the
deterministic calculators (:mod:`app.estimator.food_serving`,
:mod:`app.estimator.exercise`) still own every calorie/macro value.

Design: every parser is pure, total, and returns ``None`` when its signal is
absent, so a caller can chain them and fail closed. The vocabularies are small,
documented tunables. Bare single-letter distance units (``m``) are deliberately
excluded because ``m`` already means *minutes* in the exercise duration parser;
distance metres must be spelled out (``meters`` / ``metres``) to be recognised.
"""

from __future__ import annotations

import re
from typing import Final

from app.estimator.food_serving import (
    _MASS_UNIT_GRAMS,
    _VOLUME_UNIT_GRAMS,
    _grams_from_text,
)

# ---------------------------------------------------------------------------
# Numeric ranges — "a handful (5-10) of onion rings".
# A range is resolved to its arithmetic midpoint, a deterministic documented
# assumption (7.5 for 5-10). The midpoint lets the serving math estimate a
# single number instead of asking the user which end of the range they meant.
# ---------------------------------------------------------------------------

#: Match "5-10", "5 - 10", "5–10" (en/em dash), or "5 to 10". The look-around
#: keeps the match from splitting a longer decimal token.
_RANGE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)(?![\d.])",
    re.IGNORECASE,
)


def parse_range_midpoint(quantity_text: str) -> tuple[float, float, float] | None:
    """Return ``(low, high, midpoint)`` for a numeric range in ``quantity_text``.

    Returns ``None`` when no range is present. The bounds are ordered (a
    reversed "10-5" is normalised) and a non-positive range is rejected so a
    stray "0-0" does not become a zero portion.
    """

    match = _RANGE_RE.search(quantity_text or "")
    if match is None:
        return None
    low = float(match.group(1))
    high = float(match.group(2))
    if high < low:
        low, high = high, low
    if high <= 0:
        return None
    midpoint = round((low + high) / 2.0, 3)
    return low, high, midpoint


# ---------------------------------------------------------------------------
# Bare counts — "(i had 4)", "4", "2 large".
# A stated count with no measured unit is usable evidence — a count of pieces or
# servings — so it is lifted into the structured ``amount`` when the model
# stranded it in ``quantity_text`` and left ``amount`` empty. A measured quantity
# ("100 g", "1 tbsp") is owned by the serving math and is never re-read as a
# count here; a numeric range is owned by :func:`parse_range_midpoint`.
# ---------------------------------------------------------------------------

#: A casual counted log is a small whole number; a larger value is not a piece
#: count and falls closed to the existing routing (rough tiers / clarification).
MAX_BARE_COUNT: Final[float] = 50.0

#: A *standalone* whole number — a count of pieces/servings — delimited by
#: whitespace/punctuation on both sides, never glued to another character that
#: makes it a product or detail numeral rather than a count:
#:   * a decimal ("1.5") or the digits inside a measured "150 g" — the dot / digit
#:     look-arounds keep those from being read as a bare count;
#:   * a fat/detail percentage ("2% milk", "2 % milk") — a digit immediately (or
#:     across spaces) followed by ``%`` is excluded;
#:   * a fraction ("1/3", "1/3 cup") — a digit adjacent to ``/`` on either side is
#:     excluded (the measured-portion path owns worded fractions);
#:   * a product-number hint glued to letters ("7up", "v8") — a digit touching a
#:     word character is excluded.
#: A genuine count token ("4", "(i had 4)", "2 large", "4 toppables") is still
#: matched because it is bounded by spaces or parentheses, not glued to any of the
#: above.
_BARE_COUNT_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\w./])(\d+)(?![\w./]|\s*%)")

#: A fraction ("1/3", "1 / 2") is a measured/detail portion, never a piece count.
#: The token look-arounds already reject a *glued* fraction, but a spaced fraction
#: ("1 / 2 avocado") strands a lone denominator that would otherwise read as a
#: count, so the whole phrase is rejected when any numeric fraction is present. A
#: non-numeric slash ("w/ hummus") has no digits around it and does not match.
_FRACTION_RE: Final[re.Pattern[str]] = re.compile(r"\d+\s*/\s*\d+")

#: The supported measured mass/volume unit spellings whose form is more than one
#: word ("fl oz", "fluid ounce"). Derived from the canonical serving-math vocabularies
#: so this stays in sync as units are added. :func:`app.estimator.food_serving._grams_from_text`
#: reads only ONE alphabetic token after the number, so it silently misses these
#: multi-word measures — a stated "1 fl oz" would otherwise fall through to the bare-count
#: recovery and be lifted into ``amount`` as a fabricated serving count of 1. Single-token
#: measured units ("100 g", "1 tbsp") are already caught by ``_grams_from_text``.
_MULTIWORD_MEASURED_UNITS: Final[tuple[str, ...]] = tuple(
    sorted(
        (unit for unit in (*_MASS_UNIT_GRAMS, *_VOLUME_UNIT_GRAMS) if " " in unit),
        key=len,
        reverse=True,
    )
)

#: Match "<number> <multi-word measured unit>" ("1 fl oz", "2 fluid ounces"). Each
#: unit's internal space is matched as flexible whitespace so "1 fl  oz" still counts;
#: the trailing ``\b`` keeps "fluid ounce" from matching a longer glued word. The
#: alternation is longest-first (``sorted`` above) so "fluid ounces" wins over
#: "fluid ounce".
_MULTIWORD_MEASURED_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*(?:"
    + "|".join(unit.replace(" ", r"\s+") for unit in _MULTIWORD_MEASURED_UNITS)
    + r")\b",
    re.IGNORECASE,
)


def parse_leading_count(quantity_text: str) -> float | None:
    """Return a stated bare count from ``quantity_text``, or ``None``.

    A "bare count" is a small whole number the user stated with no measured unit
    — "(i had 4)", "4", "2 large" — i.e. a count of pieces or servings. It is
    returned so a caller can lift it into the structured ``amount`` the model
    left empty (:func:`app.estimator.parse._effective_candidate`), so a supplied
    count reaches the count/common-portion/model-prior scaling instead of being
    silently dropped and re-asked. Returns ``None`` when the phrase already
    carries a measured mass/volume quantity (owned by the serving math) — including
    a multi-word measured unit such as ``1 fl oz`` / ``1 fluid ounce`` that the
    single-token :func:`app.estimator.food_serving._grams_from_text` scan misses — states a
    numeric range (owned by :func:`parse_range_midpoint`), carries only a *detail*
    numeral rather than a count — a percentage ("2% milk"), a fraction ("1/3 cup"),
    or a product-number hint glued to letters ("7up", "v8") — has no standalone
    whole number, or the number is non-positive or beyond a casual count
    (:data:`MAX_BARE_COUNT`). Only a whitespace/punctuation-delimited count token is
    recovered (:data:`_BARE_COUNT_RE`), so a non-count detail numeral is never
    lifted into ``amount``.
    """

    text = quantity_text or ""
    # A measured quantity ("100 g", "1 tbsp") is the serving math's, not a count.
    # `_grams_from_text` catches single-token measures; a multi-word measured unit
    # ("1 fl oz", "1 fluid ounce") is invisible to it (it reads one token), so it is
    # excluded explicitly to keep a stated measured portion from being recovered as
    # a bare count (FTY-362 reviewer round 2).
    if _grams_from_text(text) is not None or _MULTIWORD_MEASURED_RE.search(text) is not None:
        return None
    # A range resolves to a midpoint through its own deterministic path.
    if parse_range_midpoint(text) is not None:
        return None
    # A fraction ("1/3", "1 / 2") is a stated portion, not a piece count.
    if _FRACTION_RE.search(text) is not None:
        return None
    match = _BARE_COUNT_RE.search(text)
    if match is None:
        return None
    value = float(match.group(1))
    if value <= 0 or value > MAX_BARE_COUNT:
        return None
    return value


# ---------------------------------------------------------------------------
# Distance — "ran 5 km", "swam a mile".
# Converted to kilometres so the exercise calculator can apply a documented
# pace. Bare "m" is excluded (it is minutes); spell metres out.
# ---------------------------------------------------------------------------

#: Kilometres per recognised distance unit.
_DISTANCE_UNIT_KM: Final[dict[str, float]] = {
    "km": 1.0,
    "kilometer": 1.0,
    "kilometre": 1.0,
    "kilometers": 1.0,
    "kilometres": 1.0,
    "mi": 1.609344,
    "mile": 1.609344,
    "miles": 1.609344,
    "meter": 0.001,
    "metre": 0.001,
    "meters": 0.001,
    "metres": 0.001,
    "yard": 0.0009144,
    "yards": 0.0009144,
    "yd": 0.0009144,
    "foot": 0.0003048,
    "feet": 0.0003048,
    "ft": 0.0003048,
}

#: Match "<number> <distance unit>" inside a raw phrase ("5 km", "13.1 miles").
_DISTANCE_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(km|kilometres?|kilometers?|miles?|mi|metres?|meters?|yards?|yd|feet|foot|ft)\b",
    re.IGNORECASE,
)

#: Match a bare singular distance with an implied count of one ("a mile").
_BARE_DISTANCE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:a|an|one)\s+(km|kilometre|kilometer|mile|metre|meter|yard|foot)\b",
    re.IGNORECASE,
)


def distance_km(unit: str | None, amount: float | None, quantity_text: str) -> float | None:
    """Return the logged distance in kilometres, or ``None`` when absent.

    Prefers a structured ``amount`` + distance ``unit``; otherwise scans
    ``quantity_text`` for "<number> <distance unit>" and, failing that, a bare
    singular distance ("a mile") which implies one unit. A distance ``unit`` with
    no amount also implies one unit.
    """

    normalized = (unit or "").strip().lower()
    factor = _DISTANCE_UNIT_KM.get(normalized)
    if factor is not None and amount is not None and amount > 0:
        return round(amount * factor, 4)

    text = quantity_text or ""
    match = _DISTANCE_TEXT_RE.search(text)
    if match is not None:
        value = float(match.group(1))
        if value > 0:
            return round(value * _DISTANCE_UNIT_KM[match.group(2).lower()], 4)

    bare = _BARE_DISTANCE_RE.search(text)
    if bare is not None:
        return round(_DISTANCE_UNIT_KM[bare.group(1).lower()], 4)

    if factor is not None:
        # A distance unit with no (or a non-positive) amount implies one unit.
        return round(factor, 4)
    return None


# ---------------------------------------------------------------------------
# Steps — "walked 13000 steps".  Converted to a walking duration by cadence.
# ---------------------------------------------------------------------------

_STEP_UNITS: Final[frozenset[str]] = frozenset({"step", "steps"})

_STEP_TEXT_RE: Final[re.Pattern[str]] = re.compile(r"(\d[\d,]*)\s*steps?\b", re.IGNORECASE)


def step_count(unit: str | None, amount: float | None, quantity_text: str) -> float | None:
    """Return the logged step count, or ``None`` when absent."""

    if (unit or "").strip().lower() in _STEP_UNITS and amount is not None and amount > 0:
        return amount

    match = _STEP_TEXT_RE.search(quantity_text or "")
    if match is not None:
        value = float(match.group(1).replace(",", ""))
        if value > 0:
            return value
    return None


# ---------------------------------------------------------------------------
# Games — "played 3 games of badminton".  Converted to a duration by a
# documented per-game estimate for the activity.
# ---------------------------------------------------------------------------

_GAME_UNITS: Final[frozenset[str]] = frozenset({"game", "games", "match", "matches", "set", "sets"})

_GAME_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+)\s*(?:games?|matches?|sets?)\b", re.IGNORECASE
)


def game_count(unit: str | None, amount: float | None, quantity_text: str) -> float | None:
    """Return the logged game/match count, or ``None`` when absent."""

    if (unit or "").strip().lower() in _GAME_UNITS and amount is not None and amount > 0:
        return amount

    match = _GAME_TEXT_RE.search(quantity_text or "")
    if match is not None:
        value = float(match.group(1))
        if value > 0:
            return value
    return None


# ---------------------------------------------------------------------------
# Detail predicate for food candidates.
#
# A stated portion — numeric, a numeric range, a household measure, a colloquial
# measure word, or an indefinite article standing for one — means the user *stated*
# a portion (FTY-275), so a generic source-miss defers to a model-prior estimate
# rather than re-asking for an amount the user already gave (in words). Only a
# genuinely amountless component ("some milk", bare "milk", "some crackers") still
# clarifies. This predicate is a defensive routing net; the primary mechanism is the
# parse resolving a costable amount+unit (:mod:`app.estimator.parse_prompt`).
# ---------------------------------------------------------------------------

#: Lower-case word tokeniser for scanning a quantity phrase for stated-portion words.
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]+")

#: Household / cooking volume tokens that state a portion (FTY-275). Mirrors the
#: household measures :func:`app.estimator.food_serving.resolve_grams` now costs; a
#: phrase carrying one ("1/3 cup", "a tsp", "2 tbsp", "1 fl oz") is a stated portion
#: even when the model left the structured ``amount`` empty. ``fl oz`` tokenises to
#: ``fl``/``oz``, so ``fl`` alone flags a fluid measure (bare ``oz`` stays mass).
_HOUSEHOLD_UNIT_WORDS: Final[frozenset[str]] = frozenset(
    {
        "cup",
        "cups",
        "tsp",
        "teaspoon",
        "teaspoons",
        "tbsp",
        "tbs",
        "tablespoon",
        "tablespoons",
        "fl",
        "floz",
        "pint",
        "pints",
        "pt",
        "quart",
        "quarts",
        "qt",
        "gallon",
        "gallons",
        "gal",
    }
)

#: Colloquial / approximate measure words that state a (rough) portion (FTY-275): "a
#: splash of milk", "a drizzle of oil", "a handful of nuts", "a dash of salt". Their
#: presence means the user stated a portion — the estimate-first policy estimates it
#: (the model resolves the phrase to a concrete amount+unit), never re-clarifies.
_COLLOQUIAL_MEASURE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "splash",
        "splashes",
        "drizzle",
        "drizzles",
        "dash",
        "dashes",
        "pinch",
        "pinches",
        "handful",
        "handfuls",
        "glug",
        "glugs",
    }
)

#: An indefinite article standing for a single portion ("a"/"an" = 1): "a splash of
#: milk", "an apple". A bare identity ("milk", "some milk", "some crackers") has no
#: leading standalone indefinite article, so it is not treated as a stated portion.
_INDEFINITE_MEASURE_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:an?)\s+\S", re.IGNORECASE)


def has_stated_nutrition(
    stated_calories: float | None,
    stated_protein_g: float | None = None,
    stated_carbs_g: float | None = None,
    stated_fat_g: float | None = None,
) -> bool:
    """Whether the user stated an explicit nutrition fact for this item (FTY-279/280).

    ``True`` when a calorie total or any macro was stated (a positive value). Like a
    stated portion (FTY-275) this is a **detail signal**: a recognizable item carrying
    one is resolved/estimated from that stated evidence rather than re-asked for a
    serving amount (``food-resolution.md`` no-second-follow-up). A stated *calorie
    total* additionally drives direct ``user_text`` resolution
    (:mod:`app.estimator.user_text_step`); a stated macro alone is still detail enough
    to defer a source-miss to estimation instead of clarifying.
    """

    return any(
        value is not None and value > 0
        for value in (stated_calories, stated_protein_g, stated_carbs_g, stated_fat_g)
    )


def has_food_detail(amount: float | None, quantity_text: str) -> bool:
    """Whether a food candidate carries enough amount detail to estimate.

    ``True`` when the model supplied a positive structured ``amount`` (a count or a
    measured quantity), ``quantity_text`` states a numeric range (which resolves to a
    midpoint), ``quantity_text`` states a bare count ("(i had 4)", "2 large") the
    model stranded there, or ``quantity_text`` carries a stated worded portion — a
    household measure, a colloquial measure word, or an indefinite-article measure
    (FTY-275). A bare identity with no stated portion ("some crackers", "some milk",
    bare "milk") returns ``False`` so it still routes to clarification.
    """

    if amount is not None and amount > 0:
        return True
    text = quantity_text or ""
    if parse_range_midpoint(text) is not None:
        return True
    if parse_leading_count(text) is not None:
        return True
    return _states_worded_portion(text)


def _states_worded_portion(quantity_text: str) -> bool:
    """Whether ``quantity_text`` states a household / colloquial / indefinite portion.

    Pure and total: a household unit token, a colloquial measure word, or a leading
    indefinite article ("a"/"an" + a following word) each mean the user stated a
    portion in words. A bare identity with none of these returns ``False``.
    """

    words = frozenset(_WORD_RE.findall(quantity_text.lower()))
    if words & _HOUSEHOLD_UNIT_WORDS or words & _COLLOQUIAL_MEASURE_WORDS:
        return True
    return _INDEFINITE_MEASURE_RE.search(quantity_text) is not None
