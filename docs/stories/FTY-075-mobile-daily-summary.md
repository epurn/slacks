---
id: FTY-075
state: merged
primary_lane: mobile-core
touched_lanes: []
risk: low
tags:
  - daily-summary
  - today
  - mobile
  - calories
  - macros
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
  - docs/contracts/target-calculator.md
review_focus:
  - separated-figures-not-conflated
  - empty-day-state
  - refresh-on-entry-change
autonomous: true
---

# FTY-075: Mobile Daily Summary on Today

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-071 (daily totals / daily-summary endpoint this consumes)
- FTY-031 (Today timeline the summary augments)
- FTY-032 (polling/refresh this reuses)

## Outcome

The mobile Today screen shows a daily summary at a glance: the calories the user
has consumed, their macros, the day's calorie target, and the day's exercise
burn — with intake and exercise burn shown **separately**, never silently netted
into a single number. The summary is backed by FTY-071's daily-summary endpoint
and refreshes as the day's entries change (e.g. as pending items complete),
reusing the existing FTY-032 polling/refresh mechanism.

## Scope

- Add a compact summary header/section to the FTY-031 Today timeline that renders
  four figures distinctly:
  - intake calories consumed today,
  - macros (protein / carbs / fat),
  - the day's calorie target,
  - exercise burn for the day.
- The summary may additionally display net (intake − burn), but the four
  component figures must remain individually visible per the roadmap acceptance —
  net never replaces or hides the components.
- Fetch the figures from FTY-071's daily-summary endpoint for today.
- Reuse the FTY-032 polling/refresh path so the summary updates as visible
  entries reach terminal status, without introducing a separate poller. The
  summary reconciles to the latest fetched totals.
- Render a graceful empty-day state (no entries yet today): the summary shows
  zeroed intake/macros/burn and the target without looking broken.
- Handle loading and error states sensibly, consistent with the existing Today
  screen.
- Keep the summary accessible (iOS-first, compact) with accessible labels on each
  figure, and use compact, nonjudgmental copy per the coding standards.

## Non-Goals

- Weekly or historical summaries (this slice is today only).
- Charts or visualizations, including the weight chart (FTY-074).
- Editing entries, targets, or anything from the summary surface.
- Any new backend endpoint, server logic, or estimator/target-calculator change —
  this is a presentational mobile slice consuming FTY-071.
- Combining intake and exercise burn into a single conflated calorie figure.

## Contracts

- None new. Consumes FTY-071's daily-summary DTO (intake calories, macros,
  target, exercise burn) over the authenticated API. The separated
  intake-vs-burn presentation aligns with the target-calculator contract
  (`docs/contracts/target-calculator.md`), where exercise burn is credited to the
  day's allowance **separately** from the TDEE-based target and is deliberately
  excluded from the target math.

## Security / Privacy

- Daily totals (calories, macros, target, burn) are sensitive body/health data;
  the summary is shown only to the authenticated owner, fetched over the
  authenticated API (TLS).
- The summary figures must not be logged, and no additional sensitive on-device
  storage is introduced beyond what is needed to render and refresh the summary.
- Low risk: presentational mobile UI reading an existing per-user endpoint, with
  no server logic of its own.

## Acceptance Criteria

- The Today screen shows a summary with intake calories, macros, the day's
  target, and exercise burn for today, each rendered as a distinct figure
  (intake and exercise burn are not conflated).
- The figures match FTY-071's daily-summary endpoint response for today.
- As visible entries reach terminal status (e.g. pending → completed) via the
  existing refresh/polling path, the summary updates without manual refresh.
- The empty-day state renders gracefully (zeroed intake/macros/burn plus the
  target), with no broken or misleading display.
- Loading and error states render sensibly.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile):
  - Component tests for the summary section: renders the four separated figures
    from a mocked FTY-071 response; intake and exercise burn are shown as
    distinct values; net (if shown) does not replace the components.
  - Empty-day state test (zeroed intake/macros/burn plus target renders
    gracefully) and loading/error state tests.
  - Refresh test: when the underlying totals change (a pending entry completes
    via the FTY-032 refresh path), the summary reconciles to the new figures.
  - Accessibility checks (iOS-first, compact): accessible labels on each figure.
- Run mobile typecheck, lint, and tests via `make verify` (delegates to the
  mobile package: `tsc --noEmit`, `eslint .`, `jest`).
- On an iOS simulator, view Today with entries present and confirm the four
  figures render distinctly and update as a pending entry completes.

## Planning Notes

- Augments FTY-031's Today timeline rather than introducing a new screen; the
  summary is a header/section on the existing timeline.
- Reuses FTY-032's polling/refresh rather than adding a second poller, so the
  summary and timeline stay in sync from one fetch path.
- FTY-071 (daily-summary endpoint) is the backing data source; this slice builds
  against its published DTO and adds no contract of its own.

## Readiness Sanity Pass

- Product decision gaps: none — settled. Four figures shown distinctly (intake,
  macros, target, exercise burn); intake and burn never conflated; net optional
  but must keep components visible; today only; no charts, history, or editing.
- Cross-lane impact: none beyond mobile-core; consumes FTY-071's DTO and defines
  no new contract. Aligns with the target-calculator contract's separate-burn
  convention.
- Security/privacy risk: low — sensitive totals shown only to the authenticated
  owner over TLS, not logged; no new on-device sensitive storage.
- Verification path: mobile component tests (separated figures, empty-day,
  loading/error, refresh) + accessibility checks + `make verify` + simulator
  check.
- Assumptions safe for autonomy: yes. Dependency note: FTY-071 may not yet be
  merged — this is a dependency note, not a blocker; the slice builds against its
  published daily-summary surface and reuses the existing FTY-031/FTY-032 Today
  UI.
