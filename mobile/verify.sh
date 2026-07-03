#!/usr/bin/env bash
# Mobile verification hook run by root `make verify` via
# scripts/package-verify.sh. Installs the locked dependency set, then runs the
# TypeScript typecheck, ESLint, the accent-as-text a11y guard, and Jest tests,
# exiting non-zero on the first failure. See docs/architecture/repo-layout.md.
set -euo pipefail

cd "$(dirname "$0")"

# `npm ci` installs exactly what package-lock.json pins and fails if the
# lockfile is stale, keeping CI and local runs reproducible.
npm ci

npm run typecheck
npm run lint

# Accent-as-text a11y guard (FTY-191): fails on any `colors.accent` used as a
# text color beyond the tracked baseline (accent fails WCAG AA as text on the
# light surface — use colors.accentText). Background/border/fill uses are fine.
npm run check:accent-text

npm test
