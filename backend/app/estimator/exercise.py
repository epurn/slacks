"""Deterministic MET-based active-calorie calculator (FTY-043).

Pure functions, no I/O, no LLM: an activity description, the user's body weight,
and a logged duration in, **net active calories** out. The MET value comes from the
curated :mod:`app.estimator.met_table` (never from the model); this module owns the
duration parsing, the burn formula, and the boundary validation.

When a log states a distance, a step count, or a game count instead of a duration
(FTY-167), the duration is inferred from a documented, evidence-based assumption
(pace / cadence / per-game minutes) recorded on the run, so a detail-rich entry is
costed deterministically rather than sent to clarification.

The net-active convention
-------------------------

Gross active energy for an activity is the textbook MET identity ``1 MET ≈ 1
kcal/kg/hour``::

    gross_kcal = MET × weight_kg × duration_hours

But Fatty's daily allowance already counts resting energy in TDEE (RMR × the
baseline activity multiplier; see :mod:`app.estimator.calculator`). Adding the
*gross* burn on top would double-count the resting component the user would have
spent anyway. We therefore credit only the energy **above rest** — the ``(MET − 1)``
adjustment, since 1 MET is rest::

    net_active_kcal = (MET − 1) × weight_kg × duration_hours

This is the documented convention chosen to align with the FTY-022 TDEE model.

Failure modes are deterministic and typed so the pipeline step can route them: an
activity the curated table cannot match (:class:`UnknownActivityError`) or a
missing/zero/implausible duration (:class:`InvalidDurationError`) are ambiguities
the user can resolve (``needs_clarification``); a missing body weight
(:class:`MissingBodyWeightError`) is an incomplete profile that fails closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.estimator.detail_signals import distance_km, game_count, step_count
from app.estimator.met_table import MetEntry, lookup_met

#: Resting metabolic rate expressed in MET. 1 MET is rest by definition, so it is
#: the amount subtracted from an activity's MET to credit only energy above rest.
RESTING_MET: Final[float] = 1.0

#: Minimum and maximum plausible logged duration, in minutes. A non-positive
#: duration cannot have burned energy and an implausibly long one (> 24 h) is far
#: likelier a parse error than a real session; both are rejected for clarification
#: rather than silently producing a bogus or zero burn.
MIN_DURATION_MINUTES: Final[float] = 0.0
MAX_DURATION_MINUTES: Final[float] = 24.0 * 60.0

#: Plausible body-weight band (kg), matching the profile boundary validation. A
#: weight outside this band is treated as missing/invalid rather than trusted.
MIN_WEIGHT_KG: Final[float] = 0.0
MAX_WEIGHT_KG: Final[float] = 1000.0

#: Human-readable description of the net-active formula, recorded as run evidence.
NET_ACTIVE_FORMULA: Final[str] = "net_active_kcal = (MET - 1) * weight_kg * duration_hours"

#: Minutes per recognised time unit, used to normalise a duration to minutes.
_TIME_UNIT_MINUTES: Final[dict[str, float]] = {
    "s": 1.0 / 60.0,
    "sec": 1.0 / 60.0,
    "secs": 1.0 / 60.0,
    "second": 1.0 / 60.0,
    "seconds": 1.0 / 60.0,
    "m": 1.0,
    "min": 1.0,
    "mins": 1.0,
    "minute": 1.0,
    "minutes": 1.0,
    "h": 60.0,
    "hr": 60.0,
    "hrs": 60.0,
    "hour": 60.0,
    "hours": 60.0,
}

#: Match a leading number then a time unit inside a free-text quantity phrase
#: ("30 min", "1.5 hours", "45m"). Used only as a fallback when the structured
#: unit/amount do not already give a duration.
_DURATION_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+(?:\.\d+)?)\s*(seconds|second|secs|sec|minutes|minute|mins|min|hours|hour|hrs|hr|[smh])\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Quantity → duration conversions (FTY-167).
#
# When a log states a distance, a step count, or a game count instead of a
# duration, the calculator infers the duration from a documented, evidence-based
# assumption so a detail-rich entry ("ran 5 km", "walked 13000 steps", "played 3
# games of badminton") is costed deterministically rather than sent to
# clarification. Each conversion records a content-free assumption string so the
# inference is visible on the estimation run. All values are documented tunables.
# ---------------------------------------------------------------------------

#: Walking cadence for a step-count → duration conversion, in steps per minute.
#: ~100 steps/min is the widely cited threshold for moderate-intensity walking
#: (Tudor-Locke et al., "How many steps/day are enough?", IJBNPA 2011), matching
#: the moderate "walking, 3.0 mph" MET entry. 13 000 steps ÷ 100 ≈ 130 min.
STEPS_PER_MINUTE: Final[float] = 100.0

#: Representative pace (kilometres per hour) for a distance → duration conversion,
#: keyed by curated MET-table activity. Values are common recreational speeds:
#: walking ~5 km/h (≈3.1 mph, the moderate "walking, 3.0 mph" entry), running
#: ~10 km/h (≈6 mph recreational jog), swimming ~2.5 km/h (moderate freestyle).
#: An activity with no documented pace here cannot be costed from distance alone.
PACE_KM_PER_HOUR: Final[dict[str, float]] = {
    "walking": 5.0,
    "running": 10.0,
    "swimming": 2.5,
}

#: Representative duration (minutes) of one game/match, keyed by curated activity,
#: for a game-count → duration conversion. A casual badminton game to 21 (rally
#: scoring) runs ~10–20 min; 15 min is the documented midpoint. An activity with
#: no documented per-game duration cannot be costed from a game count.
GAME_DURATION_MINUTES: Final[dict[str, float]] = {
    "badminton": 15.0,
}


class ExerciseCalculationError(Exception):
    """Base for deterministic exercise-resolution failures, carrying a sanitized reason.

    ``reason`` is a short, fixed label (never raw user text) suitable for persisting
    on the estimation run and for routing the pipeline outcome.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UnknownActivityError(ExerciseCalculationError):
    """The activity description has no confident match in the curated MET table."""


