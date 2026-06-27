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
| `fatty/` | The product repo (public `epurn/fatty`). Product code, contracts, standards. Its own repo. |
| `fatty-steward-agent/` | The single always-on poller. Routes ready stories, and launches one-shot author AND reviewer workers in parallel based on PR + queue state. |
| `fatty-reviewer-agent/` | One-shot worker. The steward dispatches it (`reviewer once --pr N`) to review a PR head read-only and post the reviewer-approved status. |
| `fatty-author-agent/` | One-shot worker. Implements/fixes one assigned story in a worktree, opens a PR. |
| `fatty-worktrees/` | Per-assignment git worktrees + steward run state. |
| `fatty-fatop/` | Read-only Go TUI/CLI that monitors the agents. Reads the structured event logs; never operates the services. |
| `docs/` | The agent operating system: roles, polling, model policy, event log. Also `docs/stories/` — the canonical story roadmap + specs the steward reads and embeds into author assignments (kept out of the public app repo). |
| `.claude/` | Skills and the planner subagent used to manage everything from here. |

## The Four Roles

Roles stay separate; one agent never does two of these for the same work. Full
detail in `docs/agent-operating-system.md`.

- **Planner** — creates, refines, and promotes stories. Never implements,
  reviews, or operates the services. Driven interactively from here with the
  `plan-stories` skill (it interviews you, then writes the story/stories) or the
  planner subagent directly.
- **Steward** — the single deterministic poller. Assigns ready stories to
  authors, routes PR fixes, and dispatches reviewers for PR heads needing a
  verdict — launching author and reviewer workers in parallel. Wakes a model
  only for bounded judgment, and auto-repairs a story that trips the circuit
  breaker (split/revise/escalate, repair-once) instead of parking it.
- **Author** — implements one scoped story on its own branch and opens a PR.
- **Reviewer** — a one-shot worker the steward dispatches; inspects the PR head
  (read-only) and approves, comments, or requests changes. Always a separate
  process from the author — the steward launches it but never reviews itself.

## Operating The Agents

You own start/stop/observe. The planner prepares work; it never runs services.

```sh
# Start the steward + reviewer pollers and tail logs (command-centre orchestration)
./scripts/agents-up.sh

# Stop all agent processes
./scripts/agents-down.sh

# Health-check any agent (tools, GitHub App token)
( cd fatty-author-agent && make doctor )

# One-shot debugging cycles
( cd fatty-steward-agent && make poll )
( cd fatty-reviewer-agent && make once PR=<n> )
```

Prefer the `agents-status` and `agents-control` skills for these — they wrap the
commands and summarize state.

## Observing The Agents (fatop)

`fatty-fatop/` is a read-only Go monitor. Build it once (`cd fatty-fatop && make
install`), then:

```sh
fatop                      # live TUI: services, runs in flight, PR state, streams
fatop status               # one-shot snapshot
fatop logs [agent] -f      # follow the merged (or one agent's) event stream
fatop inspect <id|PR-n>    # full timeline for a single run
```

`agents-up.sh` launches `fatop` automatically when it is built (pass `--raw` for
the old tail). fatop only reads the structured event logs defined in
`docs/agent-event-log.md`; it never starts, stops, or mutates anything.

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

## Keeping agent context current

The author/reviewer prompts preload facts about `fatty` (package layout, the exact
per-package verify commands) and the planner skill documents the lane vocabulary —
so runs skip rediscovery and save cost. The agents evolve `fatty`, so these can go
stale. Upkeep:

- **`scripts/check-preloads.py`** asserts the preloads still match `fatty` + the
  steward's `lane_for_path`. The steward runs it at startup and hourly and emits a
  `preload_drift` warn (visible in fatop) when they diverge. If you change `fatty`'s
  layout or a `verify.sh`, update the author/reviewer prompts and re-run the check.
- **`scripts/warm-deps.sh`** builds the dependency warm base the steward clones into
  each worktree. The steward auto-refreshes it when a lockfile changes on main; run
  it by hand to rebuild from scratch.
