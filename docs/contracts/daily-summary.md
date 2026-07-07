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

4 (FTY-071; target read-model added jointly by FTY-094/FTY-095). FTY-092 adds the
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
FTY-223 adds the integer **`uncounted_entries`** field (per-day count of entries
logged but not yet counted toward `intake` because they await a user action) so a
range consumer can tell a genuinely empty day from a day whose only entries are
uncounted; additive, no migration, populated identically in the single-day and
range reads.
5 (FTY-278, contract only) makes the finalized-state filter and `uncounted_entries`
account for the **item-scoped partial clarification** state (`log-events.md` v6,
`food-resolution.md` v9): the new first-class `partially_resolved` event status
carries committed `resolved` siblings, so the finalized filter's event-status
clause relaxes from `completed`-only to `completed` **or** `partially_resolved`,
and `uncounted_entries` counts the **unresolved component** awaiting details
(one per open item-scoped question on a `partially_resolved` event) rather than
the whole event, while the degenerate event-level `needs_clarification` case still
counts one per event. No new persistence and no migration — the same computed read
over existing rows. This version **settles the counting semantics only**; the
estimator work that first commits siblings on a `partially_resolved` event is the
downstream **FTY-278 implementation follow-up**, and until it lands the
FTY-275/FTY-223 baseline holds (a mixed log routes to an event-level
`needs_clarification` with nothing committed and counts as one whole uncounted
entry).

