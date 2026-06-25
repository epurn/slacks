#!/usr/bin/env bash
# Verify the host `gh` CLI is ready for the Fatty agents.
# - bot API calls go through `gh api` with the App token (needs gh INSTALLED)
# - the reviewer's auto-merge uses `gh pr merge --auto` as YOUR identity (needs gh AUTH'd)
set -uo pipefail
REPO="${FATTY_REPO:-epurn/fatty}"
fail=0

if ! command -v gh >/dev/null 2>&1; then
  echo "MISSING: gh not installed -> brew install gh"
  exit 1
fi
echo "ok: gh installed ($(gh --version | head -1))"

if gh auth status >/dev/null 2>&1; then
  echo "ok: gh authenticated as your identity"
else
  echo "MISSING: gh not authenticated -> gh auth login   (GitHub.com, HTTPS, scope: repo)"
  fail=1
fi

if gh repo view "$REPO" >/dev/null 2>&1; then
  echo "ok: can access $REPO"
else
  echo "MISSING: cannot reach $REPO with current auth"
  fail=1
fi

am=$(gh api "repos/$REPO" --jq '.allow_auto_merge' 2>/dev/null || echo "unknown")
echo "info: repo allow_auto_merge = $am   (must be true for the auto-merge experiment)"

if [ "$fail" -eq 0 ]; then
  echo "gh is ready for the agents"
else
  echo "gh setup incomplete — fix the MISSING lines above"
  exit 1
fi
