#!/usr/bin/env bash
# Remove orphaned git lock files left behind by an ungraceful agent shutdown.
#
# The steward and authors run git against the fatty repo (worktree add/remove,
# fetch, branch ops, commit/push in worktrees). If one is killed mid-operation,
# its index/ref/HEAD .lock files are orphaned and block the next git command.
# This sweep clears them — but ONLY when no agent is running, so it can never
# race a live git operation.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FATTY="${FATTY_STEWARD_FATTY_REPO_PATH:-$ROOT/fatty}"

PATTERN='steward_agent/runner.py|reviewer_agent/runner.py|author_agent/runner.py'
if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  echo "clean-git-locks: agents are running; refusing to touch git locks" >&2
  exit 0
fi

if [ ! -d "$FATTY/.git" ]; then
  echo "clean-git-locks: no git dir at $FATTY/.git" >&2
  exit 0
fi

removed=0
sweep_dir() {  # $1 = a gitdir (main repo or a per-worktree dir)
  local d="$1"
  for f in index.lock HEAD.lock config.lock MERGE_HEAD.lock; do
    if [ -f "$d/$f" ]; then rm -f "$d/$f" && echo "  removed $d/$f" && removed=$((removed + 1)); fi
  done
  if [ -d "$d/refs" ]; then
    while IFS= read -r l; do
      rm -f "$l" && echo "  removed $l" && removed=$((removed + 1))
    done < <(find "$d/refs" -type f -name '*.lock' 2>/dev/null)
  fi
}

sweep_dir "$FATTY/.git"
if [ -d "$FATTY/.git/worktrees" ]; then
  for wt in "$FATTY/.git/worktrees"/*/; do
    [ -d "$wt" ] && sweep_dir "${wt%/}"
  done
fi

# Drop worktree admin entries whose directory is gone (also clears their locks).
git -C "$FATTY" worktree prune 2>/dev/null || true

echo "clean-git-locks: removed $removed lock file(s)"
