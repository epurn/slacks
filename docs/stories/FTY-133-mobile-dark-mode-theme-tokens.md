---
id: FTY-133
state: ready_with_notes
primary_lane: mobile-core
touched_lanes: []
review_focus:
  - theme-all-seven-via-usetheme
  - dark-mode-renders-correctly
  - literal-to-token-mapping
  - on-accent-on-surface-foreground
  - snapshot-render-tests-updated
risk: low
tags:
  - mobile
  - dark-mode
  - design-system
  - theming
  - bug
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-133: Route the Seven Stuck-Light Components Through `useTheme()` Tokens (mobile)

## State

ready_with_notes

## Lane

mobile-core

## Dependencies

- **None to schedule.** This builds on the merged Milestone-10 design system
  (FTY-097): `theme/colors.ts` (the `lightPalette` / `darkPalette` token sets),
  `theme/ThemeContext.tsx` (`ThemeProvider` + `useTheme()`), and the 21 already
  theme-correct components are all on `main`. `approved_dependencies: []`.
- **Parallel-author note:** this story touches only `mobile/components/*` (the
  seven components + their test/snapshot files). FTY-136 touches only
  `mobile/api/*`. The two are disjoint by path, so although both are `mobile-core`
  they can author in parallel without a serialization conflict.

## Outcome

The design system ships light **and** dark charcoal themes that components read
through `useTheme()`. 21 components do this correctly. **Seven do not:** they
hardcode light-mode hex literals and never call `useTheme()`, so they render with
light-mode colors even when the device is in dark mode — a latent **dark-mode
correctness bug** (unreadable / off-theme surfaces in dark mode), not cosmetic
polish. This story routes all seven through `useTheme()` tokens so they respond to
the active theme like every other component.

The seven offenders (raw-hex literal counts, verified against the files on `main`):

1. `mobile/components/EditableItemRow.tsx` — 17 literals (reached via `EntryRow`
   → `TodayScreen`).
2. `mobile/components/LabelCaptureScreen.tsx` — 12 literals (rendered by
   `LogScreen` and `TodayScreen`).
3. `mobile/components/WeightEntryInput.tsx` — 9 literals (rendered by
   `WeightScreen` / `WeightLogSheet`).
4. `mobile/components/WeightTrendChart.tsx` — 7 literals (rendered by
   `WeightScreen`; includes a module-level `LINE_COLOR` constant).
5. `mobile/components/WeightScreen.tsx` — 7 literals (the `app/weight.tsx` screen).
6. `mobile/components/EntryRow.tsx` — 3 literals (rendered by `TodayScreen`).
7. `mobile/components/TypeaheadSuggestionBar.tsx` — 2 literals (rendered by
   `LogScreen` / `TodayScreen`). **Path correction:** the file lives at
   `mobile/components/TypeaheadSuggestionBar.tsx`, not under `components/ui/`.

All seven are live (transitively imported by `TodayScreen` / `WeightScreen` /
`LogScreen`), so the bug is shipping.

## Scope

- **Make every one of the seven components read its colors from
  `useTheme().colors`.** Add `const { colors } = useTheme();` (and, where styles
  are defined at module scope today, move the color-bearing style values into the
  render body or pass `colors` into a `makeStyles(colors)` factory so the values
  are theme-derived per render). Replace **every** raw hex literal — in
  `StyleSheet` blocks, inline `style={}`, `placeholderTextColor`, `color=` props
  on `ActivityIndicator` / icons, `trackColor` / `thumbColor` on `Switch`, and the
  `WeightTrendChart` `LINE_COLOR` constant — with the mapped token below.
