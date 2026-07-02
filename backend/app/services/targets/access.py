"""Object-level authorization for the target surface.

Every target access path is object-level authorized and fails closed: a caller
may only touch targets for *their own* goal (``user_id`` is the ownership key on
both ``goals`` and ``daily_targets``). Centralised here so every entry point
routes through the same fail-closed check.
"""

from __future__ import annotations

import uuid

from app.models.identity import User

from .errors import GoalForbidden


def authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s data."""

    if owner_id != current_user.id:
        raise GoalForbidden("cross-user goal access denied")