class InvalidDurationError(ExerciseCalculationError):
    """The logged duration is missing, zero/negative, or implausibly large."""


class MissingBodyWeightError(ExerciseCalculationError):
    """The user's profile has no usable body weight, so a burn cannot be computed."""


@dataclass(frozen=True)
class ExerciseBurn:
    """The resolved burn for one exercise candidate.

    ``active_calories`` is the net (``MET − 1``) burn rounded to 0.1 kcal;
    ``met`` / ``met_key`` / ``duration_minutes`` are the evidence behind it.
    ``assumptions`` holds any documented conversion the duration was inferred
    from (distance/steps/games → minutes); it is empty when the user stated a
    duration directly.
    """

    met_key: str
    met: float
    duration_minutes: float
    active_calories: float
    assumptions: tuple[str, ...] = ()


def net_active_calories(met: float, weight_kg: float, duration_minutes: float) -> float:
    """Net active calories for ``duration_minutes`` of a ``met``-MET activity.

    Applies the ``(MET − 1)`` net convention (see the module docstring) and rounds
    to 0.1 kcal. Pure and total: callers validate inputs first via
    :func:`resolve_exercise`; this only computes.
    """

    hours = duration_minutes / 60.0
    net = (met - RESTING_MET) * weight_kg * hours
    return round(net, 1)


def parse_duration_minutes(
    unit: str | None, amount: float | None, quantity_text: str
) -> float | None:
    """Derive a duration in minutes from the candidate's fields, or ``None``.

    Prefers the structured ``amount`` when ``unit`` is a recognised time unit; a
    non-time unit (e.g. ``"km"``, ``"reps"``) is not trusted as a duration. Falls
    back to scanning ``quantity_text`` for a ``"<number> <time-unit>"`` phrase.
    Returns ``None`` when no duration can be determined.
    """

    if amount is not None and unit is not None:
        per_minute = _TIME_UNIT_MINUTES.get(unit.strip().lower())
        if per_minute is not None:
            return amount * per_minute

    match = _DURATION_TEXT_RE.search(quantity_text)
    if match is not None:
        value = float(match.group(1))
        per_minute = _TIME_UNIT_MINUTES[match.group(2).lower()]
        return value * per_minute

    return None


