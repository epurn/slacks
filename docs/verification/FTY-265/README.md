# FTY-265 — Visual-review seam: weight-log sheet sub-state — running-app evidence

Captured on the iOS simulator (iPhone, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the committed
`mobile/.maestro/visual-review-smoke.yaml` entry point — the `weight.sheet`
preset opened by deep link and captured only after its
`visual-review-settled:weight.sheet` marker appeared. Same running binary +
Metro as the rest of the flow: no rebuild between presets.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `weight-sheet-light.png` | `weight.sheet` | `fatty://__visual-review?preset=weight.sheet&theme=light` | The weight-log sheet opens on mount from the E2E-only initial-state seam (no scripted "+ Log weight" tap) over synthetic data: it presents atop Trends' weight card (75.7 kg / ↓0.5), seeded with the last synthetic weight entry (74.8 kg) with the submit button enabled, proving both the sheet **and** its data have settled before the marker appeared |

## What this proves

- **Reachability without a scripted tap**: the flow only opens
  `fatty://__visual-review?preset=weight.sheet` — `TrendsScreen`'s own
  `sheetVisible` initial-state seam (gated on `isE2EMode()`) opens the sheet on
  mount, from `components/TrendsScreen.tsx`, registered through the FTY-247
  `registerVisualReviewPreset` API, not the shared registry/manifest files.
- **Settled-after-data, not settled-after-navigation**: the generic
  `VisualReviewSettleOverlay` (owned by FTY-247) renders at the navigator level
  and is unreachable while a native sheet is presented — a presented iOS sheet
  occludes its presenter from the accessibility tree, which the first capture
  attempt surfaced directly (the marker assertion timed out even though the
  sheet itself was visible and correctly populated). `weight.sheet`'s marker is
  therefore rendered by `WeightLogSheet` itself (a new, optional
  `settledMarkerTestID` prop, unset — and thus inert — outside this preset),
  gated on the weight-entries read reaching `"ready"`, so the marker cannot
  appear before the seeded value has actually resolved.
- **Fixed a related pre-existing gap while proving this**: `WeightEntryInput`
  only consumed its `initialValue` seed prop at first mount (a `useState`
  lazy initializer). Because this seam opens the sheet *before* Trends' own
  weight-entries read resolves — synchronously, unlike the button-press path,
  which only becomes reachable after that data has already loaded — the field
  used to stay stuck on the blank placeholder even after the real value arrived.
  The first capture attempt (a since-discarded screenshot) showed exactly that:
  a settled marker next to a still-blank `"0.0"` field. `WeightEntryInput` now
  re-syncs its seed once, only while the field is still pristine, which fixed
  the capture above (showing the real `74.8` kg seed with the submit button
  enabled) and also closes the same latent gap for a real user who taps
  "+ Log weight" before Trends' own data has finished loading.

## Full smoke-flow pass (regression proof)

The same run drove `visual-review-smoke.yaml` end-to-end — `today.populated`,
`trends.populated`, `today.empty`, `weight.sheet`, `today.signed_out`, and
`today.populated` again (the non-sticky signed-out reseed guard) — all six
presets passed in one binary with no rebuild, proving the new preset does not
disturb the existing FTY-247 presets or their settled markers.
