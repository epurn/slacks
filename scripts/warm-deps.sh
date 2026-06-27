#!/usr/bin/env bash
# Establish/refresh the "warm base": install the gitignored dependency trees in
# the canonical fatty checkout so the steward can seed them into each new author
# worktree (instant CoW clone on APFS) instead of every run installing from
# scratch on its own turn budget.
#
# Idempotent. Re-run after a dependency lockfile changes. Touches only gitignored
# dep dirs (node_modules, .venv) in the local checkout — nothing is committed.
set -euo pipefail
FATTY="${FATTY_STEWARD_FATTY_REPO_PATH:-/Users/epurn/workspace/fatty-suite/fatty}"

echo "== warming mobile deps (npm ci) =="
if [ -f "$FATTY/mobile/package-lock.json" ]; then
  ( cd "$FATTY/mobile" && npm ci )
fi

echo "== warming backend deps (uv sync) =="
if [ -f "$FATTY/backend/pyproject.toml" ]; then
  ( cd "$FATTY/backend" && uv sync )
fi

echo "== warm base ready =="
du -sh "$FATTY/mobile/node_modules" "$FATTY/backend/.venv" 2>/dev/null || true

# Record the lockfile fingerprint so the steward only re-warms when a lockfile
# actually changes (see refresh_warm_base_if_stale in the steward runner).
STATE="${FATTY_STEWARD_RUN_DIR:-/Users/epurn/workspace/fatty-suite/fatty-worktrees/.steward-run}"
mkdir -p "$STATE"
cat "$FATTY/mobile/package-lock.json" "$FATTY/backend/uv.lock" 2>/dev/null \
  | shasum -a 256 | awk '{print $1}' > "$STATE/.warm-base-hash" || true
