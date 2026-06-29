---
id: FTY-124
state: merged
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - trends
  - daily-summary
  - range
  - adherence
  - mobile
  - performance
approved_dependencies: []
requires_context:
  - docs/contracts/daily-summary.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/security/security-baseline.md
review_focus:
  - single-request-fan-out-removal
  - sensitive-data-handling
  - range-switch-correctness
  - loading-error-states
autonomous: true
---

# FTY-124: Trends Adherence Consumes the Daily-Summary Range Read (mobile-core)

## State

ready

## Lane

mobile-core

## Dependencies

- **FTY-123** (daily-summary range read endpoint + contract) — **blocking**. This
  story consumes that endpoint; the two are joined by the daily-summary range
  contract.
- **FTY-101** (Trends redesign + adherence strip) — the screen this modifies; it
  introduced the per-day fan-out being removed here. This story lands the fix for
  the blocking reviewer concern on PR #71.

## Outcome

The Trends screen's intake-adherence strip fetches the whole selected range in
**one** request via the FTY-123 range endpoint, instead of firing one
`getDailySummary` per calendar day (up to ~180 requests per render, re-fired on
every range switch). This resolves the blocking reviewer concern on PR #71
(FTY-101): a client-side fan-out over a missing read-model. Adherence behaviour is
unchanged — average kcal vs. target, days-on-target, the per-day strip, the
null-target exclusion rule, and the same range as the weight chart — only the data
source becomes a single range call.

## Scope

- **Add a typed range client** alongside the existing `getDailySummary` (e.g.
  `getDailySummaryRange(session, start, end)` in `mobile/api/dailySummary.ts`) that
  calls `GET /api/users/{user_id}/daily-summaries?start&end` and returns the
  **dense, ascending array of `DailySummaryDTO`** defined by the FTY-123 contract.
  Reuse the existing `DailySummaryDTO` type, session/auth, URL builder, and the
  existing error mapping (`401`/`404`/`422`/generic) — extend, don't fork. Map a
  `422` (over the max-span / bad range) to a clear non-leaking message.
- **Replace the adherence fan-out** in the Trends screen: where it currently maps
  the range to N per-day `getDailySummary` calls, issue **one**
  `getDailySummaryRange` call for the selected `[start, end]` and feed the returned
  array into the same adherence computation (avg kcal vs. target, days-on-target,
  the per-day strip). Because the contract guarantees one dense entry per day in
  range, the strip maps array element → cell directly with no client-side gap
  filling.
- **Preserve the adherence semantics from FTY-101 exactly:** the "on target"
  tolerance rule, **null-target days rendered as a distinct state and excluded
  from the days-on-target denominator** (never a miss), and graceful handling of a
  range with no logged days. These rules move unchanged; only their input source
  changes from N calls to one.
- **Range switching** issues a single new range request for the newly selected
  range (not a re-fan-out); the weight chart and adherence strip stay on the same
  range. **Past-day drilldown** (tapping a cell to open that day's timeline) is
  unchanged.
- **Loading / error / empty states** for the adherence panel now key off the
  single request: one in-flight spinner, one error surface (with a retry), and the
  existing empty-range invite — no partial-fan-out states. A failed range request
  degrades gracefully and never blocks the weight panel above it.

## Non-Goals

- **The range endpoint / contract** — delivered by FTY-123 (backend-core); consumed
  here, not changed.
- **The weight chart, smoothing, headline delta, weight-entry sheet, and weigh-in
  reminder** (FTY-101) — untouched; this story only swaps the adherence data
  source.
- **Changing the adherence math or the on-target / null-target rules** — they are
  reused verbatim; this is a data-fetch refactor, not a behaviour change.
- **Removing the single-day `getDailySummary` client** — Today (FTY-075) and the
  past-day drilldown still use it; only the Trends *range* fan-out is replaced.
- **Caching / persistence of range results** beyond normal in-screen state.

## Contracts

- **None new.** Consumes the **daily-summary range read** added by FTY-123
  (`docs/contracts/daily-summary.md`) — the dense ascending array of the existing
  `DailySummaryDTO`. No server contract is defined here.

## Security / Privacy

- Daily nutrition totals, macros, and targets are **sensitive personal data**:
  fetched only over the authenticated API (TLS), shown only to the authenticated
  owner, and **never written to logs, error messages, or analytics** — errors
  carry only the HTTP status + action, mirroring the existing daily-summary
  client. The range response is the same sensitive data as N single-day responses,
  now in one payload; the same no-logging discipline applies.
- No new external egress (one endpoint replaces many of the same kind), no new
  trust boundary. Medium risk: sensitive per-user data, but a client-side
  data-source swap with no new server logic or contract of its own.

## Acceptance Criteria

- Rendering the Trends adherence strip for a range issues **exactly one**
  daily-summary request (the range call), not one per day — asserted in a test
  that counts fetch invocations for a multi-day range.
- Switching range issues exactly one new range request for the new range (no
  fan-out); the weight chart and adherence strip remain on the same range.
- The adherence summary (avg kcal vs. target, days-on-target, per-day strip) is
  unchanged from FTY-101, including the **null-target exclusion** rule (null days
  are a distinct state, not a miss, not in the denominator) and the empty-range
  invite.
- The per-day strip maps one cell per day directly from the dense range array (no
  client-side gap filling).
- Loading shows a single in-flight state; a failed range request shows one error
  surface with retry and does not block the weight panel; a `422`/`401`/`404`
  maps to a clear, non-leaking message.
- No nutrition number is emitted to logs, error output, or analytics.
- TypeScript strict passes; mobile checks pass via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile): mobile typecheck, lint, and
  tests via `make verify` where wired.
