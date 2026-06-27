---
id: FTY-071
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
  - estimator
risk: medium
tags:
  - daily-summary
  - aggregation
  - api
  - contracts
  - nutrition-data
approved_dependencies: []
requires_context:
  - docs/contracts/README.md
  - docs/contracts/log-events.md
  - docs/contracts/target-calculator.md
  - docs/contracts/food-resolution.md
  - docs/contracts/exercise-burn.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
review_focus:
  - object-level-authz
  - deterministic-aggregation-math
  - timezone-day-resolution
  - finalized-state-filtering
  - input-validation
autonomous: true
---

# FTY-071: Daily Totals Endpoint

## State

ready

## Lane

backend-core

## Dependencies

- FTY-022
- FTY-030
- FTY-043
- FTY-044
- FTY-051

## Outcome

A user can fetch a read-only daily summary for a given day and receive, computed
in their profile timezone: the day's intake calories and macros
(protein/carbs/fat), the day's calorie/macro **target** (from the FTY-022 target
calculator), and the day's exercise **active-calorie burn** — with intake, target,
and burn reported **separately** (not pre-netted). The endpoint is the backend
slice only; it gives the mobile daily-summary UI (FTY-075) a real contract to
render and lets the client compute net (`intake − burn`) itself from the exposed
components.

## Scope

- Add a read-only daily-summary endpoint that returns, for the authenticated
  user and a requested day, the separated totals/target/burn DTO described under
  Contracts. This is a **computed read endpoint** — no new table, no migration,
  no persisted summary row.
- **Day / timezone resolution.** Resolve `day` in the user's profile timezone,
  mirroring `log-events.md`: `day` is an optional `YYYY-MM-DD` query parameter
  that defaults to the current day in that timezone; a malformed `day` is `422`.
  The day boundary is computed in the profile timezone and used to bound the
  events/items aggregated.
- **Intake aggregation.** Sum the **current** calories and macros (protein/carbs/
  fat) of the user's `derived_food_items` for that day, reading post-correction
  current values per FTY-051 (the editable `calories` / `protein_g` / `carbs_g` /
  `fat_g`, never the `*_estimated` snapshots).
- **Burn aggregation.** Sum the **current** `active_calories` of the user's
  `derived_exercise_items` for that day (FTY-043 net active calories,
  post-correction current value), reported as a separate `exercise.active_calories`
  figure — not subtracted from intake.
- **Target.** Read the day's calorie/macro target from the FTY-022 target
  calculator / `daily_targets` for the user's active goal. Document and implement
  the resolution rule when no target exists for the day (see Planning Notes); the
  DTO must distinguish "no target available" from a zero target.
- **Finalized-state filtering.** Only aggregate items that belong to a finalized
  log event and are in a resolved/finalized item state. Per `log-events.md`, only
  events in the terminal `completed` status carry committed resolved items; items
  on `pending` / `processing` / `failed` / `needs_clarification` events, and any
  `unresolved` item (NULL calories/burn), are excluded. Document this filter
  explicitly so pending/failed work never inflates a total.
- **Day attribution.** Attribute an item to a day by its owning log event's
  `created_at` (the field `log-events.md` already indexes and resolves by day for
  the Today timeline), so the summary day matches the timeline day.
- **Empty day.** A day with no finalized items returns zeroed intake totals and a
  zeroed burn, plus the resolved target for that day (or the documented
  no-target representation).

## Non-Goals

- The mobile daily-summary UI, charts, and net display (FTY-075, mobile-core).
- Any new persisted summary/rollup table, materialized view, or caching layer —
  this is a pure computed read.
- Pre-netting intake against burn on the server; the endpoint exposes components
  separately and the client derives net.
- Editing, correcting, or recomputing item values — summaries only **read**
  current values (FTY-051 owns corrections).
- Re-running the estimator, target recomputation, or weight-trend logic.
- Multi-day ranges, weekly/period rollups, or trends (later).
- Adjusting the target for logged exercise burn server-side (the burn is reported
  separately; combining is a client/product concern).

## Contracts

- **Daily-summary DTO** (the named request/response contract this story
  introduces, consumed by FTY-075): the request shape (`day` query param, profile
  timezone resolution) and the response shape with **separated** components —
  intake (`calories`, `protein_g`, `carbs_g`, `fat_g`), `target` (calorie + macro
  target from FTY-022, or an explicit no-target representation), and `exercise`
  (`active_calories`). Canonical units only (kcal, grams), reusing the FTY-043/
  FTY-044 derived-item units and a single documented rounding rule.
- **Object-level authorization rule** for the endpoint: scoped to the owner under
  `/api/users/{user_id}/...`, fail-closed `404` on cross-user access, mirroring
  `log-events.md` (no existence oracle).
- This contract **reads** existing contracts without redefining them: the
  `daily_targets` / target-calculator output (FTY-022), `derived_food_items`
  current calories/macros (FTY-044, post-correction per FTY-051),
  `derived_exercise_items.active_calories` (FTY-043, post-correction per FTY-051),
  and the log-event status state machine + day/timezone discipline (FTY-030).