6 (FTY-279, contract only) states how a **calorie-only user-stated item** counts. A
recognizable item the user gave a calorie total for resolves as a `user_text`
`as_logged` item (`food-resolution.md`, `evidence-retrieval.md`) with **known
calories but unknown (`null`) macros**. Its **calories count** in `intake.calories`
like any resolved item; each **unknown (`null`) macro contributes no grams** to the
day's macro total (a `null` macro is skipped, **not** summed as `0`), so a day's
macro sums reflect only the macros actually known. The item stays distinguishable at
the item detail / provenance level: its `source` descriptor is `user_text` and a
`null` macro field is surfaced as unknown rather than `0`. Additive: no new
persistence and no migration — the same computed read over existing (already-nullable)
macro columns; the `user_text` source system is `evidence-retrieval.md`'s, and it is
**numerically inert until the FTY-280 estimator follow-up** first writes such an item.

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
  false`, and `uncounted_entries: 0` (unless the day has uncounted entries — the
  count is populated per-day identically to the single-day read); their `target`
  follows the same **No-target representation** as the
  single-day read (carried forward within the goal's horizon, `null` outside it) —
  exactly the DTO the single-day endpoint returns for that day. The response is the
  JSON array `[DailySummaryDTO, …]`.
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
  "uncounted_entries": 0,
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
  for the day. Zeroed when no finalized food items exist. A finalized item with a
  **known calorie value but an unknown (`null`) macro** (a calorie-only `user_text`
  item, FTY-279) contributes its **calories** to `intake.calories` and contributes
  **no grams** to that unknown macro's sum — a `null` macro is **skipped**, never
  summed as `0`, so a macro total reflects only the macros actually known that day.
- `has_intake` — boolean, `true` iff the day has **at least one finalized food
  item**. Because `intake` is zeroed both for an unlogged day and for a day whose
  only logged food is genuinely zero-kcal, the zero alone cannot distinguish the
  two; this flag does. A range/series consumer (FTY-101 Trends adherence) excludes
  `has_intake: false` days from its logged-intake average and on/off-target
  denominator rather than counting every unlogged day as a real 0-kcal day.
- `uncounted_entries` — integer, the count of the day's **awaiting-details units**:
  things the user logged that are not yet counted toward `intake` because they need
  a user action. Precisely the sum of two disjoint kinds attributed to the day:
  - the day's **open clarification units** — the components the estimator asked
    about and is waiting on the user for. The **unit is the unresolved component**,
    not the whole event (FTY-278): under the item-scoped partial contract a
    `partially_resolved` event contributes **one per still-`unresolved` component
    that owns an open item-scoped question** (its `resolved` siblings count in
    `intake` instead, never here), and the degenerate **event-level**
    `needs_clarification` case — where no component is individually costed —
    contributes **one for the event**. Under the **FTY-275 baseline** every mixed
    log is the event-level `needs_clarification` case (nothing committed), so this
    is one per event — identical to the FTY-223 count; item-scoped per-component
    counting on `partially_resolved` events arrives with the FTY-278 estimator
    follow-up.
  - the user's **`proposed`** derived food items (FTY-196 — a costed-but-unconfirmed
    label parse, excluded from every finalized read by construction).

  **Excluded** (never counted): finalized items (already in `intake`), including a
  partial event's `resolved` siblings; `pending` and `processing` events (the
  estimator is still working — the client's loading path, not "awaiting details");
  and `failed` events (a distinct retry state). A single partially-resolved entry
  can therefore contribute to **both** `intake` (its resolved siblings) and
  `uncounted_entries` (its unresolved component) at once — the two sets are disjoint
  by item status, so nothing is double-counted. Day attribution is the owning
  `LogEvent.created_at` in the profile timezone over `[start, end)`, exactly
  matching how `intake` / `has_intake` attribute a day. A day with no such units
  reports `0`. This is what lets a range consumer (FTY-188 Trends adherence)
  honestly say "N entries awaiting details" rather than collapse an uncounted-only
  day (`has_intake: false`, zeroed `intake`, non-zero `uncounted_entries`) into
  "nothing logged" (`uncounted_entries: 0`). Present on every day of the single-day
  and range reads.
- `target` — the **target read-model** for the user's active goal on this day,
  **carried forward** within the goal's horizon (a `daily_targets` row is stored on
  goal-creation day but the daily target is effectively constant across the horizon
  (a whole-year-age approximation; see `target-calculator.md`), so any
  in-horizon day reports the most recent stored row), or `null` (JSON `null`) when
  none applies (no active goal, the day predates the goal's first stored row, or the
  day is past the goal's `target_date`). See **No-target representation** below.
  Each of `calories` (kcal, int) and the macro targets `protein_g` /
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

> `log_events.status IN ('completed', 'partially_resolved')`
> AND `derived_{food,exercise}_items.status == 'resolved'`
> AND `current_value IS NOT NULL`

- Items on `pending` / `processing` / `failed` events are excluded: a `pending` or
  `processing` event has no committed terminal items (the estimator is still
  working — the client's loading path), and a `failed` event never produced any.
- **`partially_resolved` events are included (FTY-278).** Under the item-scoped
  partial contract (`log-events.md` v6, `food-resolution.md` v9) a
  `partially_resolved` event carries committed `resolved` siblings — a mixed
  log's costable components — committed in the same terminal transaction as the
  `processing → partially_resolved` transition, exactly as FTY-043/FTY-044 commit
  a `completed` event's items. Those siblings are genuine costed nutrition and
  count immediately; the event's still-`unresolved` component contributes to
  `uncounted_entries` instead (below), so the two are disjoint and the entry is
  never double-counted. The event-level `needs_clarification` case commits nothing
  and is correctly excluded by this filter. **Baseline:** until the FTY-278
  estimator follow-up lands, no `partially_resolved` event exists, so this clause
  adds nothing to any total — the numbers are identical to the `completed`-only
  filter.
- `unresolved` items (NULL calories / NULL active_calories) are excluded — this is
  what keeps a partial event's amountless component out of `intake` while its
  resolved siblings count. The `current_value IS NOT NULL` clause gates on the item's
  **headline** value (a food item's `calories`); a **calorie-only `user_text` item**
  (FTY-279) has non-null calories and is therefore **included**, and its unknown
  (`null`) macros do not exclude it — they are simply skipped from the macro sums
  (above), never treated as `0`.
- **`proposed` items are excluded by construction (FTY-196).** A legible
  nutrition-label parse lands as an uncounted **`proposed`** food item on a
  `completed` event (`label-upload.md` → Confirmation gate); because the predicate
  requires `status == 'resolved'`, a `proposed` item is filtered out automatically
  and never inflates intake until the user confirms it (`proposed → resolved`). This
  filter is **not relaxed** for the gate — the exclusion is a property of the
  existing predicate, not new logic.
- A test proves this exclusion: items on `pending` / `processing` / `failed` /
  `needs_clarification` events, `unresolved` items (including a partial event's
  amountless component), and `proposed` (unconfirmed label) items never inflate a
  total (single-day and range); a `partially_resolved` event's `resolved` siblings
  do count.

## Day / timezone resolution

- The `day` boundary is computed in the user's profile timezone (falling back to
  UTC when the profile is absent).
- Items are attributed to a day by their owning log event's `created_at` — the
  field `log-events.md` already indexes and resolves by day for the Today timeline.
  This keeps the summary day consistent with the event timeline the mobile UI shows.
- The `day` parameter defaults to the current day in the profile timezone.
- A malformed `day` (unparseable date string) returns `422`.

## No-target representation

The active-goal target is **carried forward** within the goal's horizon: a
`daily_targets` row is stored on goal-creation day (and on an override write), but
the daily target is effectively constant across the horizon (a whole-year-age
approximation; see `target-calculator.md`), so any day at or after the first
stored row and on or before the goal's `target_date` reports that target (the most
recent stored row). This is what keeps the calories-vs-target headline — and the
onboarding-completeness probe — present for a returning user rather than vanishing
the day after onboarding.

`target` is `null` (JSON `null`) only when:
- The user has no active goal (`goals.is_active = true`), or
- The day predates the goal's **first stored** `daily_targets` row, or
- The day is **past** the goal's `target_date` (the planned trajectory is complete;
  the user is steered to set a new goal rather than shown a stale deficit).

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
surfaces a Today item — the corrections `PATCH` response and the FTY-198
day-listing read (`GET /api/users/{user_id}/log-events/by-date?day=YYYY-MM-DD`) —
so all read paths inherit them.

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
| `source_type` | The `evidence-retrieval.md` hierarchy enum on the item's `evidence_sources` row: `trusted_nutrition_database`, `product_database`, `official_source`, `user_label`, `user_text` (FTY-279), `reference_source`, `model_prior`. A `model_prior` value is the client's signal to render the "≈ rough estimate · make it exact" treatment (ux-design §4a); a `user_text` item's headline (its calories) is a **user-stated** value, and any macro estimated to fill a gap carries `field_provenance = estimated` for the detail sheet. |
| `label` | A human, display-ready string mapped deterministically from `source_type` / `ref`: `trusted_nutrition_database` → "USDA", `product_database` → "Open Food Facts", `user_label` → "Label scan", `user_text` → "You logged" (FTY-279), `official_source` → the URL host, `reference_source` → the page host, `model_prior` → "Rough estimate". |
| `ref` | The stable `source_ref` (`usda_fdc:<id>`, `open_food_facts:<barcode>`, `official_source:<url>`, `user_label:<hash>`, `user_text:<hash>` (FTY-279), `reference_source:<url>`, `model_prior`) for the sheet's deeper provenance line. For an `official_source` / `reference_source` item this is the **URL only** (no headers, body, or query secrets); for a `user_text` item it is the hash of the extracted facts, **never the raw diary phrase**. |

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
| `422` | **Single-day read:** malformed `day` parameter (not a valid `YYYY-MM-DD` date). **Range read:** malformed or missing `from`/`to` (not a valid `YYYY-MM-DD`), `from` is after `to` (ordering error), or span exceeds 366 days (span error). |

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
- **FTY-223** adds the additive `uncounted_entries` integer (single-day and range).
  It is a pure computed read over existing rows (`log_events.status ==
  'needs_clarification'` events + `derived_food_items.status == 'proposed'` items),
  no new table and **no migration** — both statuses already exist and `proposed` is
  persisted as a plain `VARCHAR` (application-only per `DerivedItemStatus`).
  Additive and backward-compatible: existing consumers ignore the new field; the
  intended consumer is FTY-188 Trends adherence. FTY-278 re-bases the counting unit
  from the whole event to the unresolved component (below) without changing the
  field or its baseline value.
- **FTY-279 (contract only; no migration).** States that a calorie-only `user_text`
  item counts its calories in `intake.calories` while each unknown (`null`) macro is
  **skipped** from the macro sums (not summed as `0`), and adds the `user_text` value
  (label "You logged") to the per-item `source` descriptor enum/mapping. A **pure
  computed read** over existing rows — the macro columns are already nullable
  (FTY-044/FTY-051) and `evidence_sources.source_type` is a string, so there is no new
  table, no new column, and no DTO shape change. Backward-compatible and **numerically
  inert until the FTY-280 estimator follow-up** writes the first such item. (This entry
  also completes the descriptor enum's `reference_source` value, per FTY-166's
  provenance read-model.)
- **FTY-278 (contract only; no migration).** Relaxes the finalized-state filter's
  event-status clause to `IN ('completed', 'partially_resolved')` and re-bases
  `uncounted_entries` onto the unresolved **component** (one per open item-scoped
  question on a `partially_resolved` event, plus one per event-level
  `needs_clarification` event) so a mixed log's resolved siblings count in `intake`
  while its amountless component stays uncounted. Still a **pure computed read**
  over existing rows — the `partially_resolved` status is a new value in the
  existing string `status` column, so there is no new table, no new column, and no
  DTO shape change (the item↔question link is `parse-candidates.md` v5's additive
  `clarification_questions.derived_food_item_id`, owned by the FTY-278 estimator
  follow-up). Backward-compatible and **numerically inert until that follow-up
  lands**: no `partially_resolved` event exists today, so the relaxed filter adds
  nothing to any total and `uncounted_entries` still counts one per event-level
  `needs_clarification` event (the FTY-223 baseline). The consumer contract
  (FTY-188 Trends) is unchanged.
