# Contract: Corrections Audit + Derived-Item Edit

## Purpose

Define how a user **corrects** a derived food/exercise item's value (FTY-051) so
that every edit preserves the estimator's original value and appends an immutable
audit record instead of silently overwriting the estimate. This is the backend
foundation for the mobile edit UI (FTY-050) and later learning/adaptation (FTY-052).

It covers three things:

1. the **`corrections`** table — an append-only, immutable audit row per changed
   field, and its DTO;
2. the **estimated/original snapshot columns** added to `derived_food_items` and
   `derived_exercise_items` (extending the FTY-043/FTY-044 derived-item contracts
   without redefining them);
3. the **edit endpoint** (`PATCH` a derived item's field), its request/response
   DTOs, the deterministic **servings rescale rule**, input validation, and the
   object-level authorization that fails closed on cross-user access.

Out of scope: the editable item UI (FTY-050), saved foods/aliases (FTY-052),
learning that feeds corrections back into future estimates, re-running the
estimator or any LLM on edit (edits are deterministic user overrides), and
deleting/undoing derived items (corrections are append-only history, not undo).

## Owner

backend-core / contracts / security-privacy lane:
`backend/app/models/corrections.py`, `backend/app/models/derived.py`
(`*_estimated` snapshot columns), `backend/app/schemas/corrections.py`,
`backend/app/services/corrections.py`,
`backend/app/services/item_read_model.py` (FTY-092 — the `source` descriptor +
`is_edited` derivation), `backend/app/routers/corrections.py`,
`backend/app/enums.py` (`CorrectionSource`, `SourceType`), `backend/alembic/`
(`0008`).

## Version

2 (FTY-092). v1 was FTY-051. FTY-092 adds the `amount_adjust` `CorrectionSource`
value, redefines the quantity-edit rescale as a **provenance-preserving** adjustment
(tagged `amount_adjust`, evidence untouched, item stays un-edited), and defines the
`is_edited` derivation. The value-override path (`user_edit`, single row,
`is_edited = true`) is unchanged.

## Inputs

### Edit request — `DerivedItemEditRequest`

`PATCH /api/users/{user_id}/derived-items/{item_type}/{item_id}`

| Field | Type | Meaning |
| --- | --- | --- |
| `field` | string | The field to override. Editable food fields: `quantity`, `calories`, `protein_g`, `carbs_g`, `fat_g`. Editable exercise field: `active_calories`. |
| `value` | number | New value in **canonical units** (kcal, grams, or servings). Must be finite and non-negative. |

`item_type` (`food` / `exercise`) and `item_id` are path parameters; `user_id`
scopes ownership. The body forbids unknown keys.

## Outputs

### Response — `DerivedFoodItemDTO` / `DerivedExerciseItemDTO`

The updated derived item carrying **both** the editable current values and the
immutable estimated/original snapshot:

- food: `amount`, `grams`, `calories`/`protein_g`/`carbs_g`/`fat_g` (current),
  `calories_estimated`/`protein_g_estimated`/`carbs_g_estimated`/`fat_g_estimated`
  (original), plus `id`, `user_id`, `log_event_id`, `name`, `status`, timestamps,
  and `item_type: "food"`.
- exercise: `active_calories` (current) and `active_calories_estimated` (original),
  plus the same envelope with `item_type: "exercise"`.

### Snapshot columns (estimated/original)

The `0008` migration adds nullable snapshot columns paired with the existing
editable current columns:

- `derived_food_items`: `calories_estimated`, `protein_g_estimated`,
  `carbs_g_estimated`, `fat_g_estimated`.
- `derived_exercise_items`: `active_calories_estimated`.

The estimated value is captured **exactly once** and never mutated afterward:

- **At creation** — the estimator persists a resolved item with each `*_estimated`
  column set to the value it just computed (the preferred path; see
  `app/estimator/processing.py`).
- **On first edit (safety net)** — if an `*_estimated` column is still `NULL`
  (e.g. an item created before this migration), the edit snapshots the prior
  current value into it before applying the change.

There is no `quantity_estimated` column: `quantity` (the `amount`) is an input that
drives the rescale, not a snapshotted estimator output.

### `corrections` audit row — `CorrectionDTO`

One immutable row per changed field:

| Column | Meaning |
| --- | --- |
| `id` | PK. |
| `user_id` | Owner (FK `users.id`, `ON DELETE CASCADE`). |
| `item_type` | `food` / `exercise` discriminator. |
| `derived_food_item_id` / `derived_exercise_item_id` | Exactly one is set (FK, `ON DELETE CASCADE`); a check constraint enforces the XOR. |
| `field` | Changed field name. |
| `old_value` | Prior value in canonical units (`NULL` only if the field had no value yet). |
| `new_value` | New value in canonical units. |
| `source` | Origin (`CorrectionSource`): `user_edit` (a direct value override) or `amount_adjust` (a provenance-preserving portion change, FTY-092). See **`CorrectionSource`** and **`is_edited` derivation** below. |
| `created_at` | Append timestamp. |

### `CorrectionSource`

| Value | Meaning |
| --- | --- |
| `user_edit` | A direct **value override** of `calories` / a single macro / `active_calories`. The load-bearing signal for `is_edited`. |
| `amount_adjust` | A **provenance-preserving portion change** (FTY-092): the rows a `quantity` edit produces (the `quantity` change and each rescaled field). It never marks the item edited and never rewrites provenance. |

Stored as a string column, so adding `amount_adjust` is additive with **no
migration** and **no backfill** (pre-v1, no production data; the new semantics apply
going forward).

### The servings rescale rule (deterministic, provenance-preserving)

Editing a food item's `quantity` is a **provenance-preserving amount adjustment**
(FTY-092), **not** a value override:

1. `old_quantity` is the item's current `amount`; `new_quantity` is the request
   value. `ratio = new_quantity / old_quantity`.
2. Each currently-resolved `calories`/`protein_g`/`carbs_g`/`fat_g` is rescaled to
   `current × ratio`, **rounded to 0.1** (the same canonical rounding the FTY-044
   serving math uses). `amount` is set to `new_quantity` (rounded to 3 dp, matching
   resolved-grams precision). `grams` and evidence are **not** recomputed — a portion
   fix is not a re-resolution.
3. A correction row is appended for the `quantity` change **and** for each rescaled
   field (each snapshotting its original first), every row tagged **`amount_adjust`**.
4. The item's **evidence/source is unchanged** — the `evidence_sources`
   `source_type` / `source_ref` snapshot stays exactly as resolved — and the item's
   `is_edited` stays **false**. Fixing the amount does not turn the item into a manual
   override (matches `docs/design/ux-design.md` §4a).

A direct edit to `calories`, a single macro, or `active_calories` is a **value
override**: it overrides only that field, rounds to 0.1, appends exactly **one**
`user_edit` correction row, does not change the amount, leaves provenance unchanged,
and sets `is_edited` **true**. Last edit wins.

#### Worked example

```
food item: amount 2, calories 300, protein_g 10, carbs_g 40, fat_g 5
PATCH {field: "quantity", value: 3}                       # provenance-preserving
  → ratio = 3 / 2 = 1.5
  → calories 450.0, protein_g 15.0, carbs_g 60.0, fat_g 7.5; amount 3
  → corrections += quantity(2→3), calories(300→450), protein_g(10→15),
    carbs_g(40→60), fat_g(5→7.5)   (5 rows, all source=amount_adjust)
  → *_estimated unchanged (300/10/40/5 preserved)
  → evidence_sources unchanged; is_edited stays false

PATCH {field: "calories", value: 280}                     # value override
  → calories 280.0; amount unchanged
  → corrections += calories(450→280)   (1 row, source=user_edit)
  → is_edited becomes true
```

### `is_edited` derivation (canonical rule)

An item's `is_edited` flag is **derived, never stored**:

> `is_edited` is **true iff the item has at least one correction whose
> `source == user_edit`** (a value override).

`amount_adjust` corrections never make an item edited. So a never-edited item and an
item that has only been amount-adjusted are both `false`; an item with a value
override is `true`. Computed at read time from the append-only audit trail, so it
never drifts and needs no backfill. This flag is exposed per item on the
Today/daily read-model — see `daily-summary.md`.

> **Re-match is a third, distinct lever (FTY-093).** The "Change match" operation
> re-resolves an item to a *different real source* (see
> `evidence-retrieval.md` → **Item Re-match — FTY-093**). It is **not** a correction:
> it writes **no** `corrections` row of either source, rewrites the item's
> `evidence_sources` provenance to the new source, and **re-snapshots** `*_estimated`
> to the newly computed values (deliberately diverging from the captured-once rule,
> which governs `user_edit` overrides). Because it writes no `user_edit` row, a
> re-matched item stays `is_edited == false` — its honesty comes from the new source,
> not from a value override. Do not "fix" this back to `user_edit`.

## Validation

- **Known field.** A field outside the editable set for the item type →
  `422 {"error": "unknown_field", "field": <field>}`. (Fail closed: an exercise
  item rejects food fields and vice-versa.)
- **Non-negative, finite value.** Enforced at the request boundary (`422` with the
  pydantic error shape for a negative/NaN/infinite value).
- **Range bound.** A value above the canonical sanity bound (`100000` kcal/g, or
  `100000` servings) → `422 {"error": "out_of_range", "field": <field>}`.
- **Quantity.** A zero/`NULL`/negative `old_quantity` (no defined ratio) →
  `422 {"error": "invalid_old_quantity", "field": "quantity"}`; a non-positive new
  quantity → `invalid_quantity`. Fails closed, nothing mutated.

## Authorization

Object-level, on every edit, **failing closed**:

- The caller must own `{user_id}` (`current_user.id == user_id`), and the item is
  loaded **scoped to that user**. A cross-user or unknown id is indistinguishable
  from a missing one — both render `404`, so a non-owner edit never mutates state
  and never reveals the item exists.
- `corrections`, `derived_food_items`, and `derived_exercise_items` are user-owned
  with `ON DELETE CASCADE` from `users`.

## Privacy and Retention

- **Append-only / immutable.** `corrections` is never updated or deleted by
  application code. Two ORM guards reject any `UPDATE`/`DELETE` through a session
  (`CorrectionImmutableError`), proven by a tamper test. Account/user deletion
  still removes a user's rows via the database `ON DELETE CASCADE` (a retention
  requirement, intentionally outside the application-edit guard).
