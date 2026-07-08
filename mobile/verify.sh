#!/usr/bin/env bash
# Mobile verification hook run by root `make verify` via
# scripts/package-verify.sh. Installs the locked dependency set, then runs the
# TypeScript typecheck, ESLint (with the sonarjs code-smell rules), the
# accent-as-text a11y guard, the fontSize type-scale guard, the knip dead-code +
# dependency gate, and Jest tests, exiting non-zero on the first failure. See
# docs/architecture/repo-layout.md.
set -euo pipefail

cd "$(dirname "$0")"

# `npm ci` installs exactly what package-lock.json pins and fails if the
# lockfile is stale, keeping CI and local runs reproducible. See
# docs/architecture/repo-layout.md for the explicit pre-provisioned-deps skip.
if [[ "${FATTY_VERIFY_SKIP_INSTALL:-}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  echo "Skipping dependency install because FATTY_VERIFY_SKIP_INSTALL is set."
else
  npm ci
fi

npm run typecheck
npm run lint

# Accent-as-text a11y guard (FTY-191): fails on any `colors.accent` used as a
# text color beyond the tracked baseline (accent fails WCAG AA as text on the
# light surface — use colors.accentText). Background/border/fill uses are fine.
npm run check:accent-text

# fontSize type-scale guard (FTY-192): fails on any numeric `fontSize: N`
# literal beyond the tracked baseline — reference a theme/typography.ts
# typeScale token instead.
npm run check:font-size

# Dead-code + dependency hygiene gate (FTY-232): knip fails on unused files,
# unused exports/types, and unlisted/unused dependencies. Runs after lint so the
# static gates share the fast unit loop; see knip.jsonc for entry-point config.
npm run check:dead-code

npm test
