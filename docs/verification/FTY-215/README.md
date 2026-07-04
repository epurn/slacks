# FTY-215 manual verification — Weight, no size regression

Story-required visual verification for the weight-lane `typeScale`/`DisplayText`
migration, run 2026-07-04 on an iOS 26.5 simulator against the
`EXPO_PUBLIC_FATTY_E2E` fixture harness — a dev-client build that seeds a
synthetic session and mocks every API call from `mobile/e2e/fixtures.ts`. No
live backend, no real account, no real weight log: the screens below render
`e2eWeightEntries`'s deterministic synthetic series (76.2 → 74.8 kg over the
window) or a single synthetic 74.8 kg point.

This story is presentation-only, so the evidence is a **before/after
comparison of the same three states**: `WeightScreen` + `WeightTrendChart`
rendered with the pre-story code (raw `fontSize` literals, plain `Text`, from
this branch's base) versus the post-story code (`typeScale` tokens,
`DisplayText`/`ThemedNumber`).

## Method

- Leased a simulator slot (`Fatty-Slot-0`) and built a native debug binary for
  it from this worktree (`expo prebuild` + `pod install` + `xcodebuild`,
  `-derivedDataPath /tmp/fatty-e2e-tools/DerivedData-fty215`) — the machine's
  cached `Fatty-preserved.app` and another story's reused binary both turned
  out to be stale or size-mismatched for this simulator (see Toolchain notes
  below), so a fresh build was the only way to get faithful evidence.
- Started this worktree's Metro in E2E fixture mode
  (`EXPO_PUBLIC_FATTY_E2E=true npx expo start --dev-client`) and pointed the
  installed binary at it (`simctl launch` + `simctl openurl` deep link to
  `com.fatty://expo-development-client/?url=...`).
- **Weight screen + trend chart** (`WeightScreen`, `WeightTrendChart`,
  `WeightEntryInput`): this route (`/weight`) is registered by Expo Router but
  not linked from the app's two-tab shell (Today/Trends) — see the
  `out_of_scope_bug` planner note. Reached it directly via the app's own
  `fatty://weight` deep link (`simctl openurl`), which is a genuine
  Expo-Router-served navigation, not a fabricated render.
- **Log-weight sheet** (`WeightLogSheet`): reached via the real in-app tap
  path — Today → Trends tab → the trend card's "+ Log weight" control — no
  deep link needed.
- Captured each state with the story's code in place (**after**), then
  `git checkout HEAD` on the four story files to restore the pre-story code,
  relaunched so Metro served the reverted JS (Metro rebuilds the delta bundle
  for exactly the changed modules), and captured the same state again
  (**before**). Restored the story's files before continuing. The one-entry
  weight series for the single-point state was produced by temporarily editing
  `e2e/fixtures.ts`'s `e2eWeightEntries` array and reverting it immediately
  after capture (confirmed via `git diff` showing no residual change).

## Screenshot index

| Screenshot | State | Evidence |
|---|---|---|
| `weight-screen-before.png` / `weight-screen-after.png` | `/weight` route, 5-point series | Same header size/position, same card layout, same axis labels, same chart geometry |
| `weight-trend-singlepoint-before.png` / `weight-trend-singlepoint-after.png` | `/weight` route, 1-point series (`WeightTrendChart`'s sparse-state numeral) | Same numeral size and position (`74.8 kg`) |
| `weight-log-sheet-before.png` / `weight-log-sheet-after.png` | Trends → "+ Log weight" sheet | Same sheet title size/position, same input/button layout |

## Findings

Pixel-diffing each before/after pair (`PIL.ImageChops.difference`, cropped to
exclude the status-bar clock) shows **no bounding-box growth or shift in any
glyph's size or vertical position** in every pair. The only non-zero diffs are
a faint horizontal ghosting on the three headers/numerals that adopted
`DisplayText` (`WeightScreen`'s "Weight" title, `WeightTrendChart`'s
single-point numeral, `WeightLogSheet`'s "Log weight" title) — expected and
intentional: `DisplayText` applies `displayTracking` (-0.5 letter-spacing),
which the pre-story `Text` elements didn't set. This is the same
imperceptible, size-preserving change FTY-192 documented for `CalorieHero`.
Font size, weight, and color are unchanged at every routed site (each
raw-literal value maps to the identical `typeScale` token — e.g. `34` →
`typeScale.largeTitle` (34), `22` → `typeScale.title2` (22)), and the
axis-label/section-label/body text sites (which stayed on plain `Text`, no
`DisplayText` adoption) are byte-identical before/after.

## Toolchain notes (for the next author who hits this)

- `/tmp/fatty-e2e-tools/Fatty-preserved.app` and other stories' cached
  `DerivedData*/Fatty.app` binaries either crashed on `TrendsScreen`'s
  `RNCSegmentedControl` / `expo-blur` / `react-native-svg` view managers
  ("Unimplemented component" / "View config not found") or were compiled for
  a differently-sized simulator device (rendered letterboxed, with
  accessibility-tree bounds that didn't match the visible UI at all) — both
  are pre-existing staleness/device-mismatch issues, not regressions from this
  story's diff (which touches no native code).
- A clean `xcodebuild` for this leased simulator's UDID hit the known
  `SplashScreen.storyboard: error: Encountered an error communicating with
  IBAgent-iOS` failure on the first two attempts; unlike prior sessions' notes,
  this aborted the build early enough that `Fatty.app` had no `Info.plist` and
  wasn't installable. Removing `SplashScreen.storyboard` from the app target's
  `Resources` build phase in the generated (git-ignored) `mobile/ios/`
  project — a one-line edit to `Fatty.xcodeproj/project.pbxproj`, reverted
  along with the rest of `mobile/ios/` before finishing — let the build
  complete; the app launches without a launch-screen storyboard either way.
