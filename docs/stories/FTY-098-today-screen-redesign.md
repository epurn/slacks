---
id: FTY-098
state: ready
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - mobile
  - today
  - redesign
  - hero
  - provenance
  - design-system
approved_dependencies:
  - FTY-097
  - FTY-092
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/daily-summary.md
  - docs/contracts/log-events.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - hero-accuracy-under-and-over-budget
  - exercise-not-conflated
  - provenance-icons-always-on-light-dark
  - needs-a-detail-uncounted
  - empty-state-and-time-clustering
---

# FTY-098: Today Screen Redesign

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-097 (design system / tokens — the redesign is built against FTY-097's
  color, type, spacing, and component tokens, including the amber accent, the
  coral over-budget color, the display numeral face, and light/dark surfaces.
  **Must merge first**: this story consumes its tokens and never hardcodes the
  palette or type scale.)
- FTY-092 (per-item provenance + `is_edited` in the read-model — the timeline's
  always-on source icon and the "✎ edited" marker read the provenance/`is_edited`
  fields FTY-092 surfaces. **Must merge first.**)
- FTY-031 / FTY-075 (the existing Today timeline + daily-summary surface this
  story rebuilds — `TodayScreen.tsx`, `DailySummary.tsx`, `EntryRow.tsx`; the
  data-fetch, polling/refresh, optimistic-add, and error/loading wiring are
  retained and re-skinned, not rewritten.)

## Outcome

The Today screen is rebuilt as the **status-first home** described in
`docs/design/ux-design.md` §4 (and the over-budget / empty edges in §6), against
the FTY-097 design tokens. A user opening Today sees, in priority order:

1. a **hero** that is calories-consumed-vs-target only — a bold display number
   plus a slim amber linear bar ("1,240 / of 2,000 kcal · 62%"), one focus;
2. a **secondary tier** of macro chips (P / C / F) followed by a visually
   **distinct** "🔥 burned" exercise line — exercise is not in the hero and is
   not a fourth macro;
3. an **items-forward timeline** grouped into ~10–15-minute time clusters, each
   item showing name · kcal · an **always-on source icon**, with corrected items
   carrying the "✎ edited" icon and "needs a detail" entries shown muted and
   visibly uncounted.

The screen degrades to a calm **empty state** before anything is logged (full
budget available, gentle single invite) and to a clear **over-budget** hero when
intake exceeds the target (amber to the target line, a coral over-segment past
it, copy flips to "X over"). All states render correctly in light and dark and
read coherently under VoiceOver.

This replaces the current functional-scaffolding Today layout (a refresh button,
a four-tile `DailySummary` grid, and a flat newest-first list) with the resolved
v1 design.

## Scope

Rebuild the Today presentation layer in `mobile/components/` against FTY-097
tokens, reusing the existing data/fetch/polling wiring in `TodayScreen.tsx`:

