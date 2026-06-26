"""Shared domain enums for the identity/profile contract.

These string enums are the canonical vocabulary for the profile contract and are
reused by both the ORM models (column validation) and the Pydantic boundary DTOs
so the persisted values and the API surface cannot drift apart.
"""

from __future__ import annotations

from enum import StrEnum


class MetabolicFormula(StrEnum):
    """Resting-metabolic-rate formula preference.

    Mifflin-St Jeor is the v1 default (see the system overview); the enum leaves
    room for the additional formulas a later target story may offer.
    """

    MIFFLIN_ST_JEOR = "mifflin_st_jeor"


class UnitsPreference(StrEnum):
    """Display-unit preference. Storage is always canonical (kg, m)."""

    METRIC = "metric"
    IMPERIAL = "imperial"


#: Authentication provider for an :class:`~app.models.identity.AuthIdentity`.
#: Only the local email+password path exists in v1; hosted providers (e.g. Sign
#: in with Apple) are deferred to a later story but modelled as separate
#: identities against the same user.
class AuthProvider(StrEnum):
    """Authentication provider backing an auth identity."""

    LOCAL = "local"
