# Contract: Daily Summary

## Purpose

Define the read-only **daily-summary endpoint** (FTY-071): how a user fetches
their day's separated calorie/macro intake, calorie target, and exercise burn,
all resolved in their profile timezone — as individual components the client can
use to render a daily summary UI (FTY-075) and compute net (intake − burn) itself.

This contract covers five things:

1. the **request shape** — the `day` query parameter, profile-timezone resolution,
   and the day-default rule;
2. the **response shape** — the daily-summary DTO with separated `intake`,
   `target`, and `exercise` components;
3. the **finalized-state filter** — the exact predicate used to exclude non-ready
   items so pending/failed work never inflates a total;
4. the **object-level authorization rule** — scoped to the owner, fail-closed
   `404` on cross-user access, mirroring `log-events.md`;
5. the **per-item provenance read shape** (FTY-092) — the `source` descriptor +
   `is_edited` flag the Today timeline renders per item, derived server-side so the
   client never joins `evidence_sources` / `corrections` itself.

It **reads** existing contracts without redefining them:
`derived_food_items` current calories/macros (FTY-044, post-correction per FTY-051),
`derived_exercise_items.active_calories` (FTY-043, post-correction per FTY-051),
the `daily_targets` / target-calculator output (FTY-022), and the log-event status
state machine + day/timezone discipline (FTY-030).

No new persistence, no migration, no pre-netting.

## Owner

backend-core / contracts lane (`backend/app/schemas/daily_summary.py`,
`backend/app/services/daily_summary.py`, `backend/app/routers/daily_summary.py`).
The per-item provenance read shape (FTY-092) is owned by
`backend/app/schemas/corrections.py` (`ItemSourceDTO`, the `source` + `is_edited`
fields on the item DTOs) and `backend/app/services/item_read_model.py` (the shared
serializer that derives them).

## Version

1 (FTY-071). FTY-092 adds the **per-item provenance read shape** (`source`
descriptor + `is_edited`) to the Today/daily item read-model below; it does not
change the aggregate DTO or the totals math.

## Inputs

### HTTP request

```
GET /api/users/{user_id}/daily-summary?day=YYYY-MM-DD
Authorization: Bearer <token>
```

- `user_id` — the authenticated user's own id; must match the token.
- `day` — optional `YYYY-MM-DD` calendar day in the user's profile timezone.
  Defaults to the current day in that timezone when omitted. A malformed `day`
  is rejected as `422`.

## Outputs

### Daily-summary DTO

```json
{
  "date": "YYYY-MM-DD",
  "intake": {
    "calories": 1234.5,
    "protein_g": 80.0,
    "carbs_g": 150.0,
    "fat_g": 40.0
  },
  "target": {
    "calories": 1800
  },
  "exercise": {
    "active_calories": 210.0
  }
}
```

- `date` — the requested calendar day (echoed back).
- `intake` — summed calories (kcal) and macros (grams) from finalized food items
  for the day. Zeroed when no finalized food items exist.
- `target` — the calorie target from the stored `daily_targets` row for the user's
  active goal on this day, or `null` (JSON `null`) when none exists (no active
  goal, or the day predates the goal). See **No-target representation** below.
  Macro targets are not part of the FTY-022 contract and are not included.
- `exercise` — summed net active-calorie burn (kcal) from finalized exercise items.
  Zeroed when no finalized exercise items exist. **Not** subtracted from intake.

**Response code**: `200 OK`.

## Finalized-state filtering

The exact predicate (documented for auditability — never relaxed without updating
this contract):

> `log_events.status == 'completed'`
> AND `derived_{food,exercise}_items.status == 'resolved'`
> AND `current_value IS NOT NULL`

- Items on `pending` / `processing` / `failed` / `needs_clarification` events are
  excluded: only `completed` events carry committed resolved items (FTY-043/FTY-044
  commit items in the same transaction as the terminal `completed` status).
- `unresolved` items (NULL calories / NULL active_calories) are excluded.
- A test proves this exclusion: non-`completed` event items and `unresolved` items
  never inflate a total.

## Day / timezone resolution

- The `day` boundary is computed in the user's profile timezone (falling back to
  UTC when the profile is absent).
- Items are attributed to a day by their owning log event's `created_at` — the
  field `log-events.md` already indexes and resolves by day for the Today timeline.
  This keeps the summary day consistent with the event timeline the mobile UI shows.
- The `day` parameter defaults to the current day in the profile timezone.
- A malformed `day` (unparseable date string) returns `422`.

## No-target representation

`target` is `null` (JSON `null`) when:
- The user has no active goal (`goals.is_active = true`), or
- The user has an active goal but no `daily_targets` row has been stored for the
  requested day (e.g. the day predates the goal's start or the target was never
  computed for that date).

A `null` target is distinct from a zero-calorie target and must be rendered
differently by the client (e.g. "no target set" vs. "target: 0 kcal").

## Per-item provenance read shape (FTY-092)

Each derived food/exercise item the Today timeline renders carries two fields,
**computed server-side** so the client maps the always-on **source icon** and the
**"✎ edited"** marker from one DTO rather than joining `evidence_sources` /
`derived_items` / `corrections` itself. They appear on the shared item DTO
(`DerivedFoodItemDTO` / `DerivedExerciseItemDTO`) returned by every read path that
surfaces a Today item — the corrections `PATCH` response today, and any future
day-listing read — so all read paths inherit them.

