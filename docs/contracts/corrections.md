# Contract: Corrections Audit + Derived-Item Edit

## Purpose

Define how a user **corrects** a derived food/exercise item's value (FTY-051) so
that every edit preserves the estimator's original value and appends an immutable
audit record instead of silently overwriting the estimate. This is the backend
foundation for the mobile edit UI (FTY-050) and later learning/adaptation (FTY-052).

It covers four things:

1. the **`corrections`** table — an append-only, immutable,
   **value-type-polymorphic** (FTY-377) audit row per changed field, and its DTO;
2. the **estimated/original snapshot columns** added to `derived_food_items` and
   `derived_exercise_items` (extending the FTY-043/FTY-044 derived-item contracts
   without redefining them);
3. the **edit endpoint** (`PATCH` a derived item's field), its request/response
   DTOs, the deterministic **servings rescale rule**, input validation, and the
   object-level authorization that fails closed on cross-user access;
4. the **rename endpoint** (`PATCH …/name`, FTY-377) — the audited display-name
   edit — and the derived `is_renamed` flag.

Out of scope: the editable item UI (FTY-050), the rename UI (FTY-378), saved
foods/aliases (FTY-052), learning that feeds corrections back into future
estimates, re-running the estimator or any LLM on edit or rename (both are
deterministic user operations), and deleting/undoing derived items (corrections
are append-only history, not undo).

## Owner

backend-core / contracts / security-privacy lane:
`backend/app/models/corrections.py`, `backend/app/models/derived.py`
(`*_estimated` snapshot columns), `backend/app/schemas/corrections.py`,
`backend/app/services/corrections.py`,
`backend/app/services/item_read_model.py` (FTY-092 — the `source` descriptor +
`is_edited` derivation), `backend/app/routers/corrections.py`,
`backend/app/enums.py` (`CorrectionSource`, `SourceType`), `backend/alembic/`
(`0008`, `0021`).

## Version

4 (FTY-377). The audit is now **value-type-polymorphic**: the `0021` migration
makes `new_value` nullable, adds the bounded `old_value_text` / `new_value_text`
columns, and adds the `ck_corrections_one_value_kind` check constraint (exactly
one of `new_value` / `new_value_text` per row). A new **`name_edit`**
`CorrectionSource` records a **display-name rename** — the dedicated
`PATCH …/derived-items/{item_type}/{item_id}/name` mutation overwrites the item's
`name` in place and appends one immutable text-valued row. A rename is **not** a
value override: it never affects `is_edited`; the read model exposes the separate
derived `is_renamed` flag. See **Item rename — FTY-377** below.

3 (FTY-306, contract only). Applying an **exact evidence upgrade** (`Make it
exact` — `evidence-retrieval.md`, **Exact Evidence Upgrade — FTY-306**) is
audited exactly like a Change-match re-resolve: it appends one immutable
**`re_match`** correction row, **not** a `user_edit`, and the applied item reads
`is_edited = false` until a later manual override. No new `CorrectionSource`
value, no schema change. See the FTY-306 note under **`is_edited` derivation**.

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

### Rename request — `DerivedItemRenameRequest` (FTY-377)

`PATCH /api/users/{user_id}/derived-items/{item_type}/{item_id}/name`

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | The new display name. Untrusted user text: non-blank after stripping, ≤ 200 chars (the derived-item `name` cap). Stored as data via parameterized ORM inserts — never executed, interpreted, logged, or echoed. |

Same path-parameter/ownership shape as the edit request; the body forbids unknown
keys. A request-validation failure (empty / whitespace-only / over-length name,
unknown key) renders the **content-free** `422 {"error": "invalid_request"}` shape
(the FTY-307 sanitized handler) — never FastAPI's default input-echoing body, so
the submitted name is never reflected back.

## Outputs

### Response — `DerivedFoodItemDTO` / `DerivedExerciseItemDTO`

Returned by the edit **and rename** endpoints. The updated derived item carrying
**both** the editable current values and the immutable estimated/original
snapshot, plus the derived `source` descriptor, `is_edited`, and `is_renamed`
(FTY-377) flags:

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
  `app/estimator/persist.py`).
- **On first edit (safety net)** — if an `*_estimated` column is still `NULL`
  (e.g. an item created before this migration), the edit snapshots the prior
  current value into it before applying the change.

