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

## Operational Boundary

The public app repo documents poller expectations, handoff rules, and review
gates. It must not publish local runner commands, private package paths,
machine-specific defaults, credentials, queue state, thread IDs, durable agent
memory, or runner logs.

Planner documentation may describe what each role is allowed to do. It must not
instruct planners to start, reload, poll, stop, or otherwise operate steward,
reviewer, or author services.

## Scheduling

Schedule poller code, not Codex. The scheduling mechanism and service runner
configuration belong outside this public repository. The model should wake only
after deterministic checks conclude work is needed.