def resolve_duration(
    entry: MetEntry, unit: str | None, amount: float | None, quantity_text: str
) -> tuple[float, tuple[str, ...]]:
    """Derive a duration (minutes) for ``entry`` plus any inference assumptions.

    Resolution order, first hit wins:

    1. an explicit duration (the user stated minutes/hours) — no assumption;
    2. a **distance** → duration via the activity's documented pace;
    3. a **step count** → walking duration via the documented cadence;
    4. a **game count** → duration via the activity's documented per-game minutes.

    Raises :class:`InvalidDurationError` (``missing_duration``) when none apply, so
    the caller routes to ``needs_clarification`` rather than guessing. Each inferred
    conversion returns a content-free assumption string (numbers + the curated
    activity key only — never raw diary text) so the inference is visible on the run.
    """

    explicit = parse_duration_minutes(unit, amount, quantity_text)
    if explicit is not None:
        return explicit, ()

    distance = distance_km(unit, amount, quantity_text)
    if distance is not None:
        pace = PACE_KM_PER_HOUR.get(entry.key)
        if pace is not None:
            minutes = distance / pace * 60.0
            assumption = (
                f"distance→duration: {distance:g} km ÷ {pace:g} km/h "
                f"= {round(minutes, 1):g} min ({entry.key})"
            )
            return minutes, (assumption,)

    steps = step_count(unit, amount, quantity_text)
    if steps is not None:
        minutes = steps / STEPS_PER_MINUTE
        assumption = (
            f"steps→duration: {steps:g} steps ÷ {STEPS_PER_MINUTE:g} steps/min "
            f"= {round(minutes, 1):g} min (walking cadence)"
        )
        return minutes, (assumption,)

    games = game_count(unit, amount, quantity_text)
    if games is not None:
        per_game = GAME_DURATION_MINUTES.get(entry.key)
        if per_game is not None:
            minutes = games * per_game
            assumption = (
                f"games→duration: {games:g} × {per_game:g} min/game "
                f"= {round(minutes, 1):g} min ({entry.key})"
            )
            return minutes, (assumption,)

    raise InvalidDurationError("missing_duration")


def has_exercise_detail(unit: str | None, amount: float | None, quantity_text: str) -> bool:
    """Whether an exercise candidate carries a quantity that can yield a duration.

    ``True`` when an explicit duration, a distance, a step count, or a game count is
    present. Used by the parse step to keep a detail-rich exercise log ("ran 5 km")
    out of clarification even when the model's confidence was conservative; the
    calculator still fails closed later if the activity is unknown or the inferred
    duration is implausible.
    """

    return (
        parse_duration_minutes(unit, amount, quantity_text) is not None
        or distance_km(unit, amount, quantity_text) is not None
        or step_count(unit, amount, quantity_text) is not None
        or game_count(unit, amount, quantity_text) is not None
    )


def _validated_duration(duration_minutes: float | None) -> float:
    """Return a duration that is present and within the plausible band, or raise."""

    if duration_minutes is None:
        raise InvalidDurationError("missing_duration")
    if duration_minutes <= MIN_DURATION_MINUTES:
        raise InvalidDurationError("non_positive_duration")
    if duration_minutes > MAX_DURATION_MINUTES:
        raise InvalidDurationError("implausible_duration")
    return duration_minutes


def _validated_weight(weight_kg: float | None) -> float:
    """Return a body weight that is present and plausible, or raise."""

    if weight_kg is None or weight_kg <= MIN_WEIGHT_KG or weight_kg > MAX_WEIGHT_KG:
        raise MissingBodyWeightError("missing_body_weight")
    return weight_kg


def resolve_exercise(
    *,
    activity: str,
    weight_kg: float | None,
    unit: str | None,
    amount: float | None,
    quantity_text: str,
) -> ExerciseBurn:
    """Resolve one exercise candidate into a net active-calorie burn.

    Raises :class:`UnknownActivityError` when the activity is not in the curated MET
    table, :class:`InvalidDurationError` for a missing/zero/implausible duration, and
    :class:`MissingBodyWeightError` when the profile has no usable weight. Otherwise
    returns the deterministic :class:`ExerciseBurn`.
    """

    entry: MetEntry | None = lookup_met(activity)
    if entry is None:
        raise UnknownActivityError("unknown_activity")

    duration_minutes, assumptions = resolve_duration(entry, unit, amount, quantity_text)
    duration = _validated_duration(duration_minutes)
    weight = _validated_weight(weight_kg)

    return ExerciseBurn(
        met_key=entry.key,
        met=entry.met,
        duration_minutes=duration,
        active_calories=net_active_calories(entry.met, weight, duration),
        assumptions=assumptions,
    )
