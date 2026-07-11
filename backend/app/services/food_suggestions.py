"""Contextual food-suggestion read model (FTY-340).

The service ranks a user's own saved foods and completed food-history labels with
a deterministic, time-aware frecency score. It is deliberately read-only and has
no provider, LLM, or network dependency: all inputs are existing database rows
scoped to the caller.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import DerivedItemStatus, LogEventStatus
from app.models.derived import DerivedFoodItem
from app.models.identity import User
from app.models.log_events import LogEvent
from app.models.saved_foods import FoodAlias, SavedFood
from app.normalization import normalize_text
from app.schemas.food_suggestions import FoodSuggestionDTO
from app.timeutils import user_timezone

#: Only recent-enough history is read so endpoint work stays bounded.
HISTORY_WINDOW_DAYS = 120
#: Exponential recency half-life. Fourteen days keeps recent habits dominant
#: while still allowing regular older foods to contribute.
RECENCY_HALF_LIFE_DAYS = 14.0
#: Local-time kernel plateau around the request hour.
HOUR_KERNEL_FULL_WEIGHT_MINUTES = 90
#: Local-time distance where the hour kernel reaches its floor.
HOUR_KERNEL_FLOOR_DISTANCE_MINUTES = 240
#: Minimum hour-kernel contribution for off-hour occurrences, so strong all-day
#: favorites can still surface.
HOUR_KERNEL_FLOOR = 0.15
#: Additive smoothing for weekday/weekend affinity. This pulls sparse candidates
#: toward plain frecency rather than overfitting one weekend or weekday log.
DAY_TYPE_SMOOTHING = 2.0
#: Scores are rounded for the debugging field in the response, but sorting uses
#: the unrounded score.
SCORE_DECIMAL_PLACES = 4

_MINUTES_PER_DAY = 24 * 60
_WEEKEND_START_WEEKDAY = 5


@dataclass
class _Occurrence:
    happened_at: datetime


@dataclass
class _Candidate:
    label: str
    submit_phrase: str
    saved_food_id: uuid.UUID | None
    normalized_label: str
    normalized_forms: set[str] = field(default_factory=set)
    occurrences: list[_Occurrence] = field(default_factory=list)

    @property
    def most_recent(self) -> datetime:
        return max(occurrence.happened_at for occurrence in self.occurrences)


def get_food_suggestions(
    session: Session,
    current_user: User,
    *,
    now: datetime,
    limit: int,
) -> list[FoodSuggestionDTO]:
    """Return ranked suggestions for ``current_user`` at ``now``.

    ``now`` is injected by the route so tests can pin exact local moments. The
    scoring path never reads the wall clock directly. Returned labels and submit
    phrases come only from the user's own saved-food rows or completed history.
    """

    owner_id = current_user.id
    now_utc = _as_utc(now)
    tz = user_timezone(session, owner_id)
    request_local = now_utc.astimezone(tz)
    history_start_utc = (request_local - timedelta(days=HISTORY_WINDOW_DAYS)).astimezone(UTC)

    candidates: dict[str, _Candidate] = {}
    saved_form_index = _load_saved_candidates(session, owner_id, candidates)
    _load_history_candidates(session, owner_id, history_start_utc, candidates, saved_form_index)

    scored: list[tuple[float, _Candidate]] = []
    for candidate in candidates.values():
        if not candidate.occurrences:
            continue
        score = _score_candidate(candidate, now_utc, request_local, tz)
        if score > 0:
            scored.append((score, candidate))

    scored.sort(
        key=lambda pair: (
            -pair[0],
            -pair[1].most_recent.timestamp(),
            pair[1].normalized_label,
            str(pair[1].saved_food_id or ""),
        )
    )
    return [
        FoodSuggestionDTO(
            label=candidate.label,
            submit_phrase=candidate.submit_phrase,
            saved_food_id=candidate.saved_food_id,
            score=round(score, SCORE_DECIMAL_PLACES),
        )
        for score, candidate in scored[:limit]
    ]


def _load_saved_candidates(
    session: Session,
    owner_id: uuid.UUID,
    candidates: dict[str, _Candidate],
) -> dict[str, str]:
    """Load saved-food candidates and return normalized form -> candidate key."""

    saved_foods = list(
        session.scalars(
            select(SavedFood)
            .where(SavedFood.user_id == owner_id)
            .order_by(SavedFood.name_normalized, SavedFood.id)
        )
    )
    aliases_by_saved_id = _load_aliases(session, owner_id)
    form_index: dict[str, str] = {}

    for saved_food in saved_foods:
        key = f"saved:{saved_food.id}"
        aliases = aliases_by_saved_id.get(saved_food.id, [])
        submit_phrase = aliases[0].alias if aliases else saved_food.name
        normalized_forms = {saved_food.name_normalized}
        normalized_forms.update(alias.alias_normalized for alias in aliases)
        candidate = _Candidate(
            label=saved_food.name,
            submit_phrase=submit_phrase,
            saved_food_id=saved_food.id,
            normalized_label=saved_food.name_normalized,
            normalized_forms={form for form in normalized_forms if form},
            occurrences=[_Occurrence(_as_utc(saved_food.created_at))],
        )
        candidates[key] = candidate
        for form in sorted(candidate.normalized_forms):
            form_index.setdefault(form, key)
    return form_index


def _load_aliases(session: Session, owner_id: uuid.UUID) -> dict[uuid.UUID, list[FoodAlias]]:
    aliases = list(
        session.scalars(
            select(FoodAlias)
            .where(FoodAlias.user_id == owner_id)
            .order_by(FoodAlias.saved_food_id, FoodAlias.created_at, FoodAlias.alias, FoodAlias.id)
        )
    )
    by_saved_id: dict[uuid.UUID, list[FoodAlias]] = {}
    for alias in aliases:
        by_saved_id.setdefault(alias.saved_food_id, []).append(alias)
    return by_saved_id


def _load_history_candidates(
    session: Session,
    owner_id: uuid.UUID,
    history_start_utc: datetime,
    candidates: dict[str, _Candidate],
    saved_form_index: dict[str, str],
) -> None:
    rows = session.execute(
        select(DerivedFoodItem.name, LogEvent.created_at)
        .join(LogEvent, LogEvent.id == DerivedFoodItem.log_event_id)
        .where(
            DerivedFoodItem.user_id == owner_id,
            LogEvent.user_id == owner_id,
            LogEvent.status == LogEventStatus.COMPLETED,
            LogEvent.voided_at.is_(None),
            DerivedFoodItem.status == DerivedItemStatus.RESOLVED,
            LogEvent.created_at >= history_start_utc,
        )
        .order_by(LogEvent.created_at.desc(), DerivedFoodItem.name, DerivedFoodItem.id)
    ).all()

    for label, happened_at in rows:
        normalized_label = normalize_text(label)
        if not normalized_label:
            continue
        candidate_key = saved_form_index.get(normalized_label)
        if candidate_key is None:
            candidate_key = f"history:{normalized_label}"
            if candidate_key not in candidates:
                clean_label = label.strip()
                candidates[candidate_key] = _Candidate(
                    label=clean_label,
                    submit_phrase=clean_label,
                    saved_food_id=None,
                    normalized_label=normalized_label,
                    normalized_forms={normalized_label},
                )
        candidate = candidates[candidate_key]
        candidate.occurrences.append(_Occurrence(_as_utc(happened_at)))
        if candidate.saved_food_id is None and _as_utc(happened_at) >= candidate.most_recent:
            clean_label = label.strip()
            candidate.label = clean_label
            candidate.submit_phrase = clean_label


def _score_candidate(
    candidate: _Candidate,
    now_utc: datetime,
    request_local: datetime,
    tz: ZoneInfo,
) -> float:
    request_day_type = _day_type(request_local)
    occurrence_locals = [
        occurrence.happened_at.astimezone(tz) for occurrence in candidate.occurrences
    ]
    matching_day_type_count = sum(
        1
        for occurrence_local in occurrence_locals
        if _day_type(occurrence_local) == request_day_type
    )
    day_type_weight = _day_type_weight(matching_day_type_count, len(occurrence_locals))
    return sum(
        _recency_decay(occurrence.happened_at, now_utc)
        * _hour_kernel(occurrence_local, request_local)
        * day_type_weight
        for occurrence, occurrence_local in zip(
            candidate.occurrences, occurrence_locals, strict=True
        )
    )


def _recency_decay(happened_at: datetime, now_utc: datetime) -> float:
    age = max(timedelta(0), now_utc - happened_at)
    age_days = age.total_seconds() / 86_400
    return math.pow(0.5, age_days / RECENCY_HALF_LIFE_DAYS)


def _hour_kernel(occurrence_local: datetime, request_local: datetime) -> float:
    distance = _circular_minute_distance(
        occurrence_local.hour * 60 + occurrence_local.minute,
        request_local.hour * 60 + request_local.minute,
    )
    if distance <= HOUR_KERNEL_FULL_WEIGHT_MINUTES:
        return 1.0
    if distance >= HOUR_KERNEL_FLOOR_DISTANCE_MINUTES:
        return HOUR_KERNEL_FLOOR
    span = HOUR_KERNEL_FLOOR_DISTANCE_MINUTES - HOUR_KERNEL_FULL_WEIGHT_MINUTES
    remaining = HOUR_KERNEL_FLOOR_DISTANCE_MINUTES - distance
    return HOUR_KERNEL_FLOOR + (1.0 - HOUR_KERNEL_FLOOR) * (remaining / span)


def _day_type_weight(matching_day_type_count: int, total_count: int) -> float:
    match_probability = (matching_day_type_count + DAY_TYPE_SMOOTHING) / (
        total_count + 2 * DAY_TYPE_SMOOTHING
    )
    return match_probability / 0.5


def _circular_minute_distance(left: int, right: int) -> int:
    raw_distance = abs(left - right)
    return min(raw_distance, _MINUTES_PER_DAY - raw_distance)


def _day_type(value: datetime) -> str:
    return "weekend" if value.weekday() >= _WEEKEND_START_WEEKDAY else "weekday"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
