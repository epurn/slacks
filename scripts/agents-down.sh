#!/usr/bin/env bash
# Command-centre orchestration: bring the Fatty agents down gracefully.
#
# Order matters: unload the launch agents, send SIGTERM and give the runners a
# grace period to finish any in-flight git operation and run their cleanup,
# force-kill only stragglers, then sweep any orphaned git locks so the next
# start is clean.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

launchctl unload "$HOME/Library/LaunchAgents/com.epurn.fatty-reviewer-agent.plist" >/dev/null 2>&1 || true
launchctl unload "$HOME/Library/LaunchAgents/com.epurn.fatty-steward-agent.plist"  >/dev/null 2>&1 || true

PATTERN='steward_agent/runner.py|reviewer_agent/runner.py|author_agent/runner.py'

# Graceful stop: SIGTERM (the runners trap it, finish the current git op, and exit).
pkill -TERM -f "$PATTERN" >/dev/null 2>&1 || true

# Drain: wait up to ~20s for clean exit.
for _ in $(seq 1 20); do
  pgrep -f "$PATTERN" >/dev/null 2>&1 || break
  sleep 1
done

# Force only what refused to leave.
if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  echo "grace period elapsed; force-killing remaining agent processes"
  pkill -KILL -f "$PATTERN" >/dev/null 2>&1 || true
  sleep 1
fi

# An author that was SIGKILLed could orphan its claude child; clear those too.
pkill -KILL -f 'claude .*--output-format stream-json' >/dev/null 2>&1 || true

# Recover any git locks left by an ungraceful exit (no-op if none / if agents up).
bash "$ROOT/scripts/clean-git-locks.sh" || true

echo "stopped Fatty reviewer, steward, and author processes"