- **Use the authoritative literal → token map** (verified against
  `theme/colors.ts` and the already-correct components). The first group is a
  clean 1:1 to an existing token; the second group has **no exact token** and maps
  to its **nearest design-system semantic token** (see Planning Notes for why this
  is the right call rather than inventing new colors):

  | literal | token | role |
  | --- | --- | --- |
  | `#1C1C1E` | `colors.text` | primary text (and, as a CTA *background*, see note) |
  | `#8E8E93` | `colors.textMuted` | muted/tertiary text |
  | `#636366` | `colors.textSecondary` | secondary text / inactive track |
  | `#A0A0A8` | `colors.textMuted` | placeholder text |
  | `#F2F2F7` | `colors.surface` | screen background |
  | `#FFFFFF` | `colors.surfaceRaised` | card / raised surface (see on-fill note) |
  | `#E5E5EA` | `colors.separator` | hairline separator |
  | `#C7C7CC` | `colors.separator` | control border (hairline family) |
  | `#3A3A3C` | `colors.textSecondary` | secondary detail |
  | `#E4E4EA` | `colors.controlBackground` | input / control fill |
  | `#C0392B` | `colors.coral` | alert / over-budget red |
  | `#FF453A` | `colors.coral` | destructive / error red (the palette's one red) |
  | `#0A84FF` | `colors.accent` | primary action / link / chart line |
  | `#9DC9FF` | `colors.controlBackground` (fill) + `colors.textMuted` (label) | disabled-button treatment |
  | `#0A7E3A` | `colors.accentText` | positive/confirmation text (no green in the palette) |
  | `#D1F0E0` | `colors.controlBackground` | positive/confirmation fill |

- **On-fill foreground correctness.** Where a literal was a label/spinner/icon
  rendered **on top of** a filled control (e.g. the white `ActivityIndicator` /
  white button label currently on a `#0A84FF` fill, or white content on a
  `#1C1C1E` dark CTA), map the *fill* per the table and the *on-fill content* to
  the matching on-color token: content on `colors.accent` → `colors.accentForeground`;
  content on a `colors.text`-coloured CTA → `colors.surface`. Do not leave a raw
  `#FFFFFF` label sitting on a now-themed fill.
- **Update the seven components' tests/snapshots** so they pass with the themed
  output, and add at least one dark-mode render assertion per component family
  (see Verification).

## Non-Goals

- **Do not add, rename, or change any palette token** in `theme/colors.ts`. This
  story maps onto the *existing* light/dark token sets only. Keeping the palette
  fixed is what keeps every edit inside `mobile/components/*` (a clean single
  boundary, disjoint from FTY-136) and avoids a design decision about new dark
  values. If a literal genuinely cannot map to an existing token, **stop and flag
  it** rather than inventing a hex or a token — the audit found none.
- **No behavioural or layout change.** Only color sources change: same components,
  same props, same structure, same flows. No new screens, no contract calls.
- **Do not touch the other 21 already-correct components**, `theme/*`, `api/*`, or
  any state module.
- **Not a visual redesign.** Where a scaffolding literal differs from its
  design-system token (the second map group — e.g. iOS-blue → `accent` amber),
  the resulting light-mode shift is the *intended* correction to the merged
  FTY-097 palette, not a new design; do not redesign these components beyond
  applying the token map.

## Contracts

- **None.** No API, schema, or contract surface is touched — this is a
  client-only theming fix. No `docs/contracts/*` file changes.

## Security / Privacy

- **None new.** No new input, stored field, network call, or permission. Pure
  presentation. Positive effect: the seven components stop rendering unreadable
  light-on-light (or wrong-contrast) surfaces in dark mode, which is the only
  user-facing risk being closed.

## Acceptance Criteria

- All seven listed components call `useTheme()` and source **every** color from
  `colors.*`; **zero raw color hex literals remain** in those seven files
  (including `placeholderTextColor`, `*Color` props, `Switch` track/thumb colors,
  and the `WeightTrendChart` `LINE_COLOR` constant). If any unavoidable literal
  remains it is justified inline with a comment and called out in the PR — none is
  expected.
- Each literal is replaced per the authoritative map above; on-fill content uses
  the matching on-color token (`accentForeground` / `surface`), not a bare white.
- In **dark mode** (`ThemeProvider override="dark"`) the seven components render
  with dark-palette colors (dark surfaces, light text) — proven by at least one
  dark-mode render/snapshot assertion per component (or component family).
- In **light mode** they render with the design-system tokens; updated snapshots
  reflect the token-aligned colors (expected diffs where a scaffolding literal
  differed from its token).
- No change to `theme/colors.ts`, the other 21 components, `api/*`, or state.
- `make verify` (mobile: `npm run typecheck && npm run lint && npm test`) passes.

## Verification

- Run the mobile verify path: `cd mobile && npm run typecheck && npm run lint &&
  npm test` (i.e. `mobile/verify.sh` / root `make verify`).
- **Raw-hex guard:** a `grep`/lint pass over the seven files shows no
  `#[0-9A-Fa-f]{3,6}` color literals remain (the objective signal the fix is
  complete).
- **Dark-mode render proof:** for each component (or family — Weight*, Entry/
  EditableItemRow, LabelCapture, Typeahead), render inside
  `<ThemeProvider override="dark">` and assert it picks up a dark-palette value
  (e.g. a surface resolves to `darkPalette.surface` / text to `darkPalette.text`),
  proving it now responds to the theme. A matching light-mode assertion guards the
  no-regression direction.
- **Updated snapshots** for the seven components reflect the themed output; the
  diff is limited to color values, not structure.

## Planning Notes

- **Why map to existing tokens instead of adding new ones.** The audit's "1:1
  map" covered the eight literals that have an exact token (`text`, `textMuted`,
  `textSecondary`, `surface`, `surfaceRaised`, `separator`, `controlBackground`,
  `coral`). Verifying against the real files surfaced a second group with **no
  exact token**: iOS-system blue `#0A84FF` (+ its disabled tint `#9DC9FF`), a
  success green `#0A7E3A` / `#D1F0E0`, a destructive red `#FF453A`, a control
  border `#C7C7CC`, a placeholder grey `#A0A0A8`, and a near-black `#3A3A3C`.
  These are pre-design-system scaffolding colors. Two options existed: (a) add new
  semantic tokens (interactive/positive/destructive) to both palettes, or (b) map
  each to its nearest existing design-system token. **Chosen: (b).** The merged
  `ux-design.md` deliberately uses a single **amber `accent`** as the interactive
  color and **`coral`** as its one alert red, with **no green** — so the
  scaffolding blue belongs on `accent`, the destructive red on `coral`, and the
  green "confirmation" on the amber `accentText`. Option (b) keeps the palette
  fixed, keeps the whole change inside `components/*` (no `theme/*` edit, so a
  clean boundary parallel to FTY-136), and avoids inventing dark-mode hex values
  that would themselves be an un-reviewed design decision. The cost — a few
  light-mode color shifts (blue→amber, green→amber) — is the intended alignment of
  scaffolding to the reviewed design system (clean-break: no users, kill the
  scaffolding debt).
