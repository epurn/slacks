---
name: agents-control
description: Start, stop, or reload the Fatty steward and reviewer poller services (and the launchd launch agents). Use when the user says "start the agents", "stop the agents", "restart", "bring the system up/down", or "reload after a config change".
---

# Agents Control

Operate the always-on poller services. The steward and reviewer run as launchd
agents; the author is one-shot and launched by the steward, so it has no service
to start. Confirm destructive actions (stop/restart) before running them.

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
