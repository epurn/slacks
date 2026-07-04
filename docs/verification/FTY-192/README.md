# FTY-192 manual verification — Today hero, no size regression

Story-required manual verification for the type-scale foundation (`DisplayText`
+ `typeScale` + the fontSize guard), run 2026-07-03 on an **iPhone 17 Pro
simulator (iOS 26.5)** against the **real backend** on `:18000` (an already
running RC), driven by the app's shared, previously-connected session — not
the E2E mock.

This story is presentation-only and touches no user-facing flow, so the
evidence is a **before/after comparison of the same screen** rather than a new
flow: the Today hero (`CalorieHero`) rendered with the pre-change code (raw
`Text` + manual `fontFamily: DISPLAY_FONT_FAMILY` override) versus the
post-change code (`ThemedNumber`, now built on the new `DisplayText`
primitive).

## Method

- Started this worktree's own Metro (`expo start --dev-client`) and
  re-pointed the already-booted, already-signed-in simulator app at it
  (`simctl terminate` + `simctl openurl com.fatty://...`), per the documented
  shared-simulator re-point recipe.
- Captured `today-hero-after-displaytext.png` with the story's changes in
  place.
- `git stash`-ed only `components/CalorieHero.tsx` (reverting it to the
  pre-story `Text` + inline `fontFamily` override), relaunched so Metro served
  the reverted JS, and captured `today-hero-before-displaytext.png`.
- Restored the stash (`git stash pop`) to return to the story's code before
  continuing work.

## Screenshot index

| Screenshot | State | Evidence |
|---|---|---|
| `today-hero-before-displaytext.png` / `-crop.png` | Pre-story `CalorieHero` (raw `Text` + manual `fontFamily` override) | Hero reads `0 / 1,643 kcal · 1,643 to go` |
| `today-hero-after-displaytext.png` / `-crop.png` | Post-story `CalorieHero` (routed through `ThemedNumber` → `DisplayText`) | Same layout, same copy, same hero size — the two crops are pixel-identical |
| `today-hero-after-displaytext-with-entry.png` | Post-story, same account with a logged (uncounted) entry present | Confirms the hero renders correctly once the timeline has content beneath it |

The before/after crops (`*-crop.png`, cropped to the hero card) are
pixel-identical: the `DisplayText` consolidation does not change the hero's
rendered size or position. The one intentional visual change — the hero
numeral now carries `displayTracking` (-0.5 letter-spacing) instead of the
previous explicit `letterSpacing: 0` override — is not perceptible at a single
"0" digit; `components/CalorieHero.test.tsx` (`CalorieHero — display face`)
asserts the tracking and `tabular-nums` directly on the rendered node.
