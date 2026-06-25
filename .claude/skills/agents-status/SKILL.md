---
name: agents-status
description: Show the current state of the Fatty agent system — which services are running, launchd status, open PRs and their review/check state, active worktrees, and recent steward run logs. Use when the user asks "what's running", "agent status", "what are the agents doing", or wants a health snapshot.
---

# Agents Status

Produce a concise snapshot of the Fatty agent system. Run these read-only checks
(paths assume the command-centre root `/Users/epurn/workspace/fatty-suite`), then
summarize — do not dump raw output.

## Processes and services

```sh
pgrep -af 'reviewer_agent/runner.py|steward_agent/runner.py|author_agent/runner.py' || echo "no agent processes"
launchctl list | grep -i 'com.epurn.fatty' || echo "no launch agents loaded"
```

## GitHub PR state

```sh
gh pr list --repo epurn/fatty --state open \
  --json number,title,headRefName,isDraft,reviewDecision,statusCheckRollup
```

For each open PR, report: number, title, draft?, review decision, and whether
`governance` / `reviewer-approved` checks pass.

## Work in flight

```sh
ls -1 fatty-worktrees | grep -v '^\.'                 # active worktrees
cat fatty-worktrees/.steward-run/*.json 2>/dev/null   # last routing decisions
tail -n 20 fatty-worktrees/.steward-run/agent-monitor.log 2>/dev/null
```

## Health (optional, if something looks off)

```sh
( cd fatty-steward-agent && make doctor )
( cd fatty-reviewer-agent && make doctor )
```

## Output

A short summary: services up/down, open PRs and what each is waiting on, active
author lanes, and anything that looks stuck (failed checks, requested changes,
stale worktrees). Flag concrete next actions but do not take them unless asked.