- **Fan-out removal test (the core property):** for a multi-day range, assert the
  mocked fetch is called **once** (the range endpoint), not N times — and that the
  adherence summary derived from the single dense array matches the previously
  expected values.
- **Range-client test:** `getDailySummaryRange` builds the correct
  `?start&end` URL with the bearer token, parses the dense array, and maps
  `401`/`404`/`422`/generic errors to non-leaking messages.
- **Adherence parity test:** avg kcal vs. target, days-on-target counting, the
  per-day strip, and the **null-target exclusion** rule produce the same results
  from the range array as FTY-101 produced from per-day calls.
- **Range-switch test:** selecting a new range triggers a single new range request
  and updates the strip.
- **Error/empty states:** a failed range request renders one retry-able error and
  leaves the weight panel intact; an empty range shows the invite.
- On an iOS simulator: open Trends, confirm the adherence strip loads with one
  request (verify via network inspector / mock), switch ranges and confirm a single
  new request, and tap a day to open its timeline (drilldown unchanged).

## Planning Notes

- **Extend the existing client, don't fork it.** `getDailySummaryRange` lives next
  to `getDailySummary` and reuses the session type, URL builder, auth headers, and
  error mapping already in `mobile/api/dailySummary.ts`, so there is one place that
  knows the daily-summary surface.
- **This is a refactor of FTY-101's adherence data path**, not a redesign — keep
  the adherence component's props/shape stable where possible so the change is
  "swap N fetches for one" and the math is provably unchanged (parity test).
- No evidence research warranted — the adherence cadence/on-target rules are
  already settled and evidence-grounded in FTY-101; this is a data-fetch change.

## Readiness Sanity Pass

- **Product decision gaps:** none. Behaviour is fixed by FTY-101; this only changes
  the fetch shape. `ready`.
- **Sizing decision:** one boundary — **mobile-core** only. No code in a second
  serializing lane. **Zero big rocks:** no public contract change (consumes the
  FTY-123 contract), no schema migration, no untrusted-input trust boundary.
  `review_focus` = 4 (under 5); `requires_context` = 4 (under 8). Small, single
  story — deliberately split from the backend endpoint (FTY-123) it depends on,
  joined by the daily-summary range contract.
- **Cross-lane impact:** none beyond mobile-core. Hard-depends on FTY-123 for the
  endpoint/contract; touches the FTY-101 Trends screen only.
- **Security/privacy risk:** medium — sensitive nutrition data over the
  authenticated API, never logged; one endpoint replaces many of the same kind, no
  new egress or trust boundary.
- **Verification path:** mobile tests proving single-request fan-out removal,
  range-client URL/error mapping, adherence parity incl. null-target exclusion,
  range-switch, error/empty states; `make verify`; simulator smoke.
- **Assumptions safe for autonomy:** yes — a bounded client-side data-source swap
  on an existing screen, gated by FTY-123 landing first; all behaviour rules
  inherited unchanged from FTY-101.
