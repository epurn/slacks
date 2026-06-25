# Fatty Command Centre

This folder is the control surface for the Fatty autonomous development system.
From here you manage the agents, plan work, and observe state. The agents run on
**Claude Code** (`claude -p`) under local services.

This repo tracks only command-centre files (this `CLAUDE.md`, `.claude/`,
`docs/`). The nested repos below are independent git repos and are gitignored
here — work inside them on their own.

## What Lives Here

| Path | What it is |
| --- | --- |
| `fatty/` | The product repo (public `epurn/fatty`). Product code, contracts, stories, standards. Its own repo. |
| `fatty-steward-agent/` | Always-on poller. Routes ready stories, assigns authors, watches PR state. |
| `fatty-reviewer-agent/` | Always-on poller. Reviews PR heads read-only, posts the reviewer-approved status. |
| `fatty-author-agent/` | One-shot worker. Implements/fixes one assigned story in a worktree, opens a PR. |
| `fatty-worktrees/` | Per-assignment git worktrees + steward run state. |
| `docs/` | The agent operating system: roles, polling, model policy. |
| `.claude/` | Skills and the planner subagent used to manage everything from here. |

## The Four Roles

Roles stay separate; one agent never does two of these for the same work. Full
detail in `docs/agent-operating-system.md`.

- **Planner** — creates, refines, and promotes stories. Never implements,
  reviews, or operates the services. Driven interactively from here: start with
  the `grill-me` skill (it interviews you, then writes the story), or use the
  `plan-story` skill / planner subagent directly.
- **Steward** — deterministic poller; assigns ready stories to authors and
  routes PR fixes. Wakes a model only for bounded judgment.
- **Author** — implements one scoped story on its own branch and opens a PR.
- **Reviewer** — inspects the PR head (read-only) and approves, comments, or
  requests changes. Always separate from the author.

## Operating The Agents

You own start/stop/observe. The planner prepares work; it never runs services.

```sh
# Start the steward + reviewer pollers and tail logs
( cd fatty-steward-agent && make run-all-agents )

# Stop all agent processes
( cd fatty-steward-agent && make stop-all-agents )

# Health-check any agent (tools, GitHub App token)
( cd fatty-author-agent && make doctor )

# One-shot debugging cycles
( cd fatty-steward-agent && make poll )
( cd fatty-reviewer-agent && make once PR=<n> )
```

Prefer the `agents-status` and `agents-control` skills for these — they wrap the
commands and summarize state.

## Model Policy (Claude Code)

Model choice scales with task risk as a launch-time cost control: low →
`haiku`, medium → `sonnet`, high → `opus`. Thinking depth is **not** forced —
Claude scales its own reasoning. See `docs/agent-model-policy.md`. Per-agent
overrides live in each agent's `config.example.env` (`FATTY_*_CLAUDE_MODEL_*`).

## Public Repository Boundary

`fatty/` is public. Never let private automation cross into it: no runner code,
no agent memory, machine paths, tokens, private keys, provider secrets, or queue
state. The author and reviewer enforce this at runtime; keep it true here too.

## Conventions

- Each agent repo carries its own `CLAUDE.md` with that agent's rules.
- Secrets stay in each agent's local `.env` (gitignored). Keys live in
  `~/.config/fatty-agents/keys/`.
- Auth for Claude Code: a logged-in `claude` CLI or `ANTHROPIC_API_KEY` in the
  service environment.
