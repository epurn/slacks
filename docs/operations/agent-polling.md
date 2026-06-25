# Agent Polling

Fatty automation should optimize for low token use and clear role separation.

## Principle

Do not keep Codex sessions alive to watch for work. Keep cheap deterministic
poller code running on an interval. Wake Codex only when that code finds
actionable work.

The poll cycle itself is not an LLM call. It is ordinary code that reads local
state and GitHub state, then sleeps or exits on `no_action`. A separate
one-shot Codex process may be launched only after the poller has identified a
concrete author, review, fix, or judgment task.

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
- Start bounded author, review, fix, or steward-judgment tasks only after a
  poll cycle finds actionable work.
- Pass only the minimal story, PR, diff, and checklist context needed.
- Strip GitHub App tokens, private-key paths, and secret environment variables
  before invoking Codex.
- Exit the Codex task after the one assignment completes.

## Local Commands

From the Fatty app repo:

These commands are for the user to run. The planner may document or explain
them, but must not run, reload, poll, or stop local steward/reviewer/author
services unless the user explicitly asks for that exact operational action.

```sh
make steward
make reviewer
make agents-run
make agents-stop
make steward-poll
make steward-poll-dry-run
make reviewer-poll
make reviewer-poll-auto-merge
```

`make reviewer` and `make agents-run` run the reviewer with native GitHub
auto-merge intent after the reviewer approves the current PR head. GitHub
branch protection still owns the final merge gate.

These delegate to sibling local agent repos through configurable paths:

```sh
FATTY_STEWARD_AGENT_ROOT=../fatty-steward-agent
FATTY_REVIEWER_AGENT_ROOT=../fatty-reviewer-agent
```

The public app repo documents the integration point. Private launchd state,
thread IDs, local paths, credentials, and runner logs stay outside this repo.

## Scheduling

Schedule the poller code, not Codex. A launchd, cron, or GitHub webhook wrapper
should keep the steward/reviewer code polling. The model should wake only after
deterministic checks conclude work is needed.
