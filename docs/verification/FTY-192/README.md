# FTY-192 manual verification — Today hero, no size regression

Story-required visual verification for the type-scale foundation (`DisplayText`
+ `typeScale` + the fontSize guard), run 2026-07-04 on an iOS 26.5 simulator
against the **E2E fixture harness** — the `EXPO_PUBLIC_FATTY_E2E` dev build
that seeds a synthetic session and mocks every API call from
`mobile/e2e/fixtures.ts`. No live backend, no real account, no real nutrition
logs: the Today hero renders `E2E_DAILY_SUMMARY`'s deterministic synthetic
numerals (`0 / 2,000 kcal · 2,000 to go`, from the `E2E_TARGET` fixture) over
an empty fixture timeline.

This story is presentation-only, so the evidence is a **before/after
comparison of the same hero surface**: `CalorieHero` rendered with the
pre-change code (raw `Text` + manual `fontFamily: DISPLAY_FONT_FAMILY`
override, from `origin/main`) versus the post-change code (`ThemedNumber`,
built on the new `DisplayText` primitive).

## Method

- Started this worktree's Metro in E2E fixture mode
  (`EXPO_PUBLIC_FATTY_E2E=true npx expo start --dev-client`) and pointed a
  leased simulator's dev-client at it (`simctl terminate` + `simctl openurl`
  deep link). The harness boots straight into the fixture session — no
  sign-in, no server.
- Captured the **after** frame with the story's changes in place.
- Checked out `origin/main`'s `mobile/components/CalorieHero.tsx` (the
  pre-story `Text` + inline `fontFamily` override), relaunched so Metro served
  the reverted JS (Metro's delta bundle rebuilt exactly the one changed
  module), and captured the **before** frame.
- Restored the story's `CalorieHero` before continuing.
- Cropped each frame to the hero card with `sips`; only the hero-numeral
  crops are committed.

## Screenshot index

| Screenshot | State | Evidence |
|---|---|---|
| `today-hero-before-displaytext-crop.png` | Pre-story `CalorieHero` (raw `Text` + manual `fontFamily` override) | Hero reads `0 / 2,000 kcal · 2,000 to go` (synthetic fixture numerals) |
| `today-hero-after-displaytext-crop.png` | Post-story `CalorieHero` (routed through `ThemedNumber` → `DisplayText`) | Same layout, same copy, same hero size |

The two crops are **byte-identical** (`cmp` reports no difference): the
`DisplayText` consolidation does not change the hero's rendered size or
position. The one intentional visual change — the hero numeral now carries
`displayTracking` (-0.5 letter-spacing) instead of the previous explicit
`letterSpacing: 0` override — is not perceptible at a single "0" digit;
`components/CalorieHero.test.tsx` (`CalorieHero — display face`) asserts the
tracking and `tabular-nums` directly on the rendered node.
