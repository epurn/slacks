# Agent Operating System

How the Fatty autonomous development system is organized. This is private
command-centre documentation; it must not live in the public `fatty` repo.

## Roles

Agent work is split into durable roles. Keep the roles separate unless you
explicitly change the operating model. A single agent must never do two of these
for the same piece of work — in particular, one agent must not author and
approve the same implementation.

- **Planner** — creates, refines, and promotes stories. Does not implement or
  review the work it plans. Does **not** start, reload, poll, stop, or otherwise
  operate the steward, reviewer, or author services; it prepares docs, stories,
  and commands, and you run the agents. Driven interactively from the command
  centre (`plan-story` skill / planner subagent).
- **Steward** — picks up ready stories, assigns author work, watches PR state,
  and routes PRs to reviewers. Deterministic poller; wakes a model only for
  bounded judgment (story splitting, promotion, demotion, blocker triage).
- **Author** — implements one scoped story on its own branch and opens a PR.
  One bounded assignment per run, then exits.
- **Reviewer** — inspects the current PR head using the review checklist and
  approves, comments, or requests changes. Always separate from the author.

## Public Repository Boundary

`fatty` is a public product repo: product code, public architecture docs,
standards, contracts, and review policy. Everything about *how the
automation runs* stays here in the command centre instead:

- the story roadmap + specs (`docs/stories/`) — the steward embeds each spec into
  the author's assignment, so they never ship in the public app repo,
- runner code and local automation configuration,
- durable agent memory, thread IDs, and queue state,
- machine-specific paths, tokens, private keys, provider secrets,
- runner logs.

The author and reviewer enforce this at runtime (they refuse to commit private
automation paths into `fatty`). Keep it true in everything you do here too.

## Coordination Flow

1. The planner promotes stories that meet the readiness rule.
2. The steward picks up ready stories and assigns implementation work when
   dependencies are complete and lanes are unoccupied.
3. The author works on a branch from current `origin/main` and opens a PR with
   verification, security, privacy, and story context.
4. The steward routes the PR to a separate reviewer.
5. New commits after a review require a fresh current-head review before merge.

Lanes (changed-file areas) and active author assignments are treated as occupied
until merged, closed, or complete, so overlapping work never runs in parallel.

## See Also

- `agent-polling.md` — why the loops are deterministic pollers, not live LLM
  sessions, and what the poller is responsible for.
- `agent-model-policy.md` — how model choice scales with task risk.
