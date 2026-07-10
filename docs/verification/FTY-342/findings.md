# FTY-342 visual-review EntryRow accentText findings

Status: **confirmed** with running-app evidence.

The Today `failed` and `needs_clarification` visual-review presets were opened on
a leased iOS simulator (iOS 26.5) against the installed E2E debug build, serving
this branch's JS with `EXPO_PUBLIC_FATTY_E2E=true`. Each state was reached purely
through the `fatty://__visual-review?preset=…&theme=…` deep link (no live
backend, no scripted taps), waiting on the shared
`visual-review-settled:<preset>` sibling-overlay marker before capture.

## Evidence

| Preset | Theme | Screenshot |
| --- | --- | --- |
| `today.failed` | light | `today-failed-light.png` |
| `today.failed` | dark | `today-failed-dark.png` |
| `today.needs_clarification` | light | `today-needs-clarification-light.png` |
| `today.needs_clarification` | dark | `today-needs-clarification-dark.png` |

## The three `EntryRow` accentText sites

All three render `colors.accentText` (the warm amber that darkens in light mode
and brightens in dark mode for contrast) — **not** the raw `colors.accent` — and
each reads AA-legible against its own surface in both themes:

- **`EntryRow.tsx:143` — failed-parse "Retry" action.** In
  `today-failed-{light,dark}.png` the "Retry" text renders in the accent-text
  amber against the white (light) / dark-grey (dark) failed row and is clearly
  legible in both.
- **`EntryRow.tsx:159` — failed-parse "Edit as text" action.** Same rows; the
  "Edit as text" action renders in the same accent-text amber and reads AA in
  both themes.
- **`EntryRow.tsx:240` — needs-clarification "Add a detail ›" chip.** In
  `today-needs-clarification-{light,dark}.png` the chip text renders in the
  accent-text amber on the `controlBackground` chip fill and is legible against
  it in both themes.

In light mode the accent-text tone is a deep amber (high contrast on the near-
white surfaces); in dark mode it is a brighter amber (high contrast on the dark
surfaces) — the theme-adaptive `accentText` token behaving exactly as intended.

## Defects observed

None. Both states render calmly in place with native chrome, the source glyph
(`!` failed / `?` needs-clarification) on the left, the uncounted `—` on the
right, and the accent-text affordances legible in both themes. No
`out_of_scope_bug` planner note is warranted.
