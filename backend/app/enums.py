"""Shared domain enums for the identity/profile contract.

These string enums are the canonical vocabulary for the profile contract and are
reused by both the ORM models (column validation) and the Pydantic boundary DTOs
so the persisted values and the API surface cannot drift apart.
"""

from __future__ import annotations

from enum import StrEnum


class MetabolicFormula(StrEnum):
    """Resting-metabolic-rate formula preference (FTY-022).

    Mifflin-St Jeor is the v1 RMR formula (see the system overview). The formula
    carries a sex-dependent additive constant, and the user's choice of that
    constant *is* the profile's metabolic-formula preference (captured by FTY-021
    with deliberately non-clinical wording, mapped by FTY-022's RMR calculator):

    - :attr:`MIFFLIN_ST_JEOR_PLUS_5` — the ``+5`` constant variant.
    - :attr:`MIFFLIN_ST_JEOR_MINUS_161` — the ``-161`` constant variant.

    :attr:`MIFFLIN_ST_JEOR` remains the *unspecified* family default for a
    freshly created, not-yet-captured profile: it names the formula but carries
    no constant, so RMR cannot be computed until the user selects a variant. The
    capture UI only ever writes one of the two variants, and those two are the
    only valid inputs to the target calculator (see
    :mod:`app.estimator.calculator`).
    """

    MIFFLIN_ST_JEOR = "mifflin_st_jeor"
    MIFFLIN_ST_JEOR_PLUS_5 = "mifflin_st_jeor_plus5"
    MIFFLIN_ST_JEOR_MINUS_161 = "mifflin_st_jeor_minus161"


class GoalDirection(StrEnum):
    """Direction of a weight goal, derived from start vs. target weight (FTY-022)."""

    LOSS = "loss"
    GAIN = "gain"
    MAINTAIN = "maintain"


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
