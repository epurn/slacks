---
id: FTY-101
state: ready
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - trends
  - weight
  - trend
  - chart
  - adherence
  - notifications
  - mobile
  - design-system
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/weight-entries.md
  - docs/contracts/daily-summary.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
review_focus:
  - accessibility
  - sensitive-data-handling
  - notification-scheduling-correctness
  - trend-smoothing-correctness
  - local-preference-persistence
autonomous: true
---

# FTY-101: Trends Redesign + Weigh-in Reminders

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-097 (mobile design system: tokens/components this screen is rebuilt against)
- FTY-070 (weight backend: create + list-range endpoints) — merged
- FTY-074 (mobile weight logging + trend chart) — merged; this story evolves it
- FTY-071 (daily-summary endpoint) — merged
- FTY-075 (mobile daily-summary UI) — merged

## Outcome

The Trends tab is rebuilt against the FTY-097 design system to match the §4b
design: it leads with the weight **outcome** and places intake **behavior**
beneath it, on one screen, so the outcome↔behavior link stays intact. Five
pieces, all mobile-core:

1. A **smoothed weight-trend line** drawn over the noisy daily weigh-in points,
   with a **range selector** and a **headline delta** (e.g. "182.4 lb · ↓1.8 this
   month"). The smoothed line — not any single reading — is the visual lead.
2. An **intake-adherence summary** over the same range, sourced from the
   daily-summary endpoint per day in range: average kcal vs. target,
   days-on-target, and a compact adherence strip.
3. **Past-day drilldown:** tapping a day in the intake history opens that day's
   timeline (the Today layout for that date).
4. A **"+ log weight" entry** on the weight card opening a small numeric sheet
   (defaults to today, seeded with the last value), reusing FTY-074's units-aware
   input and FTY-070's create endpoint.
5. A **weigh-in reminder**: an on-device cadence preference (default **Weekly**;
   options Weekly · Every 2 weeks · Monthly · Off) and a **due-only** low-frequency
   local notification that fires *only when a weigh-in is actually due* — never
   daily, never a streak.

## Scope

### Weight outcome (top of screen)

- Render a **smoothed weight-trend line over the raw daily points** using the
  FTY-070 list-range endpoint for the selected range. Plot the actual logged
  weigh-ins as de-emphasized points and overlay the smoothed trend as the primary
  line, per §4b ("lead with the smoothed trend, de-emphasize any single reading").
- Smoothing method: an **exponentially-weighted moving average (EWMA)** over the
  daily series — the established trend-smoothing approach for body weight (see
  Research note). Use a single documented smoothing-factor constant; seed the
  average from the first reading so early/sparse ranges render without a startup
  artifact. The factor and seeding rule live in one place with a comment citing
  why (so it is auditable and tunable), not scattered magic numbers.
- A **range selector** drives both the chart and the adherence summary (same
  range for both). Use a small set of fixed ranges (e.g. month / 3 months / 6
  months — see Open question; pick a sensible default-month and keep the set a
  single configurable list). Switching range re-fetches/recomputes both panels.
- A **headline delta** computed from the smoothed trend (not raw endpoints): the
  current smoothed value and the change across the selected range, with direction,
  in the user's units (FTY-021). Phrasing mirrors §4b ("182.4 lb · ↓1.8 this
  month").

### Intake-adherence summary (beneath weight)

- Over the same range, fetch the daily-summary DTO per day and render: **average
  kcal vs. target**, **days-on-target** (count of days whose intake met the
  on-target rule), and a **compact adherence strip** (one cell per day in range).
- Define "on target" explicitly and in one place (e.g. within a tolerance band of
  that day's `target.calories`). Days with a **null target** (per the
  daily-summary contract — distinct from a zero target) are rendered as a
  distinct "no target" state in the strip and **excluded from the days-on-target
  denominator**, never counted as a miss.
- The adherence summary degrades gracefully when the range has no logged days.

### Past-day drilldown

- Tapping a day cell (in the adherence strip / intake history) opens **that day's
  timeline** — reuse the Today layout for the selected date (the daily-summary +
  timeline surfaces already built in FTY-075). No new screen design; route to the
  existing day view for the chosen date.

### "+ log weight" entry sheet

- A **"+ log weight"** affordance on the weight card opens a **small numeric entry
  sheet**, defaulting `effective_date` to today and **seeding the value with the
  user's last logged weight** (in their units). Reuse FTY-074's units-aware input
  and the FTY-070 create endpoint; convert to canonical kg only at the API
  boundary. After save, re-fetch so the new point and recomputed trend/delta
  appear. Weight entry stays here on Trends — deliberately not on Today, not
  buried in Profile (§4b).

### Weigh-in reminder (cadence + due-only notification)

- A **cadence preference** with options **Weekly · Every 2 weeks · Monthly · Off**,
  default **Weekly**. Store it as an **on-device setting** for v1 (see
  Cadence-persistence decision); surface the same control here on Trends and,
  later, in Profile (FTY-102) reading the same stored value.
- Schedule a **due-only** local notification: it fires only when the next weigh-in
  is **due** relative to the cadence and the user's **last logged weigh-in date**
  — i.e. one scheduled reminder at `last_weigh_in + cadence_interval`, rescheduled
  forward whenever a new weight is logged or the cadence changes. **Never a daily
  or fixed repeating notification.** "Off" cancels any scheduled reminder.
- Logging a weight (or it already being logged within the current period) clears /
  pushes the pending reminder forward — the user is never nudged for a reading
  they've already taken. No streaks, no daily prompts, no scale-watching copy.
- If local notifications require a new dependency (e.g. `expo-notifications`),
  declare it as an added/approved dependency in the implementation PR with a brief
  justification and update story metadata first, per FTY-013's dependency rule
  (mirroring how FTY-074 handled the charting dependency). Request notification
  permission with a clear, calm rationale; a denied/undetermined permission must
  degrade gracefully (the cadence preference still works; no reminder fires) and
  never block the screen.

### Cross-cutting

- Rebuild all of the above against the **FTY-097 design system** tokens/components
  (type, accent, light/dark, spacing) — do not hand-roll styles the design system
  owns.
- Handle empty / sparse (single-point) / loading / error states for both the
  weight panel and the adherence panel so neither ever looks broken; Trends-empty
  shows the calm invite from §6 ("Log your first weigh-in").
- Accessible per §7: VoiceOver labels for the headline delta and chart, a text
  alternative/summary for the smoothed trend, Dynamic Type, ≥44pt targets, never
  color as the sole signal in the adherence strip, Reduce-Motion respected.

## Non-Goals

- **The weight backend / API** — merged in FTY-070; consumed, not changed.
- **Changing the daily-summary contract** — consumed as-is (FTY-071); the null vs.
  zero target distinction is honored, not redefined.
- **Macro target derivation** (FTY-094) — the adherence summary measures kcal vs.
  the existing `target.calories`; it does not derive or measure macro targets.
- **Server-side persistence of the cadence preference** — kept on-device for v1
  (see decision below). No new endpoint, schema, or contract.
- **Target re-calibration from the observed weight trend** — explicitly excluded
  by `weight-entries.md` / `target-calculator.md`; out of scope here.
- **Editing/deleting past weight entries** beyond what FTY-074 already provides.
- **Push notifications / server-driven reminders** — local notifications only.
- **New chart range options requiring a contract** — ranges are client-side over
  the existing list-range endpoint.

## Contracts

- **None new.** Consumes the existing **weight-entries** create + list-range DTOs
  (`docs/contracts/weight-entries.md`) and the **daily-summary** DTO
  (`docs/contracts/daily-summary.md`). The cadence preference is on-device state
  for v1, so it introduces no server contract. If a future story moves cadence to
  the server, that is a separate backend/contracts story this one does not block.

## Security / Privacy

- Body weight and daily nutrition totals are **sensitive personal data**: fetched
  and submitted only over the authenticated API (TLS), shown only to the
  authenticated owner, and **never written to logs, error messages, analytics, or
  notification bodies** (the reminder text must not contain any weight value or
  number — a generic "time for your weekly weigh-in" only). Errors carry only HTTP
  status + endpoint, mirroring the profile/weight client.
- The cadence preference and last-weigh-in date held on-device for scheduling are
  non-sensitive scheduling metadata; no weight values are persisted locally beyond
  the normal app state/cache needed to render the screen and seed the entry sheet.
- Local notifications only — no new external egress, no server reminder channel.
- Medium risk: sensitive per-user data plus client-side notification scheduling
  and smoothing logic, but no server logic or contract of its own.

## Acceptance Criteria

- Trends leads with a **smoothed weight-trend line** drawn over the raw daily
  points; the smoothed line is the visual lead and a single noisy reading does not
  dominate. EWMA uses a documented smoothing factor and a seeding rule that
  renders sparse/early ranges without a startup artifact.
- A **range selector** drives both the weight chart and the adherence summary over
  the same range; switching range updates both.
- The **headline delta** shows current smoothed value + signed change over the
  range in the user's units (FTY-021), computed from the smoothed trend.
- The **intake-adherence summary** shows avg kcal vs. target, days-on-target, and
  a per-day adherence strip over the range, sourced from the daily-summary
  endpoint. **Null-target days** render as a distinct state and are excluded from
  the days-on-target denominator (never counted as a miss).
- **Tapping a day** opens that day's timeline (the existing Today-for-date view).
- **"+ log weight"** opens a numeric sheet defaulting to today, seeded with the
  last logged weight; saving persists via FTY-070's create endpoint (verified
  through the endpoint) and the new point + recomputed trend/delta appear after
  re-fetch; units convert only at the API boundary.
