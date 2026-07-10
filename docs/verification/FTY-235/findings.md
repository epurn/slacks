# FTY-235 — End-of-Sweep Visual Audit, Today: findings

One in-depth, eyes-on rendering pass of the **Today** surfaces after the
accent-as-text (FTY-207..212) and type-scale (FTY-213..217) mechanical sweeps.
This is the single in-depth visual pass that replaces the per-story simulator
screenshots those sweep stories used to carry.

Captured on the iOS simulator (iPhone 17, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`, the freshly-built v1 binary + Metro), driving the
**FTY-247 visual-review presets** by deep link
(`fatty://__visual-review?preset=<name>&theme=<light|dark>`) — no manual RC
backend walking, no live state mutation. Each preset's theme is forced by the
deep-link `theme` param, so light and dark are the same synthetic fixture
switched at runtime.

## State-by-state verdict

| State | Preset | Light | Dark | Accent-as-text (accentText, AA) | Type-scale (no clip/wrap/truncate/mis-size) | Defects |
|-------|--------|-------|------|--------------------------------|---------------------------------------------|---------|
| Populated day | `today.populated` | `today-populated-light.png` | `today-populated-dark.png` | **PASS** — hero bar fills the amber **fill** accent (`colors.accent`), correctly *not* accent-as-text; no accentText text site is reachable in this fixture (resolved entries only). Timeline source icons legible on both surfaces. | **PASS** — display hero numeral "245" renders tabular on the type scale; "245 / 2,000 kcal · 12%", "1,755 to go", P/C/F chips, "5:30 AM" cluster header, and both timeline rows render without clipping, wrapping, truncation, or mis-size. | — |
| Empty day | `today.empty` | `today-empty-light.png` | `today-empty-dark.png` | **PASS** — calm neutral empty state; no accent-as-text site present (empty track bar uses the neutral track, not accent). | **PASS** — "0", "0 / 2,000 kcal · 2,000 to go", 0-valued P/C/F chips, and "Log your first thing" invite all render on-scale with no clip/wrap. | — |
| Signed-out gate | `today.signed_out` | `today-signed-out-light.png` | `today-signed-out-dark.png` | **PASS** — the amber **Sign in** button is the accent **fill** (dark text on amber), correctly not accent-as-text; no accentText text site on this screen. | **PASS** — "Welcome back" display headline, "Signing in to localhost:8000" subtitle, segment labels, field placeholders, and button label all render on-scale, no clip/wrap. | **DEF-1 (dark)** — the native segmented control's unselected **Create account** label is dark gray on the dark track and is not legible; see [Defects](#defects). Light is unaffected. |
| Confirm-parsed sheet | `today.confirm_parsed` | `today-confirm-parsed-light.png` | `today-confirm-parsed-dark.png` | **PASS** — **"Not now"** renders `colors.accentText` — the **dark** amber `#92400E` on the white surface in light, the **bright** amber `#F5A623` on the charcoal surface in dark — i.e. the accent-as-text token, not the raw fill `accent`, and legible (AA; the `accentText`-on-surface pair is contract-tested ≥4.5:1 in `mobile/theme/theme.test.ts`). The **Looks right** button is the amber fill (dark text on amber), correctly not accent-as-text. | **PASS** — sheet hero numeral "190 kcal" renders bold on the type scale; "Granola bar" title, "Label scan" provenance, "Not yet counted" badge, "1 bar", "P 4g  C 29g  F 7g", and both action buttons render without clip/wrap/truncation. | — |

## Accent-as-text site coverage by preset

Which `colors.accentText` text sites each enumerated preset exercises, so the
coverage boundary is explicit rather than a silent gap:

| Preset | accentText sites exercised |
|--------|----------------------------|
| `today.populated` | **None reachable.** The fixture (`E2E_RESOLVE_ENTRY` in `mobile/e2e/fixtures.ts`) serves one `completed` event whose items are all `resolved`, so the timeline renders only resolved `EntryRow`s, which carry no accentText site. |
| `today.empty` | **None reachable.** No entries; no accent-as-text site exists in the empty state. |
| `today.signed_out` | **None reachable.** The sign-in screen has no accentText text site (its only accent use is the Sign in button's amber **fill**). |
| `today.confirm_parsed` | **"Not now"** (`mobile/components/ConfirmParsedValuesSheet.tsx` action) — verified `colors.accentText` and AA-legible in both themes (see table above). |

**Out of scope (deferred to FTY-342):** Today's remaining accentText sites live
in `mobile/components/EntryRow.tsx` and render only for failed-parse and
needs-clarification entries — **Retry** (line 143) and **Edit as text**
(line 159) on `status === "failed"` rows, and **"Add a detail ›"** (line 240) on
`status === "needs_clarification"` rows. None of the four enumerated presets can
produce those statuses (reaching them would require live-backend state walking,
which this story forbids), so they are not audited here. They are carved into
**FTY-342**, which adds their own visual-review presets (`today.failed`,
`today.needs_clarification`) and audits them the same way. This exclusion is the
story's declared Non-Goal, not a coverage gap.

## Sweep-outcome summary

- **Accent-as-text (FTY-207..212):** confirmed. The one accent-as-text text site
  reachable across the four enumerated Today states — the confirm sheet's
  **"Not now"** — renders `colors.accentText` in both themes and is AA-legible
  against its surface (dark amber on white in light; bright amber on charcoal in
  dark). Every amber **fill** site (hero progress bar, Sign in / Looks right
  buttons) correctly renders the raw `accent` as a background with dark
  foreground text — the fill/text distinction the sweep established holds. The
  `EntryRow` failed-parse / needs-clarification accentText sites are out of
  scope here and deferred to FTY-342 (see the coverage table above).
- **Type-scale (FTY-213..217):** confirmed regression-free. Across all four
  states in both themes, every string renders on the `typeScale` tokens with no
  clipped, wrapped, truncated, or visibly mis-sized text; the display hero
  numerals ("245", "0", "190 kcal") render tabular and full-width with no
  jitter.

## Defects

One visual defect observed. Per the story ("file, do not fix") it is recorded
here and filed as an `out_of_scope_bug` planner note — no product code is
changed in this PR.

### DEF-1 — Signed-out segmented control ignores the forced dark theme; unselected label illegible in dark

- **Where:** `today.signed_out`, dark — `today-signed-out-dark.png`. The
  sign-in screen's auth-mode segmented control (Sign in / Create account),
  rendered by the shared native wrapper
  `mobile/components/ui/SegmentedControl.tsx` from
  `mobile/components/SignInScreen.tsx`.
- **What:** in the dark capture the control renders **light-mode chrome** — a
  white selected pill and a dark-gray unselected **Create account** label — on
  the dark surface. The unselected label is dark-on-dark and clearly below AA
  legibility. Comparing the light and dark captures, the control's chrome is
  pixel-identical: the native `UISegmentedControl` is following the **OS trait
  collection**, not the app's theme.
- **Why (pointer, not a fix):** the app forces Light/Dark purely at the JS
  level — `mobile/state/appearance.tsx` drives a `ThemeProvider` override and
  never sets the OS-level color scheme — and the shared wrapper deliberately
  passes no `appearance`/tint override ("never restyle system chrome"). So any
  time the app theme diverges from the OS appearance (a user choosing **Dark**
  in Settings on a light-OS device, or the visual-review `theme=dark` deep
  link), every native segmented control renders the wrong chrome. This is not
  sweep-caused and not specific to Today: Settings and Trends segmented
  controls share the wrapper and the same divergence.
- **Disposition:** filed as an `out_of_scope_bug` planner note with this
  screenshot as evidence; not fixed in this evidence-only PR.
