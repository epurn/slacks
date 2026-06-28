---
id: FTY-099
state: ready
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - mobile
  - log-page
  - composer
  - typeahead
  - redesign
  - design-system
approved_dependencies:
  - FTY-097
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/log-events.md
  - docs/contracts/saved-foods.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - stay-on-log-page-no-auto-nav
  - field-clear-rapid-successive-adds
  - in-place-skeleton-to-value-no-layout-shift
  - typeahead-reuse-backend-match-semantics
  - design-token-adherence-no-hardcoded-style
autonomous: true
---

# FTY-099: Log Page Redesign — Keyboard-Up Composer + Transient Added Feed

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-097 (design system: the token set — color/amber accent, type scale,
  spacing, and the skeleton/shimmer + in-place-fade primitives — this page is
  built against. **Must merge first**; this story consumes its tokens/primitives
  and adds none of its own.)
- FTY-053 (merged: the saved-food typeahead `TypeaheadSuggestionBar` + the
  `searchSavedFoods` client and synthetic-saved-food apply path this page reuses).
- FTY-063 (merged: the barcode scanner screen + camera scaffold this page wires an
  entry-point affordance to — capture internals unchanged).
- FTY-064 (merged: the label-capture screen + upload path this page wires an
  entry-point affordance to — capture internals unchanged).
- FTY-030 / FTY-032 (merged: the log-event create API and the
  `state/polling.ts` interval-polling primitives the transient feed reuses to
  drive a just-added entry from pending to its resolved values).

## Outcome

Fatty has a dedicated **Log page** that implements §3 (Logging loop) of the UX
design: a keyboard-up natural-language composer where the user describes food and
a saved-food typeahead surfaces reactively as they type, with barcode and label
capture sitting alongside as affordances. On submit the user **stays on the Log
page** — no navigation — the entry joins a live, transient "added" feed and the
input clears for the next entry, so rapid successive adds need no round-trip to
Today. While an entry resolves, its feed row shows a skeleton/shimmer that fills
**in place**; resolved values fade in exactly where the placeholder was, with no
layout shift. Returning to Today is a manual, user-initiated action. The page is
built entirely against the FTY-097 token set.

## Scope

- Add a standalone **Log page** as a new component (`components/LogScreen.tsx`)
  and a route (`app/log.tsx`) reachable in the app, built against the FTY-097
  design tokens — no hardcoded colors, type, or spacing.
- **Keyboard-up composer:** a natural-language text input that is the page's
  focus (keyboard presented on entry), submitting via the existing FTY-030
  `createLogEvent` API. Same `raw_text` rules as the contract (trimmed, non-empty,
  ≤ 2000 chars).
- **Reactive saved-food typeahead:** reuse the merged FTY-053
  `TypeaheadSuggestionBar` (and its `searchSavedFoods` client) beneath the input.
  Selecting a suggestion applies the stored saved food exactly as FTY-053 does
  (synthetic resolved item, estimator bypassed). The UI adds **no** client-side
  re-filtering — the backend owns match semantics (saved-foods contract).
- **Capture affordances:** barcode and label entry points rendered as
  SF-Symbol-style affordances alongside the composer, styled with FTY-097 tokens,
  that open the existing merged capture screens (FTY-063 barcode, FTY-064 label).
  Only the entry-point styling/wiring is in scope; the capture flows themselves
  are reused unchanged and dismiss back to the Log page.
- **Stay-on-page added feed:** submitted entries (typed, saved-food-applied,
  barcode, and label) stack in a transient, local in-memory feed on the Log page.
  The page never auto-navigates on submit. The composer input clears immediately
  after a successful submit so the next entry can be typed at once. Returning to
  Today is a manual control (the user leaves the page deliberately).
- **In-place thinking state:** each feed row first renders a skeleton/shimmer
  placeholder sized to the resolved row, then — driven to terminal status by the
  reused FTY-032 polling primitives (or immediately for an applied saved food) —
  fades the resolved values in **in the same slot**, with no reflow/layout shift.
  A barcode/label entry that the backend resolves in-request renders its resolved
  row directly (still via the in-place fade, no shift).
- Honor accessibility: VoiceOver labels on the capture affordances and feed-row
  state, Dynamic Type on composer + feed text, and a Reduce-Motion fallback where
  the shimmer→value transition degrades to a plain fade.

## Non-Goals

- The 3-tab navigation shell / tab bar (Today · Log · Trends) and removing the
  legacy composer from `TodayScreen` — a separate navigation story owns the shell
  and the Today cleanup. This story builds the Log page + route; it does **not**
  touch `TodayScreen`'s load/poll/timeline logic.
- Barcode and label **capture internals** — merged in FTY-063/FTY-064; only their
  entry-point styling and wiring are touched here.
- The Today canonical timeline (FTY-031): Today owns the persistent timeline; the
  Log feed is transient and does not replace or mirror it.
- The universal correction / detail slide-up sheet (FTY-100) — corrections are
  not part of this page.
- Offline capture / queueing of entries (FTY-104).
- Design tokens / the skeleton-shimmer primitive themselves (FTY-097 — consumed
  here, not defined).
- The smart context-aware food recommender and any proactive "recents" list (v2 —
  explicitly out per §3 / §v2-parked).
- Any backend, contract, or schema change.

## Contracts

- **No new contract.** Consumes the existing FTY-030 log-event create API and
  event DTO/status enum (`docs/contracts/log-events.md`) and the existing
  saved-foods typeahead search + `SavedFoodDTO` (`docs/contracts/saved-foods.md`).
  Reuses, does not redefine, FTY-061/FTY-064's label-upload path and FTY-060/
  FTY-063's barcode path via their merged capture screens.

## Security / Privacy