- **Retention.** `corrections` and the snapshot columns are user-owned derived data
  retained until the owning derived item, log event, user, or account is deleted
  (`ON DELETE CASCADE`), per `docs/security/data-retention.md`.
- **No value logging.** Old/new values are sensitive personal data and are never
  written to logs; error shapes carry a field name and a stable code only, never
  the value.

## Errors

| Condition | Result |
| --- | --- |
| Cross-user or unknown item | `404` (no existence disclosure, no mutation). |
| Missing/invalid credentials | `401`. |
| Unknown field for the item type | `422` `unknown_field`. |
| Negative / non-finite value | `422` (request-boundary validation). |
| Value above range bound | `422` `out_of_range`. |
| Zero/invalid old quantity on a rescale | `422` `invalid_old_quantity`. |
| Non-positive new quantity | `422` `invalid_quantity`. |
| Unknown `item_type` in the path | `422`. |

## Examples

See the worked example above. Covered by `tests/test_corrections_api.py`
(endpoint, validation, error shapes, cross-user fail-closed), `tests/`
`test_corrections_rescale.py` (deterministic rescale math, per-field rows,
snapshot-once, last-edit-wins), `tests/test_corrections_immutability.py`
(`UPDATE`/`DELETE` rejected), `tests/test_corrections_migration.py`
(apply/rollback, ownership, check constraint), and `tests/test_item_provenance.py`
(FTY-092 — the three `is_edited` cases, provenance-preserving amount adjust vs.
value override, and the source-descriptor mapping).

## Migration / Compatibility

- The `0008` migration applies (`alembic upgrade head`) on top of the `0007`
  food-resolution schema and is fully reversible (`alembic downgrade 0007`),
  verified by an apply/rollback test against a throwaway database.
- Additive: the derived-item tables gain nullable `*_estimated` columns and
  `corrections` is new; no prior table is altered destructively. Snapshot-on-first-
  edit removes the need for a backfill.
- The item-reference shape is two nullable typed FKs plus an `item_type`
  discriminator, with a check constraint enforcing exactly one reference. The 0.1
  rounding for energy/macros and 3-dp for servings, and the `100000` sanity bounds,
  are documented v1 choices.
- **FTY-092 (no migration).** Adding the `amount_adjust` `CorrectionSource` value is
  additive over the existing string `source` column — no schema migration, no
  backfill. FTY-051 tagged quantity-rescale rows `user_edit`; FTY-092 retags them
  `amount_adjust` and declares the rescale provenance-preserving. This is a **clean
  redefinition** (pre-v1, no production data): a portion fix no longer marks an item
  edited. The `source` descriptor and `is_edited` flag are **derived reads** (from
  `evidence_sources` and the `corrections` history) with no new persisted column or
  read table.
