"""Saved-foods + aliases service (FTY-052).

Owns the two behaviors behind the saved-foods contract:

1. **Deliberate save.** :func:`save_food` creates one :class:`~app.models.saved_foods.SavedFood`
   from a corrected nutrition snapshot plus one :class:`~app.models.saved_foods.FoodAlias`
   mapping the originating typed phrase to it. A save is always explicit and
   user-initiated; nothing auto-saves.

2. **Typeahead search.** :func:`search_saved_foods` returns the caller's own saved
   foods whose canonical name **or** any alias matches the query by normalized
   prefix/contains (:func:`app.normalization.normalize_text` — case-folded,
   diacritic- and whitespace-normalized). Matching is exact substring on the
   normalized form; there is no fuzzy or semantic step.

**Object-level authorization, fail-closed.** Both paths run through
:func:`_authorize`: the caller must own the targeted ``user_id``. A cross-user
request raises :class:`SavedFoodForbidden`, which the router renders ``404`` — a
non-owner never writes under, reads, or searches another user's foods, and the
collection's existence is never confirmed. Every query is additionally scoped to
the owner, so even a bug in the authorize check cannot widen the result set.

Alias text and query text are sensitive free-text the user typed; they are stored
as data and **never written to logs**.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.enums import SavedFoodSource
from app.models.identity import User
from app.models.saved_foods import FoodAlias, SavedFood
from app.normalization import normalize_text
from app.schemas.saved_foods import (
    DEFAULT_SEARCH_LIMIT,
    MAX_SEARCH_LIMIT,
    NutritionSnapshot,
)

#: The escape character used when building a LIKE pattern, so a query containing
#: LIKE wildcards (``%`` / ``_``) is matched literally rather than as a wildcard.
_LIKE_ESCAPE = "\\"


class SavedFoodForbidden(Exception):
    """Raised when a caller targets saved foods they do not own (fails closed)."""


def save_food(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    name: str,
    phrase: str,
    nutrition: NutritionSnapshot,
) -> SavedFood:
    """Save one corrected food under ``owner_id`` and map ``phrase`` to it.

    Creates exactly one ``saved_foods`` row from the corrected ``nutrition`` and one
    ``food_aliases`` row for the originating ``phrase``, committing them together so
    a saved food and its first alias always land atomically. Enforces ownership and
    fails closed on a cross-user save.
    """

    _authorize(owner_id, current_user)

    saved_food = SavedFood(
        user_id=owner_id,
        name=name,
        name_normalized=normalize_text(name),
        calories=nutrition.calories,
        protein_g=nutrition.protein_g,
        carbs_g=nutrition.carbs_g,
        fat_g=nutrition.fat_g,
        serving_size=nutrition.serving_size,
        serving_unit=nutrition.serving_unit,
        source=SavedFoodSource.SAVED_FROM_CORRECTION,
    )
    session.add(saved_food)
    # Flush so the alias can reference the saved food's generated id within the
    # same transaction.
    session.flush()

    alias = FoodAlias(
        user_id=owner_id,
        saved_food_id=saved_food.id,
        alias=phrase,
        alias_normalized=normalize_text(phrase),
    )
    session.add(alias)
    session.commit()
    session.refresh(saved_food)
    return saved_food


def search_saved_foods(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    query: str,
    limit: int | None = None,
) -> tuple[list[SavedFood], int]:
    """Return ``owner_id``'s saved foods matching ``query`` by normalized contains.

    Returns ``(items, applied_limit)``. The query is normalized, then matched as a
    literal substring against each saved food's ``name_normalized`` and the
    ``alias_normalized`` of any of its aliases. Results are deduplicated, ordered
    deterministically (normalized name, then id) and capped at ``applied_limit``
    (clamped to ``[1, MAX_SEARCH_LIMIT]``, default ``DEFAULT_SEARCH_LIMIT``). A
    query that normalizes to empty matches nothing. Fails closed on a cross-user
    search.
    """

    _authorize(owner_id, current_user)
    applied_limit = _clamp_limit(limit)

    normalized_query = normalize_text(query)
    if not normalized_query:
        # An all-whitespace/diacritic query has no normalized content to match;
        # return the user's own empty result rather than every saved food.
        return [], applied_limit

    pattern = f"%{_escape_like(normalized_query)}%"
    alias_match = (
        select(FoodAlias.saved_food_id)
        .where(
            FoodAlias.user_id == owner_id,
            FoodAlias.alias_normalized.like(pattern, escape=_LIKE_ESCAPE),
        )
        .scalar_subquery()
    )

    statement = (
        select(SavedFood)
        .where(
            SavedFood.user_id == owner_id,
            or_(
                SavedFood.name_normalized.like(pattern, escape=_LIKE_ESCAPE),
                SavedFood.id.in_(alias_match),
            ),
        )
        .order_by(SavedFood.name_normalized, SavedFood.id)
        .limit(applied_limit)
    )
    items = list(session.scalars(statement).all())
    return items, applied_limit


def _clamp_limit(limit: int | None) -> int:
    """Clamp a requested limit into ``[1, MAX_SEARCH_LIMIT]`` (default when ``None``)."""

    if limit is None:
        return DEFAULT_SEARCH_LIMIT
    return max(1, min(limit, MAX_SEARCH_LIMIT))


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so ``value`` matches literally.

    The escape character itself must be escaped first, then the ``%`` and ``_``
    wildcards, so a query such as ``50%`` searches for a literal percent sign.
    """

    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s saved foods."""

    if owner_id != current_user.id:
        raise SavedFoodForbidden("cross-user saved-food access denied")
