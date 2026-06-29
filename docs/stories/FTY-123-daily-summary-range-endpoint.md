---
id: FTY-123
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
risk: medium
tags:
  - daily-summary
  - range
  - trends
  - aggregation
  - api
  - contracts
  - nutrition-data
approved_dependencies: []
requires_context:
  - docs/contracts/daily-summary.md
  - docs/contracts/README.md
  - docs/contracts/target-calculator.md
  - docs/contracts/log-events.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
review_focus:
  - object-level-authz
  - range-bound-validation
  - deterministic-aggregation-math
  - timezone-day-resolution
  - aggregation-efficiency
autonomous: true
---

# FTY-123: Daily-Summary Range Read Endpoint (backend-core / contracts)

## State

ready

## Lane

backend-core

## Dependencies

- FTY-071 (daily-summary endpoint + contract) — merged; this story adds the
  "future day-listing read" the daily-summary contract already anticipates
  (`docs/contracts/daily-summary.md` — the per-item provenance section names
  "any future day-listing read"; this is it, at the **aggregate** level).
- FTY-094 / FTY-095 (target read-model in the daily-summary DTO) — merged;
  reused unchanged per entry.

## Outcome

A client can fetch daily summaries for a **date range in a single request** instead
of firing one `GET /daily-summary` per calendar day. This removes a client-side
fan-out over a missing read-model: the Trends adherence strip (FTY-101) currently
issues up to ~180 `getDailySummary` calls per render and re-fires the whole set on
every range switch, because no range/list endpoint exists. This story adds the
backend range read (and the contract for it) returning one `DailySummaryDTO` per
day in the range, computed in the user's profile timezone, with the same separated
intake / target / exercise components and the same finalized-state filter as the
single-day endpoint. The dependent mobile story (FTY-124) consumes it to replace
the per-day fan-out; this is the backend slice only.

## Scope

- **Add a read-only range endpoint** returning a list of daily-summary DTOs over
  a requested `[start, end]` inclusive date range:
  `GET /api/users/{user_id}/daily-summaries?start=YYYY-MM-DD&end=YYYY-MM-DD`
  (plural collection path; see Planning Notes). Each element is the **existing**
  `DailySummaryDTO` (`date`, `intake`, `target`, `exercise`) — the per-day shape is
  unchanged; the new contract is the request/response *envelope* and its bounds.
- **Dense, ordered result.** Return exactly one entry per calendar day in the
  inclusive range, ordered ascending by `date`, including **zeroed** intake/exercise
  days and `null`-target days (no active goal / no stored target for that day) — so
  the client's adherence strip maps one cell per day with no client-side gap
  filling. A day with no finalized items returns zeroed intake + zeroed burn (and
  its resolved-or-`null` target), identical to the single-day endpoint's empty-day
  rule.
