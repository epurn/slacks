#!/usr/bin/env bash
# Backend verification hook run by root `make verify` via
# scripts/package-verify.sh. Runs lint, format check, typecheck, and tests
# against a locked uv environment, and exits non-zero on the first failure.
set -euo pipefail

cd "$(dirname "$0")"

# Install exactly what uv.lock pins; --frozen fails if the lockfile is stale.
uv sync --frozen --dev

uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