There is no `quantity_estimated` column: `quantity` (the `amount`) is an input that
drives the rescale, not a snapshotted estimator output.

### `corrections` audit row — `CorrectionDTO`

One immutable row per changed field. **Value-type-polymorphic** (FTY-377): a
numeric correction carries `old_value` / `new_value`; a text correction (a
`name_edit` rename) carries `old_value_text` / `new_value_text` with `new_value`
`NULL`. The `ck_corrections_one_value_kind` check constraint enforces exactly one
of `new_value` / `new_value_text` per row, so each kind is well-formed and
mutually exclusive.

| Column | Meaning |
| --- | --- |
| `id` | PK. |
| `user_id` | Owner (FK `users.id`, `ON DELETE CASCADE`). |
| `item_type` | `food` / `exercise` discriminator. |
| `derived_food_item_id` / `derived_exercise_item_id` | Exactly one is set (FK, `ON DELETE CASCADE`); a check constraint enforces the XOR. |
| `field` | Changed field name (`name` for a rename). |
| `old_value` | Prior value in canonical units (`NULL` if the field had no value yet, or the row is a text correction). |
| `new_value` | New value in canonical units; `NULL` **iff** the row is a text correction (FTY-377). |
| `old_value_text` | Prior text value — the item's previous display name on a `name_edit` row; `NULL` for numeric corrections. |
| `new_value_text` | New text value — the user-authored display name on a `name_edit` row (≤ 200 chars, the item-name cap); `NULL` for numeric corrections. |
| `source` | Origin (`CorrectionSource`): `user_edit` (a direct value override), `amount_adjust` (a provenance-preserving portion change, FTY-092), `re_match` (a re-resolution to a different real source, FTY-093), or `name_edit` (an audited display-name rename, FTY-377). See **`CorrectionSource`** and **`is_edited` derivation** below. |
| `created_at` | Append timestamp. |

### `CorrectionSource`

