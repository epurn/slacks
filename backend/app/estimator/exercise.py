"""Deterministic MET-based active-calorie calculator (FTY-043).

Pure functions, no I/O, no LLM: an activity description, the user's body weight,
and a logged duration in, **net active calories** out. The MET value comes from the
curated :mod:`app.estimator.met_table` (never from the model); this module owns the
duration parsing, the burn formula, and the boundary validation.

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
    """

    met_key: str
    met: float
    duration_minutes: float
    active_calories: float


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

    duration = _validated_duration(parse_duration_minutes(unit, amount, quantity_text))
    weight = _validated_weight(weight_kg)

    return ExerciseBurn(
        met_key=entry.key,
        met=entry.met,
        duration_minutes=duration,
        active_calories=net_active_calories(entry.met, weight, duration),
    )