```json
{
  "id": "…", "name": "white rice", "amount": 1.0,
  "calories": 205.0, "protein_g": 4.3, "carbs_g": 44.5, "fat_g": 0.4,
  "source": {
    "source_type": "trusted_nutrition_database",
    "label": "USDA",
    "ref": "usda_fdc:168880"
  },
  "is_edited": false
}
```

### `source` descriptor

A small, read-only descriptor derived from the item's `evidence_sources` row
(`evidence-retrieval.md`). `null` when no evidence record exists (defensive) and on
exercise items (burn comes from MET tables, not an evidence row).

| Field | Meaning |
| --- | --- |
| `source_type` | The `evidence-retrieval.md` hierarchy enum on the item's `evidence_sources` row: `trusted_nutrition_database`, `product_database`, `official_source`, `user_label`, `model_prior`. A `model_prior` value is the client's signal to render the "≈ rough estimate · make it exact" treatment (ux-design §4a). |
| `label` | A human, display-ready string mapped deterministically from `source_type` / `ref`: `trusted_nutrition_database` → "USDA", `product_database` → "Open Food Facts", `user_label` → "Label scan", `official_source` → the URL host, `model_prior` → "Rough estimate". |
| `ref` | The stable `source_ref` (`usda_fdc:<id>`, `open_food_facts:<barcode>`, `official_source:<url>`, `user_label:<hash>`, `model_prior`) for the sheet's deeper provenance line. For an `official_source` item this is the **URL only** (no headers, body, or query secrets). |

The descriptor is **derived at read time** from the existing `evidence_sources` row
— no new persisted provenance column, no de-normalization, and only the owner's own
provenance is read (the `evidence-retrieval.md` global-vs-user split is respected).

### `is_edited`

A boolean, **true iff the item carries at least one `user_edit` value-override
correction** (the canonical rule defined in `corrections.md`). A never-edited item
and an item that has only been **amount-adjusted** (a provenance-preserving portion
fix, `corrections.md`) are both `false`; a direct value override (`calories` / a
macro / `active_calories`) is `true`. Derived from the append-only `corrections`
history, so it never drifts and needs no backfill.

## Rounding rule

Final sums are rounded to **0.1** (one decimal place) in canonical units (kcal,
grams), matching the FTY-043/FTY-044 serving-math precision. The already-stored
current values are summed first, then the sum is rounded. This rule applies to
`intake.calories`, `intake.protein_g`, `intake.carbs_g`, `intake.fat_g`, and
`exercise.active_calories`. `target.calories` is an integer (stored as
`daily_calorie_target_kcal: int`), not rounded.

## Authorization

- Authentication: every request requires a valid, unexpired bearer token; missing
  or invalid token → `401`.
- Object-level authorization: a user may only read **their own** daily summary.
  `{user_id}` must equal the authenticated user's id; a mismatch fails closed as
  `404` (no existence oracle) — the API neither confirms nor reveals another user's
  data. Proven by a negative authorization test.

## Privacy and Retention

- Daily totals, macros, target, and burn are **sensitive personal nutrition data**:
  user-owned, returned only to the owner, and **never logged**.
- Use user/event ids in logs, not personal numbers (per the security baseline).
- No external egress, no LLM, no new persistence.

## Errors

| Status | When |
| --- | --- |
| `401` | Missing/invalid/expired bearer token. |
| `404` | `{user_id}` does not belong to the authenticated user (fail closed). |
| `422` | Malformed `day` parameter (not a valid `YYYY-MM-DD` date). |

## Examples

```sh
# Get today's summary (default day in the user's timezone)
curl -s :8000/api/users/<uid>/daily-summary \
  -H 'authorization: Bearer <t>'
# → 200 { "date": "2026-06-27", "intake": {...}, "target": {...}, "exercise": {...} }

# Get a specific day
curl -s ':8000/api/users/<uid>/daily-summary?day=2026-06-26' \
  -H 'authorization: Bearer <t>'
# → 200 { "date": "2026-06-26", "intake": {...}, "target": null, "exercise": {...} }

# Malformed day
curl -s ':8000/api/users/<uid>/daily-summary?day=not-a-date' \
  -H 'authorization: Bearer <t>'
# → 422
```

## Migration / Compatibility

- No new tables, no migration. This is a pure computed read over existing tables
  (`log_events`, `derived_food_items`, `derived_exercise_items`, `daily_targets`,
  `goals`).
- Consumers (FTY-075 daily-summary UI) depend on the DTO shape defined here.
- FTY-051 post-correction values are automatically reflected: the endpoint reads
  current values (`calories`, `protein_g`, `carbs_g`, `fat_g`, `active_calories`),
  not the `*_estimated` snapshots.
- Macro targets are not part of FTY-022; when FTY-022 is extended with macro
  targets, this contract should be versioned to expose them.
- **FTY-092** adds the per-item `source` descriptor + `is_edited` flag to the item
  read shape. Both are **derived reads** (from `evidence_sources` and the
  `corrections` history) — no new table, no migration, no change to the aggregate
  totals. Consumers (FTY-098/100 timeline + sheet) depend on the `source` / `is_edited`
  shape defined here for the source icon + ✎ marker.
