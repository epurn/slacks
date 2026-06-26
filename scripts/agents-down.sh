#!/usr/bin/env bash
# Command-centre orchestration: bring the Fatty agents down gracefully.
#
# Order matters: tear down the launch agents FIRST (so KeepAlive cannot respawn
# the steward/reviewer the instant we kill them), then SIGTERM the runners with
# a grace period, force-kill stragglers, take out any detached author process
# GROUPS (which carry an orphanable `claude` child), and finally sweep git locks
# so the next start is clean.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UID_NUM="$(id -u)"

PATTERN='steward_agent/runner.py|reviewer_agent/runner.py|author_agent/runner.py'

# All process-group ids for currently-running authors. The steward launches each
# author via `sh -c` under start_new_session, so the sh wrapper, the python
# author, and its `claude` child all share one process group — killing the group
# cleans up the claude child regardless of how it was invoked.
author_pgids() {
  pgrep -f 'author_agent/runner.py' 2>/dev/null \
    | xargs -I{} ps -o pgid= -p {} 2>/dev/null | tr -d ' ' | sort -u
}

# --- 1. Remove the launchd jobs synchronously so KeepAlive can't respawn. ---
# `launchctl unload` is deprecated/unreliable on recent macOS; `bootout` is the
# synchronous teardown. Fall back to unload for older systems.
for label in com.epurn.fatty-reviewer-agent com.epurn.fatty-steward-agent; do
  plist="$HOME/Library/LaunchAgents/$label.plist"
  launchctl bootout "gui/$UID_NUM/$label" >/dev/null 2>&1 \
    || launchctl unload "$plist" >/dev/null 2>&1 || true
done
# Confirm the jobs are gone before killing anything — otherwise KeepAlive
# respawns the steward and `down` appears to do nothing.
for _ in $(seq 1 10); do
  launchctl list 2>/dev/null | grep -q 'com.epurn.fatty' || break
  sleep 1
done
if launchctl list 2>/dev/null | grep -q 'com.epurn.fatty'; then
  echo "warning: a com.epurn.fatty launch job is still registered; KeepAlive may respawn it" >&2
fi

# --- 2. SIGTERM author groups + the runners; let them finish in-flight git. ---
for pgid in $(author_pgids); do
  [ -n "$pgid" ] && kill -TERM "-$pgid" 2>/dev/null || true
done
pkill -TERM -f "$PATTERN" >/dev/null 2>&1 || true

# Drain: wait up to ~20s for clean exit.
for _ in $(seq 1 20); do
  pgrep -f "$PATTERN" >/dev/null 2>&1 || break
  sleep 1
done

# --- 3. Force only what refused to leave (groups first, then processes). ---
for pgid in $(author_pgids); do
  [ -n "$pgid" ] && kill -KILL "-$pgid" 2>/dev/null || true
done
if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  echo "grace period elapsed; force-killing remaining agent processes"
  pkill -KILL -f "$PATTERN" >/dev/null 2>&1 || true
  sleep 1
fi

# --- 4. Sweep any author `claude` child reparented out of its group. ---
# The author always runs claude with `--add-dir <worktree>` under the worktree
# root, which uniquely identifies a fatty author child (any model/format).
WT_ROOT="${FATTY_AUTHOR_WORKTREE_ROOT:-$ROOT/fatty-worktrees}"
pkill -KILL -f "claude .*--add-dir ${WT_ROOT}" >/dev/null 2>&1 || true
pkill -KILL -f 'claude .*--output-format stream-json' >/dev/null 2>&1 || true

# --- 5. Recover any git locks left by an ungraceful exit (no-op if none). ---
bash "$ROOT/scripts/clean-git-locks.sh" || true

# --- 6. Report precisely what, if anything, survived. ---
if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  echo "WARNING: agent processes still running after down:" >&2
  pgrep -af "$PATTERN" >&2
  exit 1
fi
echo "stopped Fatty reviewer, steward, and author processes (and their claude children)"
