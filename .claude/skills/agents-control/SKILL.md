---
name: agents-control
description: Start, stop, or reload the Fatty steward and reviewer poller services (and the launchd launch agents). Use when the user says "start the agents", "stop the agents", "restart", "bring the system up/down", or "reload after a config change".
---

# Agents Control

Operate the always-on poller services. The steward and reviewer run as launchd
agents; the author is one-shot and launched by the steward, so it has no service
to start. Confirm destructive actions (stop/restart) before running them.

## Preflight (before the first autonomous run)

For a fully autonomous, auto-merge experiment, confirm these once — they are the
usual silent failures:

- `claude` CLI installed, on the launchd PATH, and **authenticated** (subscription
  login or `ANTHROPIC_API_KEY` available to the service). `make doctor` checks the
  binary exists but NOT that it can talk to the API.
- `gh auth status` is logged in on this machine (the reviewer sets merge intent
  via your local `gh`).
- Repo-level auto-merge is ON: `gh api --method PATCH repos/epurn/fatty -f allow_auto_merge=true`.
- Branch protection applied (`governance` + `reviewer-approved` required) and both
  checks have each run at least once.
- All three agents' `.env` files have valid GitHub App credentials (`make doctor`
  passes for each — `run-all-agents` runs this).
- Stories you want built are `state: ready` and `autonomous: true`.
- Consider raising `FATTY_AUTHOR_CLAUDE_MAX_TURNS` for large stories so the author
  doesn't hit the turn cap mid-implementation and return BLOCKED.

## Start everything

Verifies each agent, installs/loads the steward + reviewer launch agents, and
tails logs:

```sh
( cd fatty-steward-agent && make run-all-agents )
```

## Stop everything

Unloads the launch agents and kills any running runner processes:

```sh
( cd fatty-steward-agent && make stop-all-agents )
```

## Reload (after editing .env or code)

```sh
( cd fatty-steward-agent && make stop-all-agents )
( cd fatty-steward-agent && make run-all-agents )
```

## Single service, foreground (debugging)

```sh
( cd fatty-steward-agent  && make watch )            # steward poll loop
( cd fatty-reviewer-agent && make watch-auto-merge ) # reviewer + auto-merge
```

## Notes

- Auth: the services need a logged-in `claude` CLI or `ANTHROPIC_API_KEY` in
  their environment.
- If `make doctor` fails inside `run-all-agents`, fix the missing tool/credential
  before the agents will start.
- After any change, run the `agents-status` skill to confirm the new state.
