# FTY-408 — Quick-add default for a previously-corrected food

Running-app evidence for the quick-add default (visual acceptance criterion).

## What the shots prove

Captured on the iOS simulator (iOS 26.5) against the app's E2E build, driven by
`mobile/.maestro/quick-add-default-fty408.yaml`. The shared FTY-247
`today.suggestions` visual-review preset seeds `/food-suggestions` with a
history-only `Black coffee` candidate (`saved_food_id: null`) — the shape a food
the user has corrected before takes (a completed history row). The flow types
`black coffee` into the composer; the **"From your log" → Black coffee** default
surfaces below the composer. Tapping it prefills the composer, and the submit
routes through the estimator, where FTY-406's prior-correction tier resolves the
corrected value.

| File | Theme |
| --- | --- |
| `quick-add-default-light.png` | Light |
| `quick-add-default-dark.png` | Dark |

Both frames are the settled screen with `black coffee` typed and the default
chip + amber "From your log" caption visible (the Maestro flow asserts
`quick-add-default` and the `From your log` text before each screenshot).