- The **cadence preference** defaults to **Weekly**, offers Weekly · Every 2 weeks
  · Monthly · Off, persists on-device, and is read back on relaunch.
- The reminder is scheduled **due-only**: exactly one reminder at
  `last_weigh_in + cadence_interval`, rescheduled forward on a new weigh-in or a
  cadence change; **no daily or fixed-repeat notification is ever scheduled**;
  "Off" cancels it; a denied notification permission degrades gracefully and never
  blocks the screen.
- No weight value or nutrition number is emitted to logs, error output, or
  notification bodies.
- Empty / sparse / loading / error states render gracefully for both panels;
  Trends-empty shows the calm "Log your first weigh-in" invite.
- Accessibility per §7 (VoiceOver, text alt for the chart, Dynamic Type, ≥44pt,
  no color-only signal, Reduce-Motion).
- TypeScript strict passes; mobile checks pass via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), run mobile typecheck, lint,
  and tests via `make verify` where wired.
- Component / unit tests:
  - **Trend smoothing render** — EWMA over a known noisy series produces the
    expected smoothed line (a deterministic, snapshot-stable trend), seeding makes
    a single-point and sparse range render without artifact, and a one-day spike
    does not swing the trend line (the core "encourage the trend" property).
  - **Range switching** — selecting each range re-derives both the weight chart
    and the adherence summary over that range and updates the headline delta.
  - **Adherence summary** — avg kcal vs. target, days-on-target counting, the
    per-day strip, and the **null-target exclusion** rule (null days are a
    distinct state, not a miss, and not in the denominator).
  - **Weight-entry sheet** — defaults to today, seeds the last value in the user's
    units, converts to canonical kg at submit, posts to FTY-070's create endpoint
    (mocked), surfaces success/failure, and re-fetch shows the new point.
  - **Past-day drilldown** — tapping a day routes to that date's timeline view.
  - **Due-only reminder scheduling** — a test asserts that scheduling produces a
    single reminder at `last_weigh_in + interval` for each cadence, that logging a
    weight / changing cadence reschedules forward, that "Off" cancels, and
    crucially that **no daily/repeating notification is ever scheduled** (the
    never-daily guarantee is explicitly asserted, not implied), with notification
    APIs mocked.
  - **Accessibility** — labels on the delta and chart, a text alternative/summary
    for the trend, and the adherence strip not relying on color alone.