- **Reuse the single-day computation per day.** Per-day intake, exercise, and
  target use the **same** finalized-state filter
  (`log_events.status == 'completed'` AND `derived_*_items.status == 'resolved'`
  AND `current_value IS NOT NULL`), the same profile-timezone day attribution (by
  the owning log event's `created_at`), the same 0.1 rounding, and the same
  no-target → `null` rule that FTY-071 already implements. Do **not** redefine any
  per-day semantics; the range read is a windowed aggregation of the existing one.
- **Range validation + bound (security/DoS).** `start` and `end` are required
  `YYYY-MM-DD` in the profile timezone; a malformed value → `422`; `end < start`
  → `422`. **Cap the span** at a documented maximum (recommend **366 days**); a
  range exceeding the cap → `422` with a clear message, so the query is always
  bounded. The cap is a single documented constant.
- **Efficient aggregation.** Compute the range without N separate per-day round
  trips to the DB where avoidable: prefer a small fixed number of bounded queries
  over the whole `[start, end)` window (e.g. fetch the window's finalized items
  and the window's `daily_targets` rows, then bucket by profile-timezone day
  in-process), rather than looping the single-day service 366 times. Correctness
  (timezone bucketing, finalized filter, dense fill) takes precedence; the
  efficiency shape is an implementation choice documented in the PR.

## Non-Goals

- **The mobile Trends consumption** (FTY-124, mobile-core) — separate dependent
  story joined by this contract.
- **Any new persisted summary/rollup table, materialized view, or cache** — this
  stays a pure computed read, like FTY-071. No migration.
- **Changing the per-day `DailySummaryDTO` shape** — intake/target/exercise are
  reused verbatim; only the range envelope + bounds are new.
- **Pre-netting intake against burn**, re-running the estimator, target
  recomputation, or weight-trend math — all out of scope, as in FTY-071.
- **Pagination / cursoring** — the documented day-cap bounds the response; no
  paging envelope in v1 (note in PR if a future large range needs it).
- **Per-item provenance in the range read** — this returns per-day *aggregates*,
  not items; the FTY-092 `source`/`is_edited` item shape is not part of it.

## Contracts

- **Daily-summary contract update** (`docs/contracts/daily-summary.md`, version
  bump): add the **range/list read** section — the request shape (`start` + `end`
  query params, both required, profile-timezone resolution, the inclusive-range +
  max-span rule and its `422`s), the response shape (an ordered, **dense** JSON
  array of the existing `DailySummaryDTO`, one per day), and the object-level
  authz rule (same owner-scoped, fail-closed `404`). State explicitly that each
  element reuses the v2 per-day DTO unchanged and that the array is dense + ascending.
  This is the one **big rock** (a public contract change) — it rides in this single
  backend-core story per the single-boundary rule.
- **Object-level authorization rule** identical to FTY-071: scoped to the owner
  under `/api/users/{user_id}/...`, fail-closed `404` on cross-user access (no
  existence oracle), proven by a negative test.
- **Reads** existing contracts without redefining them: the `daily_targets` /
  target-calculator read-model (FTY-022/094/095), `derived_food_items` /
  `derived_exercise_items` current values (FTY-043/044, post-correction per
  FTY-051), and the log-event status state machine + day/timezone discipline
  (FTY-030). No new persistence, no migration.

## Security / Privacy

- Daily totals, macros, target, and burn are **sensitive personal nutrition
  data**: user-owned, returned only to the owner, and **never logged** (use
  user/event ids, not personal numbers, per the security baseline).
- **Object-level authorization, fail closed.** Serves only the authenticated
  user's own `{user_id}`; a cross-user request is indistinguishable from a missing
  one and fails closed as `404`. Proven by a negative authorization test. Missing/
  invalid token → `401`.
- **Bounded query (DoS).** The required-and-validated `start`/`end` plus the
  documented max-span cap (`422` when exceeded) prevent an unbounded or pathological
  range from forcing an arbitrarily large scan/response — a real concern for a
  range endpoint that the single-day endpoint did not have.
- No external egress, no LLM, no untrusted input beyond the validated date params.
- Rated **medium**: a public contract change + range-bound validation + object-level
  authz on sensitive data, but no migration, no new persistence, no new trust
  boundary.

## Acceptance Criteria

- `GET /api/users/{user_id}/daily-summaries?start=&end=` returns an **ascending,
  dense** array with exactly one `DailySummaryDTO` per calendar day in the
  inclusive `[start, end]` range.
- Each element matches the single-day endpoint for that day: identical intake/
  exercise totals (same finalized filter, same 0.1 rounding), identical target
  read-model (or `null`), identical profile-timezone day attribution — verified by
  asserting a given day's range element equals the single-day endpoint's result.
- Days with no finalized items return zeroed intake + zeroed burn (and their
  resolved-or-`null` target); they are **present**, not omitted.
- Validation: malformed `start`/`end` → `422`; missing `start` or `end` → `422`;
  `end < start` → `422`; a span exceeding the documented max (recommend 366 days)
  → `422` with a clear message.
- A cross-user request fails closed (`404`, negative authorization test); missing/
  invalid token → `401`.
- Timezone-boundary correctness: an item near local midnight is bucketed into the
  correct profile-timezone day within the range, consistent with FTY-071.
- No new table/migration; aggregation math is deterministic and unit-tested.
- `make verify` passes.

## Verification

- Run `make verify` (API + aggregation + authz tests).
- **Range correctness test:** a fixture spanning several days with mixed finalized
  food/exercise items and some empty days asserts the array is dense + ascending
  and each element's separated totals/target match the expected per-day values.
- **Parity test:** for a sampled day inside a range, assert the range element is
  byte-equal (same DTO) to calling the single-day endpoint for that day — proving
  the range read does not drift from FTY-071's semantics.
- **Validation tests:** malformed/missing `start`/`end` → `422`; `end < start` →
  `422`; span over the cap → `422`.
- **Timezone-boundary test:** items just before/after local midnight land in the
  correct day's range element.
- **Authz tests:** cross-user request → `404` (negative test); missing/invalid
  token → `401`.
- **Empty-range edge:** `start == end` returns a single-element array for that day.

## Planning Notes

- **Path/shape choice.** A plural collection `…/daily-summaries?start&end` returning
  a bare ordered array of the existing DTO is the lowest-surface design and keeps
  each element identical to the single-day endpoint (easy parity test). An object
  envelope (`{ "summaries": [...] }`) is an acceptable alternative if the reviewer
  prefers room for future range-level metadata; pick one, document it in the
  contract, and keep elements as the unchanged `DailySummaryDTO`. Non-blocking.
- **Max-span constant.** ~180 days is the current Trends worst case; 366 gives a
  one-year headroom with a hard bound. Single documented constant, easy to tune.
  Inclusive `[start, end]` is chosen so the client passes the visible range
  directly without off-by-one math; state inclusivity explicitly in the contract.
- **Efficiency.** Bucketing one windowed item query + one windowed `daily_targets`
  query by profile-timezone day in-process avoids 366 single-day calls. Reuse the
  FTY-071 helpers (`_day_bounds_utc`, the finalized filters, `build_target_read_model`)
  so the per-day math has exactly one source of truth and cannot diverge.
- No evidence research warranted — this is an API/read-model shape decision the
  existing contract already anticipates, not a health/nutrition/behavioural question.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking. The array-vs-envelope shape, the exact
  max-span value, and inclusive bounds are documented choices with sensible
  defaults; the per-day semantics are fixed by FTY-071. `ready`.
- **Sizing decision:** one boundary — **backend-core**, with **contracts** riding
  along (non-serializing). **Exactly one big rock:** the public daily-summary
  contract change (the range envelope). No schema migration (pure computed read,
  no new table) and no new untrusted-input trust boundary — so a single big rock,
  within the single-story rule. `review_focus` = 5 (at the ceiling, not over);
  `requires_context` = 6 (under 8). Stays one story; the mobile consumption is
  split into FTY-124.
- **Cross-lane impact:** introduces the range read contract (consumed by FTY-124);
  reuses the FTY-071 per-day computation and the FTY-094/095 target read-model
  without redefining them; no migration.
- **Security/privacy risk:** medium — sensitive nutrition data, owner-scoped
  fail-closed authz with a negative test, totals never logged, and a **bounded**
  range (required params + max-span cap) to prevent an unbounded scan. No external
  egress or LLM.
- **Verification path:** `make verify` + range-correctness + single-day parity +
  validation (`422`) + timezone-boundary + negative-authz/`401` tests.
- **Assumptions safe for autonomy:** yes — the envelope shape, max-span constant,
  and inclusive bounds are documented non-blocking choices, all reusing FTY-071's
  proven per-day logic as the single source of truth.