- None new. The composer text and saved-food phrases are sensitive personal data
  already handled by the merged FTY-030/FTY-053 clients — this page reuses those
  clients unchanged and adds no new logging of `raw_text`, query text, or feed
  contents. No new network surface, credential, or trust boundary is introduced;
  capture (the only untrusted-image path) is the merged FTY-064 flow, unchanged.

## Acceptance Criteria

- The Log page presents a keyboard-up natural-language composer styled with
  FTY-097 tokens (no hardcoded color/type/spacing) and submits via the existing
  `createLogEvent` API.
- Typing surfaces the FTY-053 saved-food typeahead reactively; selecting a
  suggestion applies the stored food (estimator bypassed) exactly as FTY-053
  does, with no added client-side re-filtering.
- Barcode and label affordances sit alongside the composer and open the existing
  merged capture screens, dismissing back to the Log page.
- On a successful submit the page **stays** on Log (no navigation is triggered),
  the entry appears in the transient added feed, and the composer input clears so
  another entry can be typed immediately. Multiple successive submits stack in the
  feed without leaving the page.
- A just-added feed row shows a skeleton/shimmer placeholder, then the resolved
  values fade in **in the same slot** with no layout shift (placeholder and
  resolved row occupy the same footprint); resolution is driven by the reused
  FTY-032 polling (or is immediate for an applied saved food / in-request-resolved
  capture).
- Reduce Motion degrades the shimmer→value transition to a plain in-place fade;
  VoiceOver labels exist on the capture affordances and convey feed-row resolving
  vs. resolved state; composer and feed text scale with Dynamic Type.
- `TypeScript strict`, lint, and the mobile test suite pass via the mobile verify
  hook.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), component/integration tests
  for `LogScreen` with injected API/search functions (no real network), covering:
  - **Submit → stay-on-page:** a successful submit does not call any navigation
    function and the page remains mounted; the created entry appears in the feed.
  - **Field clear + rapid adds:** the composer value is empty after a successful
    submit, and two successive submits both appear in the feed.
  - **Added feed accumulation:** typed, saved-food-applied, and capture-originated
    entries all land in the transient feed.
  - **Typeahead reuse:** a saved-food selection applies the stored nutrition
    (estimator-bypass path) and the bar applies no extra client-side filtering.
  - **In-place skeleton → value, no layout shift:** a pending feed row renders the
    skeleton placeholder and, once polled/resolved, renders resolved values in the
    same slot — assert the row footprint is stable across the transition (e.g. a
    fixed placeholder sized to the resolved row), and that Reduce Motion yields a
    plain fade.
  - Accessibility: capture affordances expose VoiceOver labels; feed rows expose
    a resolving-vs-resolved accessibility state.
- Run the mobile verify hook (`mobile/verify.sh`: `npm ci`, `npm run typecheck`,
  `npm run lint`, `npm test`), via root `make verify` where wired — the same path
  FTY-053/FTY-064 use.
- On an iOS simulator: open the Log page, type and submit an entry, confirm the
  keyboard stays up, the field clears, the entry resolves in place in the feed
  with no jump, and that opening then dismissing barcode/label returns to Log.

## Planning Notes

- The composer logic already exists inside `TodayScreen.tsx` (optimistic create,
  saved-food apply via `syntheticSavedFoodItem`, barcode/label modals, the
  `state/polling.ts` primitives). This story lifts that pattern into a dedicated
  `LogScreen` against FTY-097 tokens — it does **not** edit `TodayScreen`, so it
  cannot conflict with Today's persistent timeline/poll logic. Removing the
  now-duplicate Today composer is deferred to the navigation-shell story (a clean
  pre-v1 break, no users).
- The "added feed" is transient local state, not a second source of truth: Today
  (FTY-031) remains the canonical timeline. The feed only needs each row to reach
  its resolved values for the in-place fade; reuse `hasPendingWork` /
  `useIntervalPolling` rather than inventing a new mechanism.
- Keep all API/search/poll dependencies injectable (the established mobile test
  seam) so no real network call runs in tests.

## Readiness Sanity Pass

- Product decision gaps: none — §3 resolves the behaviors (keyboard-up composer,
  reactive typeahead, capture-alongside, stay-on-page added feed with field-clear,
  in-place skeleton→fade, manual return to Today, no proactive recents in v1). The
  tab-bar shell and Today-composer removal are deliberately deferred to a separate
  navigation story and listed as non-goals.
- Sizing decision: single boundary, single story. One serializing lane
  (mobile-core), zero big rocks — no public contract change (consumes existing
  log-event + saved-foods contracts), no schema migration, and no new
  untrusted-input trust boundary (capture is the merged FTY-064 flow, reused
  unchanged). `review_focus` = 5 (at the ceiling, not over) and `requires_context`
  = 5 (under 8), so no size breach forces a split; scope is held down by making
  the navigation shell, Today cleanup, correction sheet, and offline queueing
  explicit non-goals.
- Cross-lane impact: none beyond mobile-core. Defines no contract; reuses merged
  mobile components and existing backend contracts only.
- Security/privacy risk: none new — reuses merged clients; no new logging,
  network surface, credential, or trust boundary.
- Verification path: injected-dependency component/integration tests for
  stay-on-page, field-clear/rapid-add, feed accumulation, typeahead reuse, and the
  in-place skeleton→value no-layout-shift + Reduce-Motion fade, plus the mobile
  verify hook and a simulator pass.
- Assumptions safe for autonomy: yes, with one gate — **FTY-097 must merge first**
  (this page is built against its tokens and skeleton/shimmer primitive). The
  reuse surfaces (FTY-053 typeahead, FTY-063/064 capture, FTY-030/032 create +
  polling) are all merged.
