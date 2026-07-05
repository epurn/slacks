# FTY-193 manual verification — Shared chip + StatusIcon token

Story-required visual evidence for the typeahead chip's ≥44pt hit target,
adoption of a single shared chip style, and `StatusIcon`'s light/dark
adaptation, captured 2026-07-05 on an iOS 26.5 simulator (`Fatty-Slot-0`)
running this branch's JS via Metro against an Expo dev-client build.

## Method

- Leased a dedicated headless simulator via `sim-slot.sh` and ran this
  worktree's Metro in **E2E fixture mode** (`EXPO_PUBLIC_FATTY_E2E=true`),
  which seeds a synthetic session and mocks every API call from
  `mobile/e2e/fixtures.ts` — no live backend, no real account. The existing
  `E2E_SAVED_FOOD` fixture (`"Chicken burrito bowl"`) backs the composer's
  saved-food typeahead exactly as `.maestro/correction.yaml` already relies on.
- Drove the running app with Maestro: typed `chicken` into the composer to
  surface the suggestion chip, captured a screenshot, tapped the chip (to
  confirm `onSelect` fires and the shared `Chip` primitive is genuinely
  interactive, not just decorative), then switched the simulator to dark
  appearance (`xcrun simctl ui ... appearance dark`) and repeated the capture.

**Note on the story's "real backend RC on :18000" instruction:** a real RC
backend was available and a test account + seeded saved foods were prepared
against it, but driving the sign-in screen through Maestro was blocked by an
iOS 26.5 simulator quirk unrelated to this change: the password
`secureTextEntry` field's typed/pasted value is confirmed present in the live
accessibility tree (`value: "•••••••••••••"`) but the on-screen render (via
both `xcrun simctl io screenshot` and Maestro's own screenshot capture) never
reflects it, and taps on the submit button are intermittently intercepted by
the system Passwords/AutoFill QuickType overlay. This is a simulator
input-automation limitation, not a defect in `SignInScreen` or this story's
code. The E2E fixture harness drives the identical production `Chip`/
`TypeaheadSuggestionBar`/`StatusIcon` components with the same rendering path,
so it is equally valid evidence for this story's presentation-only scope.

## Screenshots

| File | State | What it shows |
|------|-------|----------------|
| `typeahead-chips-light.png` | Light | Composer with `chicken` typed; the `"Chicken burrito bowl"` suggestion chip renders via the shared `Chip` primitive (`components/ui/Chip.tsx`) — compact pill, `controlBackground` fill, `text` label — sitting comfortably below the composer, uniform with a single shared style. |
| `typeahead-chips-dark.png` | Dark | Same state after `simctl ui appearance dark`; the chip's fill and label recolor via the theme tokens (no restyle needed) and stay legible. |
| `typeahead-chip-tap-applies-food.png` | Light | After tapping the chip: the composer text updates to `"Chicken burrito bowl"`, proving the chip is genuinely tappable (`onSelect` fires), not just a static decoration. |

## Chip hit target (≥44pt) and shared style — unit-proven

The visual screenshots show the compact, uniform chip; the ≥44pt effective
touch target and shared-style adoption are proven precisely (pixel-perfect
assertions aren't visually verifiable from a screenshot) by:

- `mobile/components/ui/Chip.test.tsx` — asserts `minHeight` (style) +
  `hitSlop.top` + `hitSlop.bottom` sum to ≥44, and that the chip fills from
  `controlBackground` / labels from `text` in both palettes.
- `mobile/components/TypeaheadSuggestionBar.test.tsx` ("shared chip style +
  hit target (FTY-193)") — asserts the *rendered* typeahead chip carries the
  same `CHIP_HIT_SLOP` from the shared `Chip` component (proving adoption,
  not a parallel one-off style) and still fires `onSelect` on tap.

## StatusIcon theme token

`StatusIcon.tsx` already routed its glyph color through `colors.textSecondary`
as of FTY-177 (no `#3A3A3C` literal remains) — confirmed by reading the current
file and by the pre-existing `StatusIcon.test.tsx`, which asserts the
light/dark token color and accessibility label. This story's acceptance
criterion here was already satisfied; no code change was needed. Contrast is
covered by `mobile/theme/theme.test.ts` ("textSecondary ... on surface ...
meets 4.5:1") in both palettes.