- No new persistence and no migration.

## Security / Privacy

- Daily totals, macros, target, and burn are **sensitive personal nutrition
  data**: user-owned, returned only to the owner, and never logged.
- **Object-level authorization, fail closed.** The endpoint serves only the
  authenticated user's own `{user_id}`; a cross-user request is indistinguishable
  from a missing one and fails closed as `404` (no existence oracle), exactly like
  `log-events.md`. Proven by a negative authorization test.
- Authentication: a valid, unexpired bearer token is required; otherwise `401`.
- Logging/telemetry: never log the totals, macros, target, or burn values; use
  user/event ids, not personal numbers (per the security baseline).
- No external egress, no LLM, no untrusted input beyond the validated `day`
  parameter.
- Rated **medium**: aggregation correctness plus object-level authz on sensitive
  data, but no migration, no new persistence, and no new trust boundary.

## Acceptance Criteria

- A day with known finalized food and exercise items returns correct **separated**
  totals: intake calories + macros summed from current food-item values, the
  day's calorie/macro target from FTY-022, and exercise active-calorie burn summed
  from current exercise-item values — burn is **not** netted into intake.
- An empty day (no finalized items) returns zeroed intake totals and zeroed burn,
  plus the resolved target for that day (or the documented no-target
  representation).
- Post-correction values are reflected: after an FTY-051 edit to a food or
  exercise item, the summary reflects the **current** value, not the original
  estimate.
- Only finalized/resolved items are counted: items on non-`completed` events and
  `unresolved` (uncosted) items are excluded, so pending/failed work never inflates
  a total. A test proves the exclusion.
- `day` is resolved in the user's profile timezone, defaults to the current day in
  that timezone, and timezone-boundary cases (an item near midnight) are attributed
  to the correct day. A malformed `day` returns `422`.
- A cross-user request fails closed (`404`, negative authorization test); missing/
  invalid token returns `401`.
- Aggregation math is deterministic and unit-tested with a single documented
  rounding rule; canonical units (kcal, grams) match FTY-043/FTY-044.
- `make verify` passes.

## Verification

- Run `make verify` (API + aggregation + authz tests).
- Aggregation unit/integration tests: a fixture day with multiple finalized food
  and exercise items asserts exact separated intake totals, macros, burn, and the
  target value; mixed-status fixtures assert non-`completed`/`unresolved` items
  are excluded.
- Post-correction test: edit an item via FTY-051, then assert the summary reflects
  the current value.
- Empty-day test: assert zeroed totals/burn and the resolved (or no-target)
  target.
- Timezone-boundary test: items created just before/after local midnight are
  attributed to the correct profile-timezone day; `day` default resolves to the
  current local day; malformed `day` → `422`.
- Negative authorization test proving a cross-user request fails closed (`404`),
  plus a `401` test for missing/invalid token.

## Planning Notes

- **No-target day rule.** If the FTY-022 target calculator / `daily_targets` has
  no target for the requested day (e.g. no active goal, or the day predates the
  goal), the DTO must represent this explicitly (e.g. a `null` target object)
  rather than emitting a misleading zero. Choosing between "nearest applicable
  target" vs "explicit null when none for that exact day" is an implementation
  choice; prefer the explicit-null representation and document which fires in the
  PR. Non-blocking.
- **Rounding rule.** Reuse the FTY-043/FTY-044 canonical units (kcal, grams) and
  apply a single documented rounding rule to the summed totals (e.g. round the
  final sums to 0.1, summing the already-stored current values); cite it in the
  PR. Non-blocking.
- **Day attribution field.** Attribute items via the owning log event's indexed
  `created_at` (the field `log-events.md` already resolves by day), keeping the
  summary day consistent with the Today timeline. If a future story needs a
  distinct "consumed at" time, that is out of scope here.
- **Finalized-state source of truth.** The exclusion rule keys off the log-event
  status state machine (`log-events.md`): committed resolved items live only on
  `completed` events (FTY-043/FTY-044 commit items in the same transaction as the
  terminal status). Document the exact predicate used (event status + non-NULL
  current value) so the filter is auditable.

## Readiness Sanity Pass

- Product decision gaps: none blocking — separated (not pre-netted) components,
  current-value reads, finalized-only filtering, profile-timezone day resolution,
  and the no-new-persistence shape are resolved by the product owner; the
  no-target representation and rounding rule are documented non-blocking notes.
- Cross-lane impact: introduces the daily-summary DTO + its authz rule (consumed
  by FTY-075 mobile UI); reads the FTY-022 target, FTY-044 food, and FTY-043
  exercise contracts (post-correction per FTY-051) without redefining them; no
  migration.
- Security/privacy risk: medium; sensitive nutrition data, user-owned, object-level
  authz with a fail-closed negative test, totals never logged; no external egress
  or LLM.
- Verification path: `make verify` + deterministic aggregation tests +
  finalized-state exclusion test + post-correction test + timezone-boundary test +
  negative authz/`401` tests.
- Assumptions safe for autonomy: yes; the no-target representation, rounding rule,
  and day-attribution field are documented non-blocking implementation choices.
