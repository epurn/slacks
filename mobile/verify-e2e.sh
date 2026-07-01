#!/usr/bin/env bash
# Local E2E runner for the Fatty mobile app (FTY-160).
#
# Builds the E2E debug binary (with EXPO_PUBLIC_FATTY_E2E=true baked in),
# installs it on an active simulator/emulator, and runs the Maestro flow suite.
#
# This is SEPARATE from `make verify` (npm typecheck + lint + jest) — E2E is
# its own command so the unit loop stays fast and a machine without a device
# degrades cleanly.
#
# Usage:
#   cd mobile
#   ./verify-e2e.sh           # iOS simulator (default)
#   PLATFORM=android ./verify-e2e.sh  # Android emulator
#
# Prerequisites:
#   - Expo CLI: npm install -g expo-cli  (or use npx expo)
#   - iOS: Xcode + simulator running
#   - Android: Android SDK + emulator running (adb devices shows a device)
#   - Maestro: curl -Ls "https://get.maestro.mobile.dev" | bash
#
# Environment variables:
#   PLATFORM          ios (default) or android
#   E2E_METRO_LOG     Metro log path (default: ${TMPDIR:-/tmp}/fatty-e2e-metro.log)
#   E2E_BUILD_CACHE   Unset (default) → build with --no-build-cache for a clean,
#                     deterministic local binary. Set to any value (CI sets it)
#                     to reuse the restored Gradle/Xcode build cache and keep the
#                     build bounded.

set -euo pipefail

cd "$(dirname "$0")"

PLATFORM="${PLATFORM:-ios}"
METRO_PORT="8081"
METRO_LOG="${E2E_METRO_LOG:-${TMPDIR:-/tmp}/fatty-e2e-metro.log}"
METRO_PID=""

# A clean build (no cache) is the local default for a deterministic binary. CI
# sets E2E_BUILD_CACHE to reuse the cached Gradle state so the emulator build
# stays bounded across runs.
BUILD_CACHE_FLAG="--no-build-cache"
BUILD_CACHE_LABEL="off"
if [ -n "${E2E_BUILD_CACHE:-}" ]; then
  BUILD_CACHE_FLAG=""
  BUILD_CACHE_LABEL="on"
fi

echo "==> [verify-e2e] Platform: $PLATFORM | Build cache: $BUILD_CACHE_LABEL | Metro port: $METRO_PORT"

cleanup_metro() {
  if [ -n "$METRO_PID" ] && kill -0 "$METRO_PID" 2> /dev/null; then
    echo "==> [verify-e2e] Stopping Expo dev server..."
    kill "$METRO_PID" 2> /dev/null || true
    wait "$METRO_PID" 2> /dev/null || true
  fi
}

dump_metro_log() {
  if [ -f "$METRO_LOG" ]; then
    echo "---- Expo dev server log (tail) ----"
    tail -120 "$METRO_LOG" || true
    echo "------------------------------------"
  fi
}

start_metro() {
  echo "==> [verify-e2e] Starting Expo dev server..."
  : > "$METRO_LOG"
  # Headless mode keeps Expo from launching the optional React Native DevTools
  # shell; the Linux CI sandbox blocks that Chromium binary before Metro is
  # ready.
  EXPO_PUBLIC_FATTY_E2E=true EXPO_UNSTABLE_HEADLESS=1 npx expo start --dev-client --host localhost --port "$METRO_PORT" > "$METRO_LOG" 2>&1 &
  METRO_PID="$!"

  for _ in $(seq 1 60); do
    if ! kill -0 "$METRO_PID" 2> /dev/null; then
      echo "ERROR: Expo dev server exited before becoming ready."
      dump_metro_log
      exit 1
    fi

    if curl --fail --silent --max-time 2 "http://127.0.0.1:$METRO_PORT/status" | grep -q "packager-status:running" ||
      grep -q "Waiting on .*:$METRO_PORT" "$METRO_LOG"; then
      echo "==> [verify-e2e] Expo dev server is ready."
      return
    fi

    sleep 1
  done

  echo "ERROR: Expo dev server did not become ready on port $METRO_PORT."
  dump_metro_log
  exit 1
}

trap cleanup_metro EXIT

# ── 1. Ensure Maestro is installed ────────────────────────────────────────────
if ! command -v maestro &> /dev/null; then
  echo "ERROR: maestro CLI not found."
  echo "Install it with: curl -Ls \"https://get.maestro.mobile.dev\" | bash"
  exit 1
fi

# ── 2. Prebuild the native project ────────────────────────────────────────────
# expo prebuild generates the ios/ and android/ native project dirs from the
# managed config. Run with --clean to regenerate from scratch.
echo "==> [verify-e2e] Running expo prebuild..."
EXPO_PUBLIC_FATTY_E2E=true npx expo prebuild --no-install --clean

# ── 3. Start Metro explicitly ─────────────────────────────────────────────────
# expo run:* starts Metro in the foreground by default, which prevents this
# script from reaching Maestro in CI. Keep Metro in the background and build /
# install with --no-bundler so the next command is the actual flow run.
start_metro

# ── 4. Build and install the debug binary ─────────────────────────────────────
if [ "$PLATFORM" = "android" ]; then
  echo "==> [verify-e2e] Building Android debug APK..."
  EXPO_PUBLIC_FATTY_E2E=true npx expo run:android $BUILD_CACHE_FLAG --variant debug --no-bundler

elif [ "$PLATFORM" = "ios" ]; then
  echo "==> [verify-e2e] Building iOS simulator binary..."
  EXPO_PUBLIC_FATTY_E2E=true npx expo run:ios $BUILD_CACHE_FLAG --configuration Debug --simulator --no-bundler

else
  echo "ERROR: Unknown PLATFORM='$PLATFORM'. Use 'ios' or 'android'."
  exit 1
fi

# ── 5. Run Maestro flows ───────────────────────────────────────────────────────
# Run the whole .maestro/ directory so every flow is exercised — the smoke flow
# now, and any flow added later (e.g. FTY-162's clarify regression) with no
# runner or CI change.
echo "==> [verify-e2e] Running Maestro flows (.maestro/)..."
maestro test .maestro/

echo "==> [verify-e2e] All E2E flows passed."
