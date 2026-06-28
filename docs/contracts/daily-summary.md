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

3 (FTY-071; target read-model added jointly by FTY-094/FTY-095). FTY-092 adds the
**per-item provenance read shape** (`source` descriptor + `is_edited`) to the
Today/daily item read-model below; it does not change the aggregate totals math.
FTY-094/FTY-095 replace the single-integer `target` component with the **target
read-model**: per target (calorie + each macro) the effective value, the derived
value, and a `derived | user` provenance flag (see `target-calculator.md`).
FTY-101 adds the boolean **`has_intake`** flag (finalized-food-item presence) so a
range consumer can tell an unlogged day from a genuine zero-kcal day; it does not
change any existing component.
FTY-123 adds the **range/list read** (`GET .../daily-summary/range?from&to`) — the
server-side read-model for multi-day series that replaces per-day fan-out; see the
range-read section under Inputs.

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

### HTTP request — range read (FTY-123)

```
GET /api/users/{user_id}/daily-summary/range?from=YYYY-MM-DD&to=YYYY-MM-DD
Authorization: Bearer <token>
```

The range read returns one daily-summary DTO **per calendar day** in
`[from, to]` inclusive, so a consumer that needs an adherence/history series
(FTY-101 Trends) issues **one** request rather than one request per day. It is
the canonical read for multi-day series; clients must not fan out per-day
single-day calls to build a range. (This is a totals series — the per-item
day-listing read described under "Per-item provenance" is a separate, items-level
read path.)

- `from`, `to` — required `YYYY-MM-DD` calendar days in the user's profile
  timezone. `from` must be on or before `to`, and the span may not exceed
  **366 days**; either violation (or a malformed date) is rejected as `422`.
- Every day in the inclusive range is present in the response, oldest-first.
  Days with no finalized data carry zeroed `intake`/`exercise`, `has_intake:
  false`, and a `null` `target` — exactly the DTO the single-day endpoint returns
  for that day. The response is the JSON array `[DailySummaryDTO, …]`.
- Same finalized-state filtering, day/timezone resolution, no-target
  representation, rounding, authorization, and privacy rules as the single-day
  read — it is the same read-model computed over a window, not a new shape.

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
  "has_intake": true,
  "target": {
    "calories": { "effective": 1800, "derived": 1678, "source": "user" },
    "protein_g": { "effective": 128, "derived": 128, "source": "derived" },
    "carbs_g": { "effective": 148, "derived": 148, "source": "derived" },
    "fat_g": { "effective": 64, "derived": 64, "source": "derived" }
  },
  "exercise": {
    "active_calories": 210.0
  }
}
```

- `date` — the requested calendar day (echoed back).
- `intake` — summed calories (kcal) and macros (grams) from finalized food items
  for the day. Zeroed when no finalized food items exist.
- `has_intake` — boolean, `true` iff the day has **at least one finalized food
  item**. Because `intake` is zeroed both for an unlogged day and for a day whose
  only logged food is genuinely zero-kcal, the zero alone cannot distinguish the
  two; this flag does. A range/series consumer (FTY-101 Trends adherence) excludes
  `has_intake: false` days from its logged-intake average and on/off-target
  denominator rather than counting every unlogged day as a real 0-kcal day.
- `target` — the **target read-model** for the stored `daily_targets` row of the
  user's active goal on this day, or `null` (JSON `null`) when none exists (no
  active goal, or the day predates the goal). See **No-target representation**
  below. Each of `calories` (kcal, int) and the macro targets `protein_g` /
  `carbs_g` / `fat_g` (whole grams, int) is an object with `effective` (what the
  app uses: override ?? derived), `derived` (the calculator value a reset
  restores), and `source` (`derived | user`). The full override/reset semantics
  live in `target-calculator.md`; this endpoint reads the row, it does not mutate
  it.
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
differently by the client (e.g. "no target set" vs. "target: 0 kcal"). When the
target is present, every component (calorie + macros) is always populated — a
target is never partially `null`.

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

A boolean, **true iff the item carries a `user_edit` value-override correction not
superseded by a later `re_match`** (the canonical rule defined in `corrections.md` —
this restatement defers to it). A direct value override (`calories` / a macro /
`active_calories`) sets it `true`; a later **re-match** (`re_match`, a re-resolution
to a different real source, FTY-093) **supersedes** that edit and returns it to
`false` — the item's honesty then comes from the new source, not a stale override —
until a genuine edit after the re-match makes it `true` again. A never-edited item,
an item that has only been **amount-adjusted** (a provenance-preserving portion fix,
`corrections.md`), and an edited-then-rematched item are all `false`. Derived from the
append-only `corrections` history, so it never drifts and needs no backfill.

## Rounding rule

Final sums are rounded to **0.1** (one decimal place) in canonical units (kcal,
grams), matching the FTY-043/FTY-044 serving-math precision. The already-stored
current values are summed first, then the sum is rounded. This rule applies to
`intake.calories`, `intake.protein_g`, `intake.carbs_g`, `intake.fat_g`, and
`exercise.active_calories`. The `target` read-model values are whole integers
(calorie kcal and macro grams), not rounded here.

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
| `422` | **Single-day read:** malformed `day` parameter (not a valid `YYYY-MM-DD` date). **Range read:** malformed or missing `from`/`to` (not a valid `YYYY-MM-DD`), `from` after `to`, or span exceeding 366 days. |

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

# Range read: 5-day window (oldest-first dense array)
curl -s ':8000/api/users/<uid>/daily-summary/range?from=2026-06-01&to=2026-06-05' \
  -H 'authorization: Bearer <t>'
# → 200 [{"date":"2026-06-01",...}, {"date":"2026-06-02",...}, ...]

# Range validation: inverted range
curl -s ':8000/api/users/<uid>/daily-summary/range?from=2026-06-05&to=2026-06-01' \
  -H 'authorization: Bearer <t>'
# → 422

# Range validation: span exceeds 366-day cap
curl -s ':8000/api/users/<uid>/daily-summary/range?from=2025-01-01&to=2026-06-01' \
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
- Macro targets and the override read-model are now exposed (v2): the `target`
  component is the calorie + macro read-model (effective / derived / `source`) per
  `target-calculator.md`. This is a breaking change to the `target` shape (was a
  single `{ "calories": int }`); pre-v1 with no consumers in production, so the
  read-model replaces the old shape rather than shimming it. The endpoint still
  reads `daily_targets`; it never sets or resets an override (that is the target
  endpoint).
- **FTY-092** adds the per-item `source` descriptor + `is_edited` flag to the item
  read shape. Both are **derived reads** (from `evidence_sources` and the
  `corrections` history) — no new table, no migration, no change to the aggregate
  totals. Consumers (FTY-098/100 timeline + sheet) depend on the `source` / `is_edited`
  shape defined here for the source icon + ✎ marker.