| Value | Meaning |
| --- | --- |
| `user_edit` | A direct **value override** of `calories` / a single macro / `active_calories`. The load-bearing signal for `is_edited` (when not superseded by a later `re_match`). |
| `amount_adjust` | A **provenance-preserving portion change** (FTY-092): the rows a `quantity` edit produces (the `quantity` change and each rescaled field). It never marks the item edited and never rewrites provenance. |
| `re_match` | A **re-resolution to a different real source** (FTY-093): one row a "Change match" re-resolve appends (keyed on `calories`, the item's headline value). It is **not** a value override — it never marks the item edited — and it **supersedes** any prior `user_edit`, returning `is_edited` to `false`. It **does** rewrite the item's `evidence_sources` provenance to the new source. |
| `name_edit` | An **audited display-name rename** (FTY-377): the one text-valued row the rename endpoint appends. It is **not** a value override — the item's numbers keep their source, so it never affects `is_edited` — and it drives the separate derived `is_renamed` flag. See **Item rename — FTY-377**. |

Stored as a string column, so adding `amount_adjust` / `re_match` / `name_edit` is
additive with **no migration** and **no backfill** (pre-v1, no production data; the
new semantics apply going forward). The FTY-377 **schema** generalization (the text
columns and the one-value-kind constraint the `name_edit` rows need) is the `0021`
migration.

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

### Item rename — FTY-377 (audited display-name edit)

`PATCH /api/users/{user_id}/derived-items/{item_type}/{item_id}/name` with body
`{ "name": "<new name>" }` is the **dedicated rename mutation** — a deterministic
display-name edit, deliberately separate from the numeric edit endpoint so each
boundary stays cleanly typed (overloading `DerivedItemEditRequest.value` with a
`number | string` union would weaken the numeric validation for every value edit):

1. Authorization, owner-scoped load, and the voided-parent precheck (FTY-321) are
   **identical to the numeric edit** — cross-user, unknown, and voided-parent
   targets all render `404` with no mutation and no existence/void oracle.
2. The item's `name` is overwritten **in place** and exactly **one** immutable
   `name_edit` correction row is appended atomically with it: `field = "name"`,
   `old_value_text` = the prior name, `new_value_text` = the new name,
   `new_value` `NULL`.
3. A rename to the **identical current name is a safe no-op**: the item is
   returned unchanged and no churn row is appended.
4. The response is the updated `DerivedFoodItemDTO` / `DerivedExerciseItemDTO`,
   carrying the new `name`, `is_renamed = true`, and the **unchanged** `source`
   and `is_edited`.

A rename never re-resolves, re-costs, or calls any LLM; the item's numbers and
`evidence_sources` provenance are untouched. It also does **not** repoint the
re-match candidate **seed**: the change-match search still seeds from the item's
resolved identity, and the caller-supplied sanitized `query` override
(`routers/re_match.py`) remains the way a user steers the search after a personal
rename (a seed change is a possible follow-up story, not part of this contract).

### `is_renamed` derivation (FTY-377)

`is_renamed` is **derived, never stored**, exactly like `is_edited`:

> `is_renamed` is **true iff the item has at least one `name_edit` correction** —
> the user authored the display name.

It is exposed on `DerivedFoodItemDTO` / `DerivedExerciseItemDTO` (default `false`)
through the shared serializers, so every read path carries it. It is fully
**independent of `is_edited`**: a rename is not a value override (the calories
still come from USDA / the label / the model), so a never-value-edited renamed
item reads `is_edited = false, is_renamed = true`, and a later value override
flips `is_edited` without touching `is_renamed`. The item's current `name` itself
flows through the existing read paths (`daily-summary.md` item shape) with no new
join — the audit row is history, not the display source.

### `is_edited` derivation (canonical rule)

An item's `is_edited` flag is **derived, never stored**:

> `is_edited` is **true iff the item has a `user_edit` correction not superseded by a
> later re-match** — i.e. a `user_edit` whose `created_at` is after the most recent
> `re_match` row (or, when the item has never been re-matched, simply any `user_edit`).

`amount_adjust` corrections never make an item edited, and neither do `name_edit`
corrections (FTY-377) — a rename is a display-name change, not a value override. So a
never-edited item, an item that has only been amount-adjusted, and an item that has
only been renamed are all `false`; an item with an outstanding value override is
`true`. Computed at read time from the append-only audit trail, so it never drifts
and needs no backfill. This flag is exposed per item on the Today/daily read-model —
see `daily-summary.md`.

> **User-stated-at-log-time nutrition is evidence, not an edit (FTY-279).** When a
> user states a nutrition fact **in the original log text** ("… 580 cals …"), that
> value is captured as **source provenance** — an `evidence_sources` row with
> `source_type = user_text` and `field_provenance` marking the stated field
> `user_stated` (`evidence-retrieval.md`, `food-resolution.md`) — **not** as a
> `user_edit` correction. Such an item has **no** `user_edit` row from that stated
> fact and therefore reads `is_edited == false`: its honesty comes from the
> `user_text` source, exactly as a USDA or label item's does. A **later** manual
> override of that item's value (through the edit endpoint) is still a `user_edit`
> correction and makes `is_edited` `true` as usual. The `user_text` value joins the
> `SourceType` provenance enum (`backend/app/enums.py`) additively — a string column,
> no migration, no backfill — and surfaces via the `source` descriptor
> (`daily-summary.md`); it adds no `CorrectionSource` value, because a stated fact at
> log time is not a correction.

> **Re-match is a third, distinct lever (FTY-093).** The "Change match" operation
> re-resolves an item to a *different real source* (see
> `evidence-retrieval.md` → **Item Re-match — FTY-093**). It is **not** a value override:
> it writes **no** `user_edit` row, rewrites the item's `evidence_sources` provenance to
> the new source, and **re-snapshots** `*_estimated` to the newly computed values
> (deliberately diverging from the captured-once rule, which governs `user_edit`
> overrides). It **does** append one immutable `re_match` correction row — an honest
> audit of the re-match that **supersedes** any pre-existing `user_edit`. Because the
> re-match is the latest word on the item's value, a re-matched item reads
> `is_edited == false` — its honesty comes from the new source, not from a stale
> override — even when it had been edited before. Do not "fix" this back to `user_edit`;
> a later genuine edit (a `user_edit` after the re-match) makes it `true` again.

> **Exact evidence upgrade applies are `re_match`, not `user_edit` (FTY-306).** The
> `Make it exact` lever (`evidence-retrieval.md` → **Exact Evidence Upgrade —
> FTY-306**) replaces a low-trust/incomplete food item's source with user-supplied
> **product evidence** — an exact barcode/label match, or an honestly-labelled
> lower-trust fallback when exact evidence fails. Applying a proposal is a
> **source replacement**, the same write semantics as Change match: it rewrites the
> item's `evidence_sources` provenance to the applied source, **re-snapshots**
> `*_estimated` to the newly computed values, writes **no** `user_edit` row, and
> appends **one immutable `re_match` correction row** (keyed on `calories`) that
> supersedes any prior `user_edit`. An applied item therefore reads
> `is_edited == false` — its honesty comes from the new source (or the fallback's
> visible rough provenance) — until a **later** manual value override makes it
> `true` again. The two levers differ only in where the new source comes from:
> Change match fixes a wrong source by search; Make it exact asks the user for
> product evidence and applies the resulting source explicitly. An optional amount
> adjustment made from the apply preview is folded into the same re-resolution
> (applied before the recompute), not recorded as a separate
> `amount_adjust`/`user_edit` correction. The apply operation never accepts
> client-supplied nutrition facts (`food-resolution.md`, **Exact Evidence Upgrade
> Routing — FTY-306**).

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
- **Name (FTY-377).** An empty, whitespace-only, or over-length (> 200 chars)
  rename `name` is rejected at the request boundary with the content-free
  `422 {"error": "invalid_request"}` shape — the submitted value is **never
  echoed** (the FTY-307 sanitized validation handler covers this route). The
  service re-checks the bound (`invalid_name`) so a non-HTTP caller cannot bypass
  it. Surrounding whitespace is stripped before the name is stored. Fails closed,
  nothing mutated.

## Authorization

Object-level, on every edit **and rename**, **failing closed**:

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
- **Log-event void is a status, not a deletion (FTY-321).** A user removing a
  mislogged entry (`DELETE .../log-events/{id}`, `log-events.md`) is a **soft
  void**: it sets a `voided_at` marker on the `log_events` row and **retains**
  the event, its derived items, corrections, and evidence — no application-code
  row deletion occurs, so this append-only / immutable stance is fully
  preserved. A voided entry's rows simply stop appearing in read models and
  totals; the correction history hanging off a voided event stays intact and
  untouched (the ORM `UPDATE`/`DELETE` guards still hold). Only true account/user
  deletion removes correction rows, via the database `ON DELETE CASCADE` as
  above. The retained rows are also **not mutable after the void**: the
  correction edit, the re-match candidate-list / re-resolve endpoints, and the
  FTY-306 exact-upgrade proposal/apply endpoints each
  fail closed (`404`) when the target item's parent event is voided — a
  backend-core boundary precheck, since these endpoints address their row
  directly and bypass the read-time exclusion join (`log-events.md`,
  soft-void). Non-voided behaviour is unchanged.
- **Retention.** `corrections` and the snapshot columns are user-owned derived data
  retained until the owning derived item, log event, user, or account is deleted
  (`ON DELETE CASCADE`), per `docs/security/data-retention.md`.
- **No value logging.** Old/new values — numbers and item names alike — are
  sensitive personal data and are never written to logs; error shapes carry a
  field name and a stable code only, never the value. The rename `name` is
  additionally never echoed by request-validation failures (the content-free
  `invalid_request` shape).
- **Untrusted name text (FTY-377).** The rename `name` (and the text audit
  columns holding it) is untrusted user text like `raw_text`: schema-validated,
  bounded, stored via parameterized ORM inserts, and never executed or
  interpreted as an instruction.

## Errors

| Condition | Result |
| --- | --- |
| Cross-user or unknown item (edit or rename) | `404` (no existence disclosure, no mutation). |
| Item whose parent log event is voided (FTY-321; edit or rename) | `404` (fail closed, no mutation; same shape as unknown — no void oracle). |
| Missing/invalid credentials | `401`. |
| Unknown field for the item type | `422` `unknown_field`. |
| Negative / non-finite value | `422` (request-boundary validation). |
| Value above range bound | `422` `out_of_range`. |
| Zero/invalid old quantity on a rescale | `422` `invalid_old_quantity`. |
| Non-positive new quantity | `422` `invalid_quantity`. |
| Empty / whitespace-only / over-length rename name, or unknown rename body key (FTY-377) | `422` `invalid_request` (content-free; the name is never echoed). |
| Unknown `item_type` in the path | `422`. |

## Examples

See the worked example above. Covered by `tests/test_corrections_api.py`
(endpoint, validation, error shapes, cross-user fail-closed), `tests/`
`test_corrections_rescale.py` (deterministic rescale math, per-field rows,
snapshot-once, last-edit-wins), `tests/test_corrections_immutability.py`
(`UPDATE`/`DELETE` rejected), `tests/test_corrections_migration.py`
(apply/rollback, ownership, check constraints — including the FTY-377
one-value-kind combinations), `tests/test_postgres_migration.py` (the `0021`
apply/constraint/rollback on Postgres), `tests/test_item_rename.py` (FTY-377 —
rename happy paths, `is_renamed`/`is_edited` independence, no-op rename,
fail-closed boundary, content-free validation, `name_edit` immutability, read
paths), and `tests/test_item_provenance.py` (FTY-092 — the three `is_edited`
cases, provenance-preserving amount adjust vs. value override, and the
source-descriptor mapping).

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
- **FTY-279 (contract only; no migration).** A nutrition fact the user states in the
  original log text is captured as **evidence provenance** (`SourceType = user_text`,
  `field_provenance`; `evidence-retrieval.md` / `food-resolution.md`), **not** as a
  `user_edit` correction — so such an item reads `is_edited == false` and a later
  manual override is still a `user_edit`. Additive: the `user_text` value joins the
  string `SourceType` enum with **no migration and no backfill**, and **no**
  `CorrectionSource` value is added (a stated-at-log-time fact is not a correction).
- **FTY-092 (no migration).** Adding the `amount_adjust` `CorrectionSource` value is
  additive over the existing string `source` column — no schema migration, no
  backfill. FTY-051 tagged quantity-rescale rows `user_edit`; FTY-092 retags them
  `amount_adjust` and declares the rescale provenance-preserving. This is a **clean
  redefinition** (pre-v1, no production data): a portion fix no longer marks an item
  edited. The `source` descriptor and `is_edited` flag are **derived reads** (from
  `evidence_sources` and the `corrections` history) with no new persisted column or
  read table.
- **FTY-377 (`0021` migration + `name_edit`).** The `0021` migration generalizes
  the audit to value-type-polymorphic rows: `new_value` becomes nullable, the
  bounded `old_value_text` / `new_value_text` columns (`VARCHAR(200)`, the
  item-name cap) are added, and the `ck_corrections_one_value_kind` check
  constraint enforces exactly one of `new_value` / `new_value_text` per row. It
  applies and rolls back cleanly — the downgrade drops the constraint and text
  columns and restores `new_value NOT NULL`, deleting the dev-only text-valued
  rows first (pre-v1, no production data) — proven against both SQLite and a real
  Postgres (`tests/test_postgres_migration.py`). The `name_edit`
  `CorrectionSource` value itself is additive over the string `source` column.
  The append-only ORM `UPDATE`/`DELETE` guards apply to text rows unchanged, and
  the retention posture is identical: the text columns are user-owned derived
  data removed by the same `ON DELETE CASCADE` chain
  (`docs/security/data-retention.md`).
- **FTY-306 (contract only; no migration, no new enum value).** The exact
  evidence upgrade apply (`Make it exact`) reuses the existing **`re_match`**
  `CorrectionSource` and the FTY-093 audit semantics unchanged — one immutable
  `re_match` row per apply, no `user_edit` row, `is_edited` derives `false` until
  a later manual override. The `is_edited` derivation rule above is untouched.
  Backend implementation is **FTY-307–FTY-309**; mobile consumption is
  **FTY-310–FTY-313**. **As built (FTY-307):** the generic exact-evidence apply
  reuses the FTY-093 write helpers unchanged — the shared
  `record_re_match_correction` appends the single `re_match` row (keyed on
  `calories`, superseding any prior `user_edit`) and `apply_resolved_facts`
  re-snapshots `*_estimated`. An optional apply-time amount adjustment is folded into
  that one re-resolution (applied before the recompute), never recorded as a separate
  `amount_adjust` / `user_edit` row, so an applied item reads `is_edited = false`
  until a later manual override. No new `CorrectionSource` value and no schema change.
