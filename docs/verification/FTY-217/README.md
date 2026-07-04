# FTY-217 manual verification — Trends, no size regression

Story-required visual verification for the trends-lane `typeScale`/`DisplayText`
migration, run 2026-07-04 on an iOS 26.5 simulator against the
`EXPO_PUBLIC_FATTY_E2E` fixture harness — a dev-client build that seeds a
synthetic session and mocks every API call from `mobile/e2e/fixtures.ts`. No
live backend, no real account, no real weight log: the screens below render
`e2eWeightEntries`'s deterministic synthetic series (76.2 → 74.8 kg over the
window) or a single synthetic 74.8 kg point.

This story is presentation-only, so the evidence is a **before/after
comparison of the same two states**: the Trends screen's headline delta and
`EWMATrendChart`'s single-point numeral, rendered with the pre-story code (raw
`fontSize` literals, plain `Text`) versus the post-story code (`typeScale`
tokens, `ThemedNumber`/`DisplayText`).

## Method

- Leased a simulator slot (`Fatty-Slot-0`) and reused the native debug binary
  already built for FTY-215 that same day
  (`/tmp/fatty-e2e-tools/DerivedData-fty215/.../Fatty.app`) — this story makes
  no native-dependency change, so the FTY-215 binary (built after FTY-221's
  `expo-symbols` addition) is faithful for this worktree's JS.
- Started this worktree's Metro in E2E fixture mode
  (`EXPO_PUBLIC_FATTY_E2E=true npx expo start --dev-client --port 8090`) and
  pointed the installed binary at it (`simctl launch` + `simctl openurl` deep
  link to `com.fatty://expo-development-client/?url=...`).
- **Trends headline** (`TrendsScreen`'s multi-point weight-trend card, reached
  via the app's own Today/Trends tab bar — no deep link needed): captured with
  the story's code in place (**after**), then `git checkout HEAD` on the two
  story files to restore the pre-story code, which Metro Fast-Refreshed in
  place (confirmed the screen stayed on the Trends tab across the refresh),
  and captured the same state again (**before**). Coordinate-based taps
  (`tapOn: {point: "75%, 96%"}`) drove the Trends tab because the iOS
  accessibility tree did not expose the tab bar's "Trends" text node this
  session (unrelated infra quirk — see the toolchain memory note); the
  screenshots confirm the correct screen loaded either way.
- **EWMATrendChart single-point numeral**: `e2e/fixtures.ts`'s
  `e2eWeightEntries` array was temporarily reduced to one entry (`[0, 74.8]`)
  to force the chart's sparse single-point state, the Today→Trends tabs were
  re-tapped to force a refetch under the new fixture, and the state was
  captured with the pre-story code, then again with the story's code restored.
  `e2e/fixtures.ts` was reverted to its committed content immediately after
  (confirmed via `git status` showing no residual change).
- Restored the story's two files before finishing.

## Screenshot index

| Screenshot | State | Evidence |
|---|---|---|
| `trends-headline-before.png` / `trends-headline-after.png` | Trends tab, 5-point series, 1-month range | Same headline numeral size/position/weight (`75.7 kg`), same delta text, same chart geometry |
| `weight-trend-singlepoint-before.png` / `weight-trend-singlepoint-after.png` | Trends tab, 1-point series (`EWMATrendChart`'s sparse-state numeral) | Same numeral size and position (`74.8 kg`) |

## Findings

Each before/after pair renders pixel-identically: no bounding-box growth or
shift in the headline numeral's or the single-point numeral's size or
position. This is the expected outcome — `ThemedNumber`'s `title1`/`title2`
scales resolve to the same point sizes (28 / 22) the raw literals used, and
`DISPLAY_FONT_FAMILY` still resolves to the system font (SF Pro), so swapping
`Text` for `ThemedNumber`/`DisplayText` is a no-visible-change refactor today —
it only changes what happens when a licensed geometric grotesque is bundled
into `DISPLAY_FONT_FAMILY` later (every display-face surface, Trends included,
updates in one place instead of missing this migration).

## Toolchain notes

- Same self-contained Maestro/JDK toolchain as prior stories
  (`/tmp/fatty-e2e-tools/`); see the accumulated project-memory note on iOS
  simulator verification for JDK/Maestro paths and known iOS accessibility
  quirks.
- The tab bar's "Trends" text was not found via Maestro's text selector this
  session (`Element not found: Text matching regex: Trends`) despite being
  visibly rendered — `maestro hierarchy` returned only the status-bar overlay,
  not the app content. Worked around with percentage-point taps against the
  visible tab bar position; screenshots confirm each tap landed on the correct
  screen.
