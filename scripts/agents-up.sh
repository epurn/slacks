#!/usr/bin/env bash
# Command-centre orchestration: bring the Fatty agents up.
# Each agent owns its own launch-agent installer; this only coordinates them.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AUTHOR="$ROOT/fatty-author-agent"
REVIEWER="$ROOT/fatty-reviewer-agent"
STEWARD="$ROOT/fatty-steward-agent"

echo "== clearing any orphaned git locks from a previous run =="
bash "$ROOT/scripts/clean-git-locks.sh" || true

echo "== verifying agents =="
( cd "$AUTHOR"   && make doctor )
( cd "$REVIEWER" && make doctor )
( cd "$STEWARD"  && make doctor )

mkdir -p "$REVIEWER/logs" "$STEWARD/logs"
touch "$REVIEWER/logs/reviewer.out.log" "$REVIEWER/logs/reviewer.err.log" \
      "$STEWARD/logs/steward.out.log"   "$STEWARD/logs/steward.err.log"

echo "== installing launch agents (reviewer + steward) =="
( cd "$REVIEWER" && ./scripts/install-launch-agent.sh )   # reviewer runs with --enable-auto-merge
( cd "$STEWARD"  && ./scripts/install-launch-agent.sh )

echo "== active agent processes =="
pgrep -af 'reviewer_agent/runner.py|steward_agent/runner.py|author_agent/runner.py' 2>/dev/null || true

echo
echo "Agents are running as launchd services. The viewer below is just an"
echo "observer — closing it leaves the agents running. Stop them with:"
echo "scripts/agents-down.sh"
echo

# Prefer the fatop dashboard; fall back to a raw tail with --raw or if fatop
# is not built. fatop is read-only and never touches the running agents.
FATOP="$(command -v fatop || true)"
[ -z "$FATOP" ] && [ -x "$ROOT/fatty-fatop/fatop" ] && FATOP="$ROOT/fatty-fatop/fatop"

if [ "${1:-}" != "--raw" ] && [ -n "$FATOP" ]; then
  exec "$FATOP" watch --root "$ROOT"
fi

echo "(fatop not found or --raw given; tailing raw logs)"
exec tail -n 0 -F \
  "$REVIEWER/logs/reviewer.out.log" "$REVIEWER/logs/reviewer.err.log" \
  "$STEWARD/logs/steward.out.log"   "$STEWARD/logs/steward.err.log"
