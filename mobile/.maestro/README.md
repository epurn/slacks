# Maestro E2E Flow Tests (FTY-160)

This directory contains [Maestro](https://maestro.mobile.dev/) YAML flows for
Slacks's end-to-end test harness. Maestro drives the app via the accessibility
tree against a real running device or simulator — the fidelity that catches UI
regressions that unit tests miss (e.g. a sheet that opens but is data-starved).

## Why Maestro (not Detox, not Expo Go)

**Maestro vs Detox.** Detox requires a custom native dev build with a Detox
config plugin and a heavier gray-box instrumentation layer. Maestro is the
Expo-recommended E2E tool for managed-workflow apps: a single CLI, YAML flows,
no app-code changes to drive it, and black-box operation via the accessibility
tree. It is the right fit for Expo SDK 56 managed workflow (react-native 0.85,
new architecture, config plugins expo-router / expo-camera / expo-secure-store).

**Debug binary — not Expo Go.** These flows target a debug binary built from
`expo prebuild` + the native toolchain. Expo Go cannot faithfully host this
app's config plugins and new-architecture build, and is not a deterministic
target (shared client, OTA fetch, version skew). The debug binary is also the
target for the non-required manual/scheduled `mobile-e2e` workflow.

## Prerequisites

1. **Maestro CLI** installed:
   ```sh
   curl -Ls "https://get.maestro.mobile.dev" | bash
   ```
2. An **Android emulator** or **iOS simulator** running (or a connected device).
3. An E2E debug binary installed on the device (see "Running locally" below).

## Running locally

Use the `verify-e2e.sh` runner from the `mobile/` directory:

```sh
cd mobile
./verify-e2e.sh
```

This script:
1. Builds the E2E debug binary with `EXPO_PUBLIC_SLACKS_E2E=true` (iOS simulator
   by default; set `PLATFORM=android` to build an APK).
2. Installs the binary on the active simulator/emulator.
3. Runs `maestro test .maestro/` — every flow in this directory.

## CI coverage

The required PR mobile gate is the fast `mobile` job. It does not build native
code, boot an emulator, or run this directory. The full Maestro suite remains
available as non-required evidence through the manual/scheduled `mobile-e2e`
workflow, which runs the same directory-level harness and uploads Maestro
failure artifacts for debugging.

**Running the flow directly** (if you already have the binary installed):

```sh
cd mobile
maestro test .maestro/smoke.yaml
```

## Bundle ID

The flows use bundle ID `com.slacks`. Expo prebuild generates the native iOS
bundle identifier and Android package from `app.json`, and each Maestro flow
declares the same literal `appId` so directory-level runs launch the installed
app under test reliably. If the app ID changes, update `app.json` and every flow
`appId` together.

## Flows

| File | What it tests |
|------|---------------|
| `smoke.yaml` | App launches in E2E mode → Today mounts **and** its timeline reaches the ready, non-error state — data-present, not data-starved (FTY-160) |
| `clarify.yaml` | Full clarify path: submit an entry → needs-a-detail row appears → tap row → clarify sheet shows the seeded question (data-starved sheet fails here) → free-text answer → entry resolves and counts in Today totals (FTY-162) |
| `failed-parse.yaml` | Failed-parse UX: submit gibberish → "Couldn't read that" row appears with Retry + Edit-as-text (never a static dead end) → tap Retry → the failed row is superseded in place by a fresh pending attempt, no stale duplicate (FTY-176) |
| `profile.yaml` | Profile native header: tap the Today gear → the "Profile" native large-title header renders with the grouped settings inset below it → the Goal row still opens its inline editor → Done dismisses back to Today (FTY-182) |
| `trends.yaml` | Trends hierarchy: open Trends → weight card renders real data → the cadence card is absent (it moved to Preferences) → tap the compact Log weight control → the weight sheet opens usable, not data-starved (FTY-187) |
| `resolve.yaml` | Entry-resolve beat (beat 1) real data-path + item-forward guard: submit a multi-item log → one pending skeleton row appears → pull-to-refresh loads the completed item-forward `/log-events/by-date` feed → the first resolved row ("Greek yogurt, 140 kcal") reuses the event row, the second row ("Banana, 105 kcal") is visible/editable, and the hero counts both items (a data-starved or secondary-hiding Today fails here) (FTY-180/181) |
| `correction.yaml` | Correction-saved beat (beat 2) real data-path: submit a log → it resolves → tap the resolved row → the correction sheet opens → step the portion up → the sheet shows the server-recomputed value ("175 kcal"), the successful commit the correction-saved beat rides (FTY-181) |
| `target.yaml` | Target-reached beat (beat 3) real data-path: hero mounts under target ("0 of 2,000 kcal", seeds not-reached) → submit a large log → pull-to-refresh → the day summary crosses the target and the hero flips to its over-budget end state ("2,100 of 2,000 kcal, 100 over budget"), the crossing the target-reached beat rides (FTY-181) |
| `reduce-motion.yaml` | Reduce Motion (all beats): under the reduce-motion build the harness forces `isReduceMotionEnabled` true, so the beats take their no-motion branch; the resolve value row still eases in (a fade, not a spring) and counts, proving the no-motion path reaches the same successful end state. Run via `E2E_REDUCE_MOTION=1 ./verify-e2e.sh` (see below) (FTY-181) |
| `barcode-manual-entry.yaml` | Barcode "Type it instead" fallback: open the scanner from Today → the granted chrome renders ("Point at a barcode"; permission granted via the E2E stub since the simulator has no camera) → tap "Type it instead" → the scanner dismisses and the composer is pre-filled with the "1 serving of " starter, the never-a-dead-end running start into NL logging (FTY-194) |
| `visual-review-smoke.yaml` | Visual-review mode launcher: open named presets by deep link (`slacks://__visual-review?preset=…&theme=…`) and wait for each `visual-review-settled:<preset>` marker before screenshotting — `today.populated` (light), `trends.populated` (dark), `today.empty`, the Today-owned sub-state preset `today.confirm_parsed` (FTY-262), the Today failed/needs-clarification EntryRow presets `today.failed` / `today.needs_clarification` in light and dark (FTY-342), the weight-owned sub-state preset `weight.sheet` (light, the weight-log sheet's open sub-state, FTY-265), and the onboarding-owned sub-state presets `onboarding.goal` / `onboarding.measurements_formula` / `onboarding.target_reveal` (FTY-266). The reusable launcher the screen visual audits (FTY-235..241) consume instead of hand-writing temporary YAML (FTY-247) |
| `server-url-fty405.yaml` | Settings server address: open Settings → ACCOUNT & SERVER with the base-URL editor open (`settings.server_edit`), type a malformed address → it is rejected in place; then on `settings.server_switch` (which answers `/healthz` like a live server) type a new address → probe → confirm → the session is dropped and the app lands on sign-in **naming the new host**, the proof there is no cross-server token reuse. Light + dark (FTY-405) |

## Visual-review mode (named-state launcher)

The **visual-review** harness opens any named screen/state directly via a deep
link — with synthetic data and a forced light/dark theme — so screenshot tooling
never has to rebuild the app or author throwaway flows. Same E2E gate as above.
Entry point, preset manifest, settled markers, and the registration API for
per-screen sub-state presets are documented in
[`../e2e/visualReview/README.md`](../e2e/visualReview/README.md).

### iOS launch: no manual "Open in Slacks?" dismissal (FTY-269)

Opening the `slacks://` deep link on the iOS simulator can surface a one-time OS
security confirmation ("Open in Slacks?") the first time the app is opened via
its custom scheme on a given simulator — accepting it is a permanent choice for
that simulator, so a fresh/erased simulator can see it again. Every `openLink`
step in `visual-review-smoke.yaml` and `correction-visual-review-seam.yaml` is
immediately followed by:

```yaml
- runFlow: common/accept-open-in-slacks.yaml
```

`common/accept-open-in-slacks.yaml` runs its whole body inside a
`when: platform: iOS` gate, so **Android skips it instantly** — the confirmation
is an iOS-only system dialog, and Android never enters the wait, so the retained
Android `mobile-e2e` suite's `openLink` launch path is unchanged and adds no
delay. On iOS the subflow waits (optionally) for the exact system alert title
and, only while it is visible, taps the alert's `Open` button. The title matcher
is `Open in .Slacks.*` — quote-agnostic (iOS renders the title with smart quotes,
`Open in “Slacks”?`) and full-match-safe (Maestro's `text:` is a full-match
regex), so it matches the real alert; the wait then resolves the moment the alert
appears and the `when:` gate taps it. It is also a no-op on an iOS simulator that
has already accepted the dialog: the wait warns and the gate is skipped, so
nothing is tapped and no app-owned control is ever hit. It does not swallow real
failures — the following
`extendedWaitUntil` on the preset's settled marker still fails when the preset
never actually loads. No universal-links / associated-domains entitlement is
added; the `slacks://` scheme stays a debug-only custom scheme.

Any new flow that opens a visual-review preset via `openLink` on iOS should add
the same `runFlow: common/accept-open-in-slacks.yaml` step right after — that is the
dialog-free launch recipe FTY-235..241 and other iOS evidence tooling should
reuse instead of a manual `tapOn: Open`.

### iOS marker-assertion scope for the correction native-sheet presets (FTY-272)

`correction.typeahead` and `correction.confirm_apply` open the correction sheet
at its large, dimmed native detent, where iOS's presentation does not expose
the sheet's in-modal content — including its `visual-review-settled:<preset>`
marker — to the accessibility tree at all (ratified in
[`../docs/verification/FTY-263/README.md`](../docs/verification/FTY-263/README.md);
see also [`../e2e/visualReview/README.md`](../e2e/visualReview/README.md#ios-marker-assertion-scope-fty-263--fty-272)).
Android's `NativeSheet` fallback (a real `Modal`) keeps that content reachable
at any detent, so the marker wait for those two presets in
`visual-review-smoke.yaml` and `correction-visual-review-seam.yaml` is scoped
to Android only (`when: platform: Android`); their iOS branch instead confirms
the sheet itself rendered before capturing the same evidence screenshot. Every
other preset in both flows — including `correction.detail`, whose medium,
undimmed detent keeps its marker reachable on iOS too — still asserts its
marker on both platforms, unchanged. This keeps the retained Android
`mobile-e2e` suite's marker coverage exactly as FTY-263 shipped it while
letting an iOS run of the same committed flows complete end to end.

## E2E launch mode (deterministic boot)

When the app is launched from the E2E binary it enters a gated launch mode:
- A **synthetic authenticated session** is seeded into the session store (no live
  auth dependency, no flake).
- An **in-process fetch mock** returns hermetic fixture responses for all API
  calls (no live backend, no network timing).
- **Onboarding is pre-completed** for the synthetic user so the wizard never
  appears — except under an active `onboarding.*` visual-review preset
  (FTY-266), which overrides the onboarding status so the wizard opens
  directly on that preset's step for the visual audit.

The gate is hard-closed in release builds: `__DEV__` is `false` at compile time
in a production bundle, making the E2E branch dead code that Metro eliminates.
The `EXPO_PUBLIC_SLACKS_E2E=true` env var is the second gate; it is set only by
`verify-e2e.sh` at build time, never by default. See `e2e/launchMode.ts`.

## Reduce Motion pass (FTY-181)

The signature motion beats degrade to a no-motion path under Reduce Motion (a
simple fade / value-set, no spring — see `theme/motion.ts`). Maestro cannot
toggle the OS `isReduceMotionEnabled` flag, so the reduce-motion E2E build sets a
second env var and the launch harness overrides that accessibility read — the
hermetic equivalent of the OS toggle:

```sh
cd mobile
E2E_REDUCE_MOTION=1 ./verify-e2e.sh
```

This forces Reduce Motion on for the whole run, so `reduce-motion.yaml` (and every
other flow) exercises the beats' no-motion branch end-to-end and proves they still
reach the same successful state — the resolved value row eases in with a fade (not
a spring) and counts in the hero. The default `./verify-e2e.sh` leaves the var
unset (`false`), so behaviour is unchanged and the beats run with full motion.

The animation *curve* itself (spring vs fade) is not exposed in the accessibility
tree, so the branch **selection** is asserted by the `theme/motion.ts` and
`CalorieHero` component tests; this pass guards that the no-motion path reaches the
same end state on a real device.

## Adding a new flow

1. Add a `<name>.yaml` file in this directory.
2. Use `testID` attributes (already on key UI elements) for stable assertions;
   avoid matching on copy strings that change.
3. Run it locally with `maestro test .maestro/<name>.yaml` before committing.
