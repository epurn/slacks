# Agent Polling

Fatty automation optimizes for low token use and clear role separation.

## Principle

Do not keep Claude Code sessions alive to watch for work. Keep cheap
deterministic poller code running on an interval. Wake Claude Code only when that
code finds actionable work.

The poll cycle itself is not an LLM call. It is ordinary code that reads local
state and GitHub state, then sleeps or exits on `no_action`. A separate one-shot
Claude Code process (`claude -p`) is launched only after the poller has
identified a concrete author, review, fix, or judgment task.

## Poller Responsibilities

- Inspect GitHub PR state, checks, reviews, changed files, and labels.
- Inspect story roadmap state and active author markers.
- Treat open PR changed-file lanes and active author lanes as occupied.
- Treat local story branches with unmerged commits as occupied until their PR is
  merged or otherwise handled.
- Treat story dependencies as blocking until prerequisite stories are merged or
  otherwise marked complete.
- Return quickly with `no_action` when nothing is actionable.
- Fill available author/reviewer capacity with non-overlapping work when lanes
  and dependencies are unblocked.
- Start bounded author, review, fix, or steward-judgment tasks only after a poll
  cycle finds actionable work.
- Pass only the minimal story, PR, diff, and checklist context needed.
- Strip GitHub App tokens, private-key paths, and secret environment variables
  before invoking Claude Code.
- Exit the Claude Code task after the one assignment completes.

## Scheduling

Schedule poller code, not Claude Code. Scheduling and service-runner
configuration live in each agent's `launchd/` + `scripts/`. The model wakes only
after deterministic checks conclude work is needed.
