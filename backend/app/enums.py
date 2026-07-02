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


class PacePreset(StrEnum):
    """Evidence-based weight-change pace presets (FTY-106).

    Onboarding collects a *direction* and a *pace preset*, never a free-form
    numeric rate, so an unsafe rate is structurally impossible at the API
    boundary. Each preset maps to a weekly rate expressed as a fraction of start
    weight (see :data:`app.services.goals.PACE_WEEKLY_FRACTION`):

    - :attr:`GENTLE` — the most conservative rate.
    - :attr:`STEADY` — the recommended default (~0.5%/wk loss, ~0.25%/wk gain).
    - :attr:`FASTER` — the loss-only cap (~1%/wk); never the default. Gain offers
      no faster preset because lean-mass gain is intrinsically slow.

    The evidence: a safe, lean-mass-sparing loss rate is ~0.5–1%/wk; above
    ~1.5%/wk measurably increases lean-mass loss, so no preset exceeds ~1%/wk.
    Lean gain is far slower (~0.125–0.25%/wk).
    """

    GENTLE = "gentle"
    STEADY = "steady"
    FASTER = "faster"


class ClampReason(StrEnum):
    """Why a derived daily calorie target was clamped to a safety boundary (FTY-106).

    The calculator clamps a target that falls outside the documented safety band
    to the nearest boundary and flags it. This token lets the target-reveal say
    *which* boundary was hit, so the client can show a calm note rather than
    presenting a clamped number as the achievable plan.

    - :attr:`CLAMPED_TO_FLOOR` — the derived target fell below the safety floor
      (the plan is more aggressive than is safe) and was raised to the floor.
    - :attr:`CLAMPED_TO_CEILING` — the derived target rose above the safety
      ceiling and was lowered to the ceiling.
    """

    CLAMPED_TO_FLOOR = "clamped_to_floor"
    CLAMPED_TO_CEILING = "clamped_to_ceiling"


class TargetBasis(StrEnum):
    """The stable basis token for a target's provenance (FTY-106).

    Paired with :class:`TargetSource` in the target-reveal ``provenance`` object:
    ``source`` says *how* the value was produced (derived vs. a user override),
    ``basis`` names *what it was derived from*. The human line ("from your goal +
    your metrics") is the client's; the API carries this stable token.

    - :attr:`GOAL_AND_METRICS` — the value was computed from the user's goal
      trajectory and profile body metrics.
    """

    GOAL_AND_METRICS = "goal_and_metrics"


class TargetSource(StrEnum):
    """Provenance of an effective target value (FTY-095).

    Every target the read-model exposes carries this flag so a consumer can
    honestly distinguish a number Fatty derived from the user's goal + metrics
    from one the user set by hand:

    - :attr:`DERIVED` — the value comes from the deterministic calculator
      (``daily_targets`` derived columns); a reset is a no-op.
    - :attr:`USER` — the user manually overrode the value; the derived value is
      still reported (what a reset would restore) but the effective value and
      ``source`` come from the override.
    """

    DERIVED = "derived"
    USER = "user"


class OverridableTarget(StrEnum):
    """The four independently overridable daily targets (FTY-095).

    Names the targets a user can manually set or reset, one at a time or in any
    combination: the calorie target and each of the three macro-gram targets.
    """

    CALORIES = "calories"
    PROTEIN = "protein"
    CARBS = "carbs"
    FAT = "fat"


class UnitsPreference(StrEnum):
    """Display-unit preference. Storage is always canonical (kg, m)."""

    METRIC = "metric"
    IMPERIAL = "imperial"


class LogEventStatus(StrEnum):
    """Lifecycle status of a raw log event (FTY-030).

    This is the canonical v1 status vocabulary for the log-event state machine.
    A new event starts at :attr:`PENDING`; the estimator pipeline (Milestone 4)
    drives it through :attr:`PROCESSING` to a terminal :attr:`COMPLETED`,
    :attr:`FAILED`, or :attr:`NEEDS_CLARIFICATION`. The legal transitions between
    these statuses are the named state-machine contract in
    :mod:`app.services.log_events`; later stories extend that map rather than
    redefining the vocabulary here.

    FTY-030 implements creation at :attr:`PENDING` and the
    ``PENDING → COMPLETED`` transition only; the remaining transitions are
    reserved for the estimator stories.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


class EstimationJobStatus(StrEnum):
    """Lifecycle status of an estimation job (FTY-040).

    One :class:`~app.models.estimation.EstimationJob` exists per log event (the
    idempotency anchor); its status tracks the worker's progress independently of
    the user-facing :class:`LogEventStatus`:

    - :attr:`QUEUED` — created on enqueue, not yet picked up.
    - :attr:`RUNNING` — claimed by a worker; also the resting state between
      retries while attempts remain.
    - :attr:`SUCCEEDED` / :attr:`FAILED` / :attr:`NEEDS_CLARIFICATION` — terminal
      outcomes. A terminal job is never reprocessed, which is what makes
      re-delivery of the same task a no-op.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


#: Terminal estimation-job statuses. A job in one of these is fully resolved, so
#: re-delivering its task must not create a new run or re-advance the event.
TERMINAL_JOB_STATUSES: frozenset[EstimationJobStatus] = frozenset(
    {
        EstimationJobStatus.SUCCEEDED,
        EstimationJobStatus.FAILED,
        EstimationJobStatus.NEEDS_CLARIFICATION,
    }
)


