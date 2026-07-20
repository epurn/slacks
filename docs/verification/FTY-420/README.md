# FTY-420 — Composite meal entry: one row, tap to expand the breakdown

Running-app evidence for the visual acceptance criteria, captured on the iOS
simulator (iPhone 17 Pro, iOS 26.5) driving the E2E debug binary against the
`today.meal` visual-review preset (a multi-item meal event carrying a
model-generated `name`, seeded through the shared registry — see
`mobile/e2e/visualReview/presets.ts`). Captured with
`mobile/.maestro/meal-entry-visual-review.yaml`.

The preset seeds one completed `log_event` named **"Turkey sandwich"** with three
resolved derived items — Turkey breast (90), Sub bun (150), Lettuce (3) — so the
collapsed total is 243 kcal (= 90 + 150 + 3), matching the hero.

| State | Light | Dark |
| --- | --- | --- |
| Collapsed — one meal row (`event.name` + summed total) | `today-meal-collapsed-light.png` | `today-meal-collapsed-dark.png` |
| Expanded — per-item breakdown (food · portion · calories/macros) | `today-meal-expanded-light.png` | `today-meal-expanded-dark.png` |

## What the shots prove

- **One row per meal.** The multi-item meal renders as a single Today row —
  the model-generated name "Turkey sandwich" and the meal total (243 kcal) — with
  a leading disclosure chevron, not three loose item rows.
- **Tap to expand the breakdown.** Tapping the meal row rotates the chevron and
  reveals the per-item breakdown: each food with its provenance icon, its portion
  ("3 oz", "half", "2 leaves"), its P/C/F macros, and its calories.
- **Every item editable.** Each breakdown row is a button that opens the existing
  item edit / correction flow (proven end-to-end by the jest flow test
  `mobile/components/TodayScreenMealEntry.test.tsx`, which taps a breakdown item,
  drives the portion stepper, and asserts the collapsed total re-sums).
- **Total is the sum.** The collapsed 243 kcal equals the sum of the breakdown
  items and matches the day hero.

## Reproduce

```sh
# lease a simulator, install a recent valid Slacks.app, point it at your Metro
eval "$("$SLACKS_SIM_SLOT" acquire --label fty-420)"
cd mobile
EXPO_PUBLIC_SLACKS_E2E=true npx expo start --dev-client --host localhost --port "$SLACKS_METRO_PORT" &
xcrun simctl install "$SLACKS_SIM_UDID" <path>/Slacks.app
xcrun simctl spawn "$SLACKS_SIM_UDID" defaults write com.slacks RCT_jsLocation "localhost:$SLACKS_METRO_PORT"
maestro --udid "$SLACKS_SIM_UDID" test .maestro/meal-entry-visual-review.yaml
```