- **The on-fill cases are the easy place to get it subtly wrong:** a white label
  or spinner that *used* to sit on a `#0A84FF` button must move to
  `accentForeground` (which is AA-safe on `accent` in both schemes), not stay
  white. Same for white content on the `#1C1C1E` dark CTA → `surface`.
- **Module-scope styles:** several of these define `StyleSheet.create({...})` at
  module scope with literals baked in. Since `useTheme()` is a hook, move the
  color-bearing values into render (inline or a `useMemo`/`makeStyles(colors)`
  factory) — a mechanical lift the already-correct components model.
- **No evidence research warranted:** the only decisions are UI-token mappings
  grounded in the merged design doc — not a health, nutrition, or behavioural
  question, so the evidence-backed-by-default rule does not apply here.

## Readiness Sanity Pass

- **Product decision gaps:** none left open. The one real judgment call (how to
  handle literals with no exact token) is **decided and pinned** above (map to the
  nearest existing design-system token; add no new tokens). Marked
  `ready_with_notes` because that mapping is a non-blocking note an author should
  read, not a missing decision.
- **Cross-lane impact:** primary `mobile-core`, **no touched lanes**. Pure
  client-presentation change. **Single boundary, zero big rocks:** no public
  contract change, no schema migration / new table, no new untrusted-input trust
  boundary. By holding `theme/colors.ts` fixed, all edits land in
  `mobile/components/*` (+ those components' test/snapshot files) — one path-set.
- **Size:** `review_focus` = 5 (at the ceiling, not over); `requires_context` = 3
  (well under 8). Comfortably one story; no split needed.
- **Parallel safety:** disjoint path-set from FTY-136 (`api/*`) — both `mobile-core`
  but safe to author concurrently.
- **Security/privacy risk:** low — no new surface; the change *closes* a
  dark-mode legibility defect.
- **Verification path:** `make verify` + a raw-hex guard + per-component dark-mode
  render assertions + updated snapshots.
- **Assumptions safe for autonomy:** yes — behaviour-preserving theming with the
  literal→token map pinned, the palette frozen, the on-fill foreground rule
  stated, and the "stop and flag if a literal won't map" escape hatch (none
  expected). No migration, no contract, no new color decision.
</content>
</invoke>