class EstimationRunStatus(StrEnum):
    """Outcome of a single estimation attempt (FTY-040).

    An :class:`~app.models.estimation.EstimationRun` is the auditable record of
    one attempt at the estimation pipeline. :attr:`RUNNING` is written when the
    run starts; the pipeline outcome rewrites it to :attr:`COMPLETED`,
    :attr:`FAILED`, or :attr:`NEEDS_CLARIFICATION`. A failed attempt that still
    has retries left leaves a :attr:`FAILED` run behind and a fresh run is created
    for the next attempt, so the run history is the full audit trail.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


class CandidateType(StrEnum):
    """Kind of a parsed estimation candidate (FTY-042).

    The structured parse step classifies each extracted item as :attr:`FOOD` or
    :attr:`EXERCISE`. The two kinds persist into separate derived-item tables, so
    this discriminator is the shared vocabulary for both the LLM output schema and
    the routing that splits candidates into ``derived_food_items`` /
    ``derived_exercise_items``.
    """

    FOOD = "food"
    EXERCISE = "exercise"


class DerivedItemStatus(StrEnum):
    """Resolution status of a derived food/exercise item (FTY-042, FTY-196).

    A candidate is persisted :attr:`UNRESOLVED` — parsed from the log text but not
    yet costed. The calculation steps (FTY-043 exercise burn, FTY-044 food
    resolution) later attach calories/macros and advance it to :attr:`RESOLVED`.
    FTY-042 only ever writes :attr:`UNRESOLVED`.

    :attr:`PROPOSED` (FTY-196) is a costed-but-**unconfirmed** food item: a legible
    nutrition-label parse holds its computed calories/macros in this state instead
    of :attr:`RESOLVED`, because "OCR is fallible — Fatty never silently trusts a
    fallible parse" (``docs/design-philosophy.md``). A ``proposed`` item is excluded
    from every finalized-state read **by construction** (the daily-summary filter
    requires :attr:`RESOLVED`, see ``docs/contracts/daily-summary.md``), so it never
    counts toward totals; confirming the proposal transitions it ``proposed →
    resolved`` and it then counts. Only the label path writes :attr:`PROPOSED`; a
    text parse resolves straight to :attr:`RESOLVED` as before.

    ``status`` is persisted as a plain ``VARCHAR`` (not a database ``ENUM``), so
    adding :attr:`PROPOSED` is an application-only change with **no** schema
    migration — the value round-trips on both SQLite and Postgres unchanged.
    """

    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    PROPOSED = "proposed"


class CorrectionSource(StrEnum):
    """Origin of a ``corrections`` audit row (FTY-051, FTY-092).

    A correction records who/what changed a derived item's value:

    - :attr:`USER_EDIT` — a direct **value override** of ``calories`` / a macro /
      ``active_calories`` through the edit endpoint. It is the load-bearing signal
      for ``is_edited``: an item is *edited* iff it carries a ``user_edit`` correction
      not superseded by a later re-match (FTY-092/093).
    - :attr:`AMOUNT_ADJUST` — a **provenance-preserving portion change** (FTY-092):
      editing an item's ``quantity`` deterministically rescales calories/macros but
      keeps the item's resolved source intact and does **not** mark it edited. The
      rescaled rows are an honest audit trail tagged distinctly from a value override.
    - :attr:`RE_MATCH` — a **re-resolution to a different real source** (FTY-093): the
      "Change match" lever re-aims the item to a caller-chosen source and re-snapshots
      its numbers. It is **not** a value override, so it never marks the item edited;
      instead it **supersedes** any prior ``user_edit`` — ``is_edited`` is true only for
      a ``user_edit`` made *after* the latest re-match (the new source carries the
      honesty, not the stale override). See ``docs/contracts/evidence-retrieval.md``.

    Later learning/adaptation work (FTY-052+) may append other sources without
    redefining the append-only audit contract.
    """

    USER_EDIT = "user_edit"
    AMOUNT_ADJUST = "amount_adjust"
    RE_MATCH = "re_match"


class SourceType(StrEnum):
    """Evidence source-hierarchy classification for a resolved item (FTY-045/092).

    The canonical vocabulary recorded on each ``evidence_sources`` row's
    ``source_type`` (see ``docs/contracts/evidence-retrieval.md``). FTY-092 reads it
    into the per-item ``source`` descriptor the Today timeline renders, so the client
    maps a source icon + label without re-deriving the hierarchy. ``model_prior``
    surfaces a rough estimate plainly so the client can render the
    "≈ rough estimate · make it exact" treatment.
    """

    TRUSTED_NUTRITION_DATABASE = "trusted_nutrition_database"
    PRODUCT_DATABASE = "product_database"
    OFFICIAL_SOURCE = "official_source"
    USER_LABEL = "user_label"
    REFERENCE_SOURCE = "reference_source"
    MODEL_PRIOR = "model_prior"


class SavedFoodSource(StrEnum):
    """Provenance of a ``saved_foods`` row (FTY-052).

    A saved food is always created by a deliberate, user-initiated save. v1 only
    writes :attr:`SAVED_FROM_CORRECTION` — the food was saved from a corrected
    derived item (FTY-051). The field records *how* the food entered the user's
    saved set so later sources (e.g. a manual entry) can be added without
    redefining the contract.
    """

    SAVED_FROM_CORRECTION = "saved_from_correction"


#: Authentication provider for an :class:`~app.models.identity.AuthIdentity`.
#: Only the local email+password path exists in v1; hosted providers (e.g. Sign
#: in with Apple) are deferred to a later story but modelled as separate
#: identities against the same user.
class AuthProvider(StrEnum):
    """Authentication provider backing an auth identity."""

    LOCAL = "local"
