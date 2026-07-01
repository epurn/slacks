# Maestro E2E Flow Tests (FTY-160)

This directory contains [Maestro](https://maestro.mobile.dev/) YAML flows for
Fatty's end-to-end test harness. Maestro drives the app via the accessibility
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
CI target (FTY-161).

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
1. Builds the E2E debug binary with `EXPO_PUBLIC_FATTY_E2E=true` (iOS simulator
   by default; set `PLATFORM=android` to build an APK).
2. Installs the binary on the active simulator/emulator.
3. Runs `maestro test .maestro/smoke.yaml`.

**Running the flow directly** (if you already have the binary installed):

```sh
cd mobile
maestro test .maestro/smoke.yaml
```

## Bundle ID

The smoke flow uses bundle ID `com.fatty` by default (Expo prebuild from slug
`"fatty"`). If your prebuild produced a different identifier, set the env var:

```sh
APP_BUNDLE_ID=com.yourorg.fatty maestro test .maestro/smoke.yaml
```

Or edit the `appId` line in `smoke.yaml` permanently.

## Flows

| File | What it tests |
|------|---------------|
| `smoke.yaml` | App launches in E2E mode → Today mounts **and** its timeline reaches the ready, non-error state — data-present, not data-starved (FTY-160) |

More flows will be added in subsequent stories:
- FTY-162: clarification-needs flow regression (the FTY-149 sheet driven to completion)

## E2E launch mode (deterministic boot)

When the app is launched from the E2E binary it enters a gated launch mode:
- A **synthetic authenticated session** is seeded into the session store (no live
  auth dependency, no flake).
- An **in-process fetch mock** returns hermetic fixture responses for all API
  calls (no live backend, no network timing).
- **Onboarding is pre-completed** for the synthetic user so the wizard never
  appears.

The gate is hard-closed in release builds: `__DEV__` is `false` at compile time
in a production bundle, making the E2E branch dead code that Metro eliminates.
The `EXPO_PUBLIC_FATTY_E2E=true` env var is the second gate; it is set only by
`verify-e2e.sh` at build time, never by default. See `e2e/launchMode.ts`.

## Adding a new flow

1. Add a `<name>.yaml` file in this directory.
2. Use `testID` attributes (already on key UI elements) for stable assertions;
   avoid matching on copy strings that change.
3. Run it locally with `maestro test .maestro/<name>.yaml` before committing.