- **Hero (calories vs. target).** A single bold display numeral (FTY-097 tabular
  face, no width jitter as it updates) over a slim linear progress bar. Under
  budget: amber fill to `consumed / target`, copy "1,240 / of 2,000 kcal · 62%"
  with "X to go". The bar and number read from the existing daily-summary
  `intake.calories` and `target.calories`.
  - **Over-budget (§6):** when `intake.calories > target.calories`, the amber
    fills to 100% at the target line and a **distinct coral over-segment** extends
    beyond it; both portions stay visible; the copy flips "X to go" → "**X over**".
    The over state is **always paired with the "over" text** — never signalled by
    color alone.
  - **Null target:** when `target` is JSON `null` (no active goal / day predates
    the goal, per the contract's no-target representation), the hero degrades
    gracefully — show consumed calories without a budget bar / percentage and a
    calm "no target set" treatment, never a divide-by-zero or a misleading 0/0.
- **Secondary tier.** Macro chips for protein / carbs / fat (consumed grams from
  `intake.protein_g` / `carbs_g` / `fat_g`), then a separate "🔥 burned" exercise
  line from `exercise.active_calories`. Exercise stays out of the hero math and is
  visually distinct from the macro chips (not a fourth chip).
- **Items-forward timeline with time clusters.** Group entries whose log-event
  `created_at` falls within a ~10–15-minute grace window into a single cluster
  (text-message-chain style), newest cluster first. Each item row shows
  **name · kcal · an always-on source icon** (provenance from FTY-092). The raw
  typed phrase is no longer shown inline on the row (it moves to the item sheet,
  FTY-100); tapping a row is wired to a sheet-open hook (the sheet itself is out
  of scope — the hook can be a no-op/stub here).
- **Corrected items.** An item with FTY-092 `is_edited` true carries the
  "✎ edited" source icon in its row — treated as just another provenance, no
  special-case card.
- **"Needs a detail" entries.** An entry awaiting clarification renders
  muted/de-emphasized with a gentle inline tag, is **visibly uncounted** (it must
  not contribute to the hero/macro/burn figures — these already exclude
  non-finalized items per the daily-summary finalized-state filter), and its row
  tap targets the same clarify-mode sheet hook (sheet is FTY-100).
- **Empty state (§4).** Before anything is logged, the hero shows the full target
  as available ("0 / 2,000 kcal · 2,000 to go") in a calm neutral tone with an
  empty bar track — never an alarming zero — and the timeline shows one soft
  invite ("Log your first thing") anchored to the Log CTA. Oriented, not blank,
  not a coachy illustration.
- **Retain existing behavior.** Keep the FTY-032 polling/refresh, optimistic-add,
  loading skeleton/shimmer-in-place, error banners, and the signed-out state
  wiring already in `TodayScreen.tsx`; this is a presentation rebuild over the
  same fetch path, re-skinned to FTY-097 tokens.
- **Accessibility (§7).** Full Dynamic Type (display hero scales within sane
  bounds, no jitter); a VoiceOver label on the hero ("1,240 of 2,000 kcal, 62%,
  760 remaining" / the "over" phrasing when over budget); a VoiceOver label on
  every provenance and "✎ edited" icon; ≥44pt tap targets; never color as the
  sole signal; WCAG AA contrast in both themes.

## Non-Goals

- **The detail / correction sheet itself (FTY-100)** — this story only wires the
  row-tap and clarify hooks; opening, editing, change-match, and clarify-mode are
  FTY-100.
- **Macro TARGET derivation / comparison (FTY-094, backend)** — the macro chips
  show **consumed** grams only; comparing P/C/F against a target arrives with
  FTY-094's macro targets in the read-model and is out of scope here.
- **The design tokens themselves (FTY-097)** — this story consumes them; it does
  not define the palette, type scale, or shared components.
- **The Trends and Profile screens** — only Today is rebuilt.
- **Any backend, contract, schema, or estimator change** — pure mobile
  presentation over the existing daily-summary + log-events read-models.
- **Signature motion/haptic beats beyond what FTY-097 provides** — the in-place
  fades and the hero-bar easing are honored; net-new designed haptic moments are
  not introduced here.

## Contracts

- **None authored.** Consumes the existing daily-summary DTO
  (`docs/contracts/daily-summary.md`) — `intake.calories`, `intake.protein_g/
  carbs_g/fat_g`, `target.calories` (nullable), `exercise.active_calories`, and
  its finalized-state filter (so "needs a detail" / pending items stay uncounted)
  — plus the **per-item provenance + `is_edited`** fields FTY-092 adds to the
  read-model the timeline already reads, and the log-events timeline contract
  (`docs/contracts/log-events.md`) for entry `created_at` (the basis for time
  clustering). No new field is defined here.

## Security / Privacy

- Displays the authenticated user's **own** nutrition data (calories, macros,
  target, burn, item names, provenance) — sensitive personal data, fetched over
  the authenticated API and shown only to the owner. No new trust boundary.
- These figures and item names are **never logged** (security baseline); the
  redesign introduces no new on-device persistence beyond render state.
- No external egress, no LLM, no provider secrets on the client.
- Medium risk is from UI-correctness surface area (over-budget math, uncounted
  items, provenance fidelity), not from a new privacy or security boundary.

## Acceptance Criteria

- The hero shows calories-consumed-vs-target as a bold display number plus a slim
  amber bar with the "X / of Y kcal · Z%" copy and "X to go", matching the
  daily-summary figures for today.
- **Under budget:** the bar fills amber proportionally; **over budget:** the bar
  fills amber to the target line then a distinct coral over-segment past it, and
  the copy reads "X over" (the over state is conveyed by text, not color alone).
- **Null target:** the hero degrades gracefully (consumed shown, no bar/percent,
  calm "no target set" treatment) with no crash or misleading 0/0.
- Macro chips show consumed P / C / F grams; the "🔥 burned" exercise line is
  visually distinct and exercise is not folded into the hero or shown as a fourth
  macro.
- The timeline is items-forward and groups entries within a ~10–15-minute window
  into time clusters (newest first); each item shows name · kcal · an always-on
  source icon; the raw phrase is not shown inline on the row.
- Corrected items carry the "✎ edited" icon; "needs a detail" entries render
  muted with a gentle tag, are visibly uncounted, and tapping them targets the
  (stubbed) clarify hook.
- The empty state shows the full-budget calm hero ("0 / Y kcal · Y to go") with an
  empty bar track and a single soft "Log your first thing" invite — not an
  alarming zero, not blank.
- All of the above render correctly in **light and dark** (FTY-097 surfaces) and
  expose VoiceOver labels on the hero and on every provenance / "✎ edited" icon;
  ≥44pt tap targets; AA contrast.
- Existing Today behavior (polling/refresh, optimistic add, loading/error, signed-
  out) still works.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), with daily-summary and the
  FTY-092 read-model mocked:
  - **Hero render tests:** under-budget (proportional amber bar, "X to go"),
    over-budget (amber-to-target + coral over-segment, copy flips to "X over"),
    and null-target (graceful "no target set", no bar) — each asserting the copy
    text, not just color.
  - **Secondary-tier test:** macro chips render consumed P/C/F; the "🔥 burned"
    line renders distinctly and is not counted toward the hero.
  - **Timeline / clustering test:** entries within the grace window group into one
    cluster; entries outside it form separate clusters; newest first.
  - **Provenance test:** each item row shows the always-on source icon for its
    FTY-092 provenance; an `is_edited` item shows the "✎ edited" icon; a
    "needs a detail" entry renders muted, uncounted, and taps the clarify hook.
  - **Empty-state test:** full-budget calm hero + single invite, empty bar track.
  - **Light/dark render tests:** hero (under + over budget), empty state, and
    provenance icons render under both FTY-097 themes.
  - **Accessibility checks:** hero VoiceOver label (including the over-budget
    phrasing), provenance/edited icon labels, ≥44pt tap targets.
