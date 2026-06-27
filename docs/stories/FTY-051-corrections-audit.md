---
id: FTY-051
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
review_focus:
  - object-level-authz
  - audit-immutability
  - deterministic-rescale-math
  - migration-rollback
  - input-validation
risk: high
tags:
  - corrections
  - audit
  - api
  - contracts
  - nutrition-data
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-051: Corrections Audit + Edit Endpoint

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- FTY-030
- FTY-042
- FTY-043
- FTY-044

## Outcome

A user can correct a derived food or exercise item's value through the API, and every edit preserves the estimator's original value and appends an immutable audit record instead of silently overwriting the estimate. This is the backend foundation for editing (FTY-050) and learning (FTY-052).

## Scope

- Add snapshot columns to the derived item tables so each editable estimator value carries both an immutable original and an editable current value:
  - `derived_food_items`: snapshot the original estimated calories and macros (e.g. `calories_estimated`, `protein_estimated`, `carbs_estimated`, `fat_estimated`) alongside the existing editable current fields (`calories`, `protein`, `carbs`, `fat`) from FTY-044.
  - `derived_exercise_items`: snapshot the original estimated burn (e.g. `active_calories_estimated`) alongside the editable current `active_calories` from FTY-043.
  - The estimated/original value is captured at item creation, or snapshotted from the current value on the first edit if not already set, and is never mutated after it is set.
- Add an append-only, **immutable** `corrections` migration: `id`, `user_id` (FK, ON DELETE CASCADE), a reference to the corrected derived item (item id + item type `food`/`exercise`, or two nullable typed FKs), `field` name, `old_value`, `new_value`, `source` (e.g. `user_edit`), `created_at`. No `UPDATE` or `DELETE` is permitted on this table at the application boundary (audit integrity).
- Implement an edit endpoint (`PATCH` a derived item's field) that:
  - Enforces **object-level authorization** and **fails closed** on any cross-user access (a non-owner edit must not reveal existence or mutate state).
  - Snapshots the original value into the estimated column if it has not been snapshotted yet, then sets the current value.
  - Appends the immutable correction row(s) describing the change.
  - Validates input (known field, type/range bounds, non-negative values) with a clear error shape.
- Implement the **servings rescale rule** deterministically in this backend endpoint:
  - Editing quantity/servings rescales the item's calories and macros (food) by `ratio = new_quantity / old_quantity` applied to their **current** values, and writes a correction row for the servings change **and** for each rescaled field.
  - A direct edit to calories, a single macro, or exercise burn overrides only that field and writes a single correction row.
  - Last edit wins.

## Non-Goals

- The editable item UI and edit affordances (FTY-050, mobile-core).
- Saved foods, aliases, and reuse of corrected recurring foods (FTY-052).
- Learning/adaptation that feeds corrections back into future estimates (later).
- Re-running the estimator on edit, or any LLM involvement — edits are deterministic user overrides.
- Deleting or undoing derived items (out of scope; corrections are append-only history, not undo).
- Daily summary recomputation/display (FTY-071) — summaries simply read the current values.

## Contracts

- The `corrections` table + DTO contract (append-only audit record: user-owned, typed item reference, field, old/new value, source, timestamp). This is a named contract consumed by FTY-052 and later learning work.
- The snapshot columns added to `derived_food_items` and `derived_exercise_items` (estimated/original vs current value pairs) extend the FTY-043/FTY-044 derived-item contracts without redefining them.
- The edit DTO: the `PATCH` request shape (target item id + type, field, new value) and the response shape (updated derived item with both estimated and current values) — a contract consumed by FTY-050.
- The servings rescale rule (ratio applied to current values, with per-field correction rows) is documented as the deterministic correction semantics other stories rely on.

## Security / Privacy

Derived food/exercise items and corrections are sensitive personal nutrition data and must be user-owned with object-level authorization on every edit path, proven by negative tests that **fail closed** on cross-user access. Old/new values must not be logged. The `corrections` table is append-only: the application must reject any update or delete, and a tamper/immutability test must prove it. `corrections` follow the data-retention doc (retained until user/account deletion; CASCADE on user delete). Rated high: touches contracts, a migration, object-level authz, and user nutrition data.

## Acceptance Criteria

- Editing a derived item field updates the current value, preserves the original estimated value immutably, and appends a correction row capturing field, old value, new value, and source.
- The original/estimated value is snapshotted exactly once (at creation or on first edit) and never changes on subsequent edits.
- Editing servings/quantity rescales calories and macros by `new_quantity / old_quantity` against their current values and appends a correction row for the servings change and for each rescaled field; the rescale math is deterministic and unit-tested.
- A direct edit to calories, a single macro, or exercise burn overrides only that field (last edit wins) and appends exactly one correction row.
- A cross-user edit fails closed (negative authorization test) — no mutation, no existence disclosure.
- `corrections` rows cannot be updated or deleted through the application (immutability/tamper test).
- Input validation rejects unknown fields and out-of-range/invalid values with a clear error shape.
- Migration applies and rolls back; `corrections` and the new snapshot columns carry correct user ownership/references.
- `make verify` passes.

## Verification

- Run `make verify` (API + migration + authz + rescale tests).
- Apply/roll back the `corrections` migration and the derived-item snapshot-column migration in a test database.
- API tests for request validation, auth-failure, success, and error-shape on the edit endpoint.
- Rescale unit tests: exact worked ratio examples (including fractional ratios, rounding, zero/invalid old quantity), per-field correction rows asserted.
- Negative authorization test proving a cross-user edit fails closed.
- Immutability/tamper test asserting `UPDATE`/`DELETE` on `corrections` is rejected at the application boundary.

## Planning Notes

- Snapshot timing: capturing the estimated value at item creation is preferred; the "snapshot on first edit if not already set" path is the safety net for items created before this migration. Implement both; document which fires.
- Value precision/units: corrections store `old_value`/`new_value` in the derived item's canonical units (kcal, grams for macros) — reuse the FTY-043/FTY-044 canonical units and a single documented rounding rule for rescaled values; cite it in the PR. These choices are non-blocking, hence ready_with_notes.
- The item-reference shape (polymorphic id+type vs two nullable typed FKs) is an implementation choice; either is acceptable if it preserves a typed, indexed, user-owned reference. If an audit/immutability helper (DB trigger or app-layer guard) is needed to block UPDATE/DELETE, note it in the PR — no new external dependency is expected.

## Readiness Sanity Pass

- Product decision gaps: none — storage model (preserve original + immutable audit row), the append-only `corrections` table, the fail-closed edit endpoint, and the servings rescale rule are all resolved by the product owner.
- Cross-lane impact: defines the corrections + edit-DTO contracts consumed by FTY-050 (mobile edit UI) and FTY-052 (saved foods); extends FTY-043/FTY-044 derived-item contracts.
- Security/privacy risk: high; sensitive nutrition data, user-owned, object-level authz with fail-closed negative tests, append-only audit proven by a tamper test.
- Verification path: `make verify` + migration rollback + rescale unit tests + negative authz test + immutability test.
- Assumptions safe for autonomy: yes; snapshot timing, value precision/units, and the item-reference shape are documented non-blocking notes.
