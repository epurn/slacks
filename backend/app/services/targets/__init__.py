"""Target service: derive, persist, and manually override daily targets.

Public facade for the target surface. The concerns are split across focused
submodules and re-exported here so routers and services keep importing
``app.services.targets`` unchanged:

- :mod:`.calculator_input` — normalise a profile + goal into the calculator's
  validated input (the estimator adapter).
- :mod:`.derivation` — run the deterministic calculator and upsert the derived
  ``daily_targets`` row.
- :mod:`.resolution` — active/exact-date and carried-forward target resolution,
  including the read entry point and on-demand row materialisation for writes.
- :mod:`.overrides` — the manual override lifecycle (set / reset).
- :mod:`.override_rules` — row-level override + derived-column rules (band
  validation, carry-forward).
- :mod:`.read_model` — project a row to the derived-vs-overridden read-model.
- :mod:`.access` / :mod:`.errors` — object-level authorization and the
  fail-closed error taxonomy.

Override lifecycle (the documented invariant, see ``target-calculator.md``):

- The override lives on ``daily_targets`` beside the derived columns. The
  effective value is a pure read-time ``override ?? derived``.
- A derived **recompute** (goal/pace/metric edit) refreshes the derived columns in
  place and **leaves any in-force override untouched**; when a recompute
  materialises a row for a *new* date it carries the goal's in-force override
  forward so the choice does not silently lapse on a date rollover.
- An override is cleared **only** by an explicit reset or by deletion/replacement
  of the owning goal (``ON DELETE CASCADE`` from ``goal_id``).
- A manual override is validated against the documented safety band and an
  out-of-band value is **rejected** (not silently clamped like the derived path):
  the user's explicit number is refused honestly, never quietly altered.

Every access path is object-level authorized and fails closed: a caller may only
touch targets for *their own* goal. Target numbers are sensitive derived body
data and are never logged — only user/goal ids appear in any diagnostic.
"""

from __future__ import annotations

from .calculator_input import build_calculator_input, derive_age_years
from .derivation import compute_daily_target
from .errors import (
    GoalForbidden,
    IncompleteProfileError,
    OverrideOutOfBand,
    TargetNotFound,
)
from .overrides import reset_target_override, set_target_override
from .read_model import build_target_read_model
from .resolution import (
    _resolve_active_target,
    get_active_target,
    resolve_active_target_row,
    resolve_carried_target_row,
)

__all__ = [
    "GoalForbidden",
    "IncompleteProfileError",
    "OverrideOutOfBand",
    "TargetNotFound",
    "_resolve_active_target",
    "build_calculator_input",
    "build_target_read_model",
    "compute_daily_target",
    "derive_age_years",
    "get_active_target",
    "reset_target_override",
    "resolve_active_target_row",
    "resolve_carried_target_row",
    "set_target_override",
]