- Run the mobile package checks via `make verify` (delegates to
  `mobile/verify.sh`: `npm ci`, `npm run typecheck`, `npm run lint`, `npm test`).
- On an iOS simulator: view Today under budget, drive it over budget (confirm the
  coral over-segment + "X over" copy), view the empty state, and toggle
  light/dark — confirming the hero, macro/burn tier, clustered provenance
  timeline, and "edited" / "needs a detail" markers all read correctly.

## Planning Notes

- This is the presentation half of the Today redesign; it sits on top of the
  existing `TodayScreen.tsx` fetch/polling/optimistic wiring (FTY-031/032/075),
  re-skinning `DailySummary.tsx` into the hero + secondary tier and `EntryRow.tsx`
  into the clustered, provenance-bearing item row. Keep the data path; replace the
  chrome.
- The hero needs `target.calories`; the contract makes it nullable — the
  null-target branch is a real edge (no active goal), not a loading state, and is
  called out explicitly above.
- Macro-target comparison is deliberately deferred to FTY-094 so this slice stays
  in one boundary and doesn't block on a backend read-model change.
- Provenance/`is_edited` come from FTY-092; if FTY-092 has not merged, the source
  icon and edited marker have no data to read — hence the hard dependency.

## Readiness Sanity Pass

- **Product decision gaps:** none open — §4 and §6 of `docs/design/ux-design.md`
  resolve the hero, secondary tier, timeline clustering, empty state, over-budget
  treatment, and the corrected / "needs a detail" markers. Two design-doc "open"
  items (the exact licensed display font; chart range options) do not touch this
  screen — the font is carried by FTY-097's type token; charts are Trends.
- **Cross-lane impact:** single boundary — mobile-core only. No contract authored;
  it consumes the existing daily-summary + log-events read-models and FTY-092's
  added provenance fields. No backend/schema/estimator change. No new untrusted-
  input trust boundary (user's own data, no image/OCR/fetch path here).
- **Security/privacy risk:** medium-from-UI-correctness, not from a boundary —
  own-data display, never logged, no new persistence, no egress, no secrets.
- **Verification path:** mobile render tests (hero under/over/null-target, empty
  state, time-clustering, provenance + edited + needs-a-detail, light/dark) +
  accessibility checks + `make verify` + a simulator smoke pass.
- **Sizing decision:** one boundary (mobile-core), zero big rocks (no contract
  change, no migration, no new trust boundary). `review_focus` = 5 (at the
  ceiling) and `requires_context` = 5 (under the 8 ceiling) — at most one field at
  its limit, so no split required. The redesign is deliberately kept buildable by
  pulling the design tokens (FTY-097), the provenance read-model (FTY-092), the
  macro targets (FTY-094), and the correction sheet (FTY-100) into their own
  prerequisite/sibling stories; this story is the Today **presentation** slice
  that consumes them.
- **Assumptions safe for autonomy:** yes, once FTY-097 and FTY-092 are merged —
  this slice builds against FTY-097's published tokens and FTY-092's published
  provenance/`is_edited` fields and re-skins the existing FTY-031/032/075 Today
  surface. The macro-target comparison and the item sheet are explicit non-goals,
  so the author cannot be drawn across a boundary chasing them.
- **Research:** not warranted — this implements an already-resolved, evidence-
  grounded design (status-first, separated exercise, calm over-budget tone); no
  new factual/health/behavioural decision is being made here.
