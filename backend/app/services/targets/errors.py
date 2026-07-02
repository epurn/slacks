"""Target service errors.

The fail-closed / reject-not-clamp discipline these exceptions encode is the
security-sensitive core of the target surface (see ``target-calculator.md``):
cross-user access and a missing target are indistinguishable (no existence
oracle), and an out-of-band manual override is refused honestly rather than
silently altered.
"""

from __future__ import annotations


class GoalForbidden(Exception):
    """Raised when a caller tries to act on a goal they do not own."""


class TargetNotFound(Exception):
    """Raised when no overridable target row exists for the caller's active goal.

    Rendered as the same fail-closed ``404`` as :class:`GoalForbidden` so a
    cross-user caller and a caller with no active goal / no stored target are
    indistinguishable (no existence oracle).
    """


class OverrideOutOfBand(Exception):
    """Raised when a manual override falls outside its documented safety band.

    Carries the offending field and the band so the router can return a clear
    ``422`` — the user sees their value refused, not silently clamped.
    """

    def __init__(self, field: str, value: int, low: int, high: int) -> None:
        super().__init__(f"{field} override {value} is outside the allowed band [{low}, {high}]")
        self.field = field
        self.value = value
        self.low = low
        self.high = high


class IncompleteProfileError(Exception):
    """Raised when the profile is missing a field the calculator requires."""
