#!/usr/bin/env bash
# Backend verification hook run by root `make verify` via
# scripts/package-verify.sh. Runs lint, format check, typecheck, and tests
# against a locked uv environment, and exits non-zero on the first failure.
set -euo pipefail

cd "$(dirname "$0")"

# Install exactly what uv.lock pins; --frozen fails if the lockfile is stale.
# See docs/architecture/repo-layout.md for the explicit pre-provisioned-deps
# skip.
if [[ "${FATTY_VERIFY_SKIP_INSTALL:-}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  echo "Skipping dependency install because FATTY_VERIFY_SKIP_INSTALL is set."
else
  uv sync --frozen --dev
fi

uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
