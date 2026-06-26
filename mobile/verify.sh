#!/usr/bin/env bash
# Mobile verification hook run by root `make verify` via
# scripts/package-verify.sh. Installs the locked dependency set, then runs the
# TypeScript typecheck, ESLint, and Jest tests, exiting non-zero on the first
# failure. See docs/architecture/repo-layout.md.
set -euo pipefail

cd "$(dirname "$0")"

# `npm ci` installs exactly what package-lock.json pins and fails if the
# lockfile is stale, keeping CI and local runs reproducible.
npm ci

npm run typecheck
npm run lint
npm test
