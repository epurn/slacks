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
#   APP_BUNDLE_ID     Override the iOS bundle ID / Android package name
#                     (default: com.fatty)

set -euo pipefail

cd "$(dirname "$0")"

PLATFORM="${PLATFORM:-ios}"
BUNDLE_ID="${APP_BUNDLE_ID:-com.fatty}"

echo "==> [verify-e2e] Platform: $PLATFORM | Bundle ID: $BUNDLE_ID"

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

# ── 3. Build and install the debug binary ─────────────────────────────────────
if [ "$PLATFORM" = "android" ]; then
  echo "==> [verify-e2e] Building Android debug APK..."
  EXPO_PUBLIC_FATTY_E2E=true npx expo run:android --no-build-cache --configuration debug

elif [ "$PLATFORM" = "ios" ]; then
  echo "==> [verify-e2e] Building iOS simulator binary..."
  EXPO_PUBLIC_FATTY_E2E=true npx expo run:ios --no-build-cache --configuration Debug --simulator

else
  echo "ERROR: Unknown PLATFORM='$PLATFORM'. Use 'ios' or 'android'."
  exit 1
fi

# ── 4. Run Maestro flows ───────────────────────────────────────────────────────
echo "==> [verify-e2e] Running Maestro flows..."
APP_BUNDLE_ID="$BUNDLE_ID" maestro test .maestro/smoke.yaml
APP_BUNDLE_ID="$BUNDLE_ID" maestro test .maestro/clarify.yaml

echo "==> [verify-e2e] All E2E flows passed."