- Integration tests against mocked FTY-070 (create + list-range) and FTY-071
  (daily-summary) endpoints.
- On an iOS simulator: log a weight from Trends and confirm the point + smoothed
  trend + delta update; switch ranges; tap a day to open its timeline; toggle
  cadence and confirm a due-only reminder is scheduled (and "Off" clears it).

## Research note (evidence basis)

- **Weigh-in cadence (default weekly, due-only, no streaks)** is settled and
  evidence-grounded in §4b of the design doc: weekly weighing captures the full
  weight-loss benefit (daily confers no added benefit in RCTs), ~4 readings/month
  is plenty for a meaningful trend, and the psychological harm of self-weighing is
  daily-specific. This story implements that decision; the reminder is
  low-frequency and due-only by design, per the *Encourage the trend, not the
  scale* principle.
- **Smoothing method (EWMA).** The one open technical decision the design doc
  leaves unspecified ("smoothed" without an algorithm). Grounded in established
  practice: an **exponentially-weighted moving average** is the standard
  body-weight trend smoother (The Hacker's Diet, John Walker; adopted by
  Trendweight/Libra-style apps), precisely because daily body-weight noise is
  mostly water and a one-day spike should *blunt*, not jerk, the trend line —
  which is exactly the "lead with the trend, de-emphasize any single reading"
  behavior §4b requires. Recommendation that overrides a naive choice: prefer EWMA
  over a plain N-day simple moving average (which lags and reacts hard to a single
  outlier entering/leaving the window). Use one documented smoothing-factor
  constant, seeded from the first reading.
  - Sources: [Hacker's Diet — Signal and Noise](https://www.fourmilab.ch/hackdiet/e4/signalnoise.html),
    [Hacker's Diet — Moving averages](https://www.fourmilab.ch/hackdiet/www/subsection1_2_4_0_4.html),
    [EWMA for weight tracking (summary)](https://www.shortform.com/blog/ewma-formula/).

## Readiness Sanity Pass

- **Sizing decision:** one boundary — **mobile-core** only. No code in a second
  serializing lane. No big rock: no public contract change (consumes existing
  weight-entries + daily-summary DTOs), no schema migration, no untrusted-input
  trust boundary (local notifications are not untrusted input). `review_focus` = 5
  (at the ceiling, not over); `requires_context` = 7 (under the 8 ceiling). It
  bundles several UI pieces but they are one cohesive screen rebuild on one author
  run — not a cross-lane split. Stays a single story.
- **Cadence-persistence decision:** the weigh-in cadence preference is kept as an
  **on-device setting for v1**, surfaced here and (later) in Profile FTY-102 over
  the same stored value. This deliberately avoids pulling in the backend/contracts
  lane (which would make this a cross-boundary, must-split story). If a future
  story needs cross-device persistence, it becomes a separate backend story
  (extend identity-and-profile) that this story does not block. Trade-off
  recorded: cadence does not survive reinstall/device change in v1 — acceptable
  for a low-frequency local reminder pre-v1.
- **Product decision gaps:** the chart **range option set** is marked *open* in
  §4b; instruction is to pick a sensible fixed set (default month) behind one
  configurable list, so it is settable without a contract change later. The
  on-target tolerance band and EWMA smoothing factor are documented single
  constants, justifiable and tunable. No blocking product gap.
- **Cross-lane impact:** none beyond mobile-core. Consumes FTY-070 + FTY-071 DTOs;
  defines no new server contract. Depends on FTY-097 design tokens being available.
- **Security/privacy risk:** medium — sensitive body-weight + nutrition data over
  the authenticated API; no values in logs/notifications; cadence + last-weigh-in
  date are non-sensitive scheduling metadata; local notifications only.
- **Verification path:** mobile component + integration tests against mocked
  FTY-070/FTY-071 endpoints (smoothing, range switch, adherence + null-target
  rule, entry sheet, drilldown, **due-only/never-daily** scheduling),
  accessibility checks, `make verify`, and a simulator smoke check.
- **Assumptions safe for autonomy:** yes. Dependency notes: FTY-097 must be merged
  for design tokens; FTY-070/071/074/075 are merged and consumed. A new
  notifications dependency (e.g. `expo-notifications`), if needed, must be declared
  per FTY-013's dependency rule before use.
