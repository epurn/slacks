# fatop — Fatty agent monitor

A single Go binary that gives the command centre a live, pretty view of the
agent system and lets you drill into what any individual agent is doing.

It is **read-only** operator tooling: it never starts, stops, or mutates the
agents. Start/stop still lives in the `agents-control` skill. fatop only reads
local automation state, so nothing it touches belongs in the public `fatty` repo.

## Build

```sh
cd fatty-fatop
make build            # runs `go mod tidy` then `go build -o fatop .`
make install          # builds and copies fatop to ~/.local/bin
```

`go mod tidy` fetches the Charm TUI dependencies and writes `go.sum`. Requires Go
1.22+ and network access for the first build.

## Use

```sh
fatop                      # launch the live TUI dashboard
fatop status               # one-shot snapshot of services, runs, and PRs
fatop queue                # story queue in assignment order + open PRs
fatop usage                # token + cost accounting (--since today|all|<dur>)
fatop logs                 # merged, color-coded event stream (all agents)
fatop logs author -f       # follow only the author's events
fatop logs --level warn    # only warnings and errors
fatop inspect FTY-010      # full detail + event timeline for one run
fatop inspect PR-6
fatop doctor               # verify fatop can read every source
```

The dashboard is multi-view (k9s-style). The header always shows service health,
author count, and today's spend + burn rate.

- **1 Overview** — agents, runs, a queue summary, and open PRs in the left rail;
  the live event stream on the right.
- **2 Queue** — the full story queue in assignment order, each row marked
  assignable / blocked-on-which-deps / running / needs-attention, with breaker
  attempt counts. Press `enter` to inspect a story's full spec.
- **3 Usage** — token + cost accounting for today: totals, burn rate, cache-hit
  ratio, per-model rollup, and recent runs.
- **Story** — the selected story's full markdown spec (reached with `enter` from
  the queue; `esc` returns).

### TUI keys

```
1 / 2 / 3   switch view: Overview · Queue · Usage   (tab cycles)
↑/k ↓/j     move selection (overview rail / queue rows)
enter       (queue) inspect the selected story's spec
esc         (story) back to the queue
f           (overview) toggle stream follow
l           (overview) cycle minimum level: debug → info → warn → error
g / G       jump to top / bottom
pgup/pgdn   scroll
r           force a refresh now
?           help    ·    q  quit
```

## How it reads state

fatop consumes the structured JSONL event logs defined in
`docs/agent-event-log.md`, plus the steward run directory and `gh` for PR state:

| Source | Path |
| --- | --- |
| steward events | `fatty-steward-agent/logs/steward.events.jsonl` |
| reviewer events | `fatty-reviewer-agent/logs/reviewer.events.jsonl` |
| author events | `fatty-author-agent/logs/author.events.jsonl` |
| author Claude stream (per run) | `fatty-worktrees/.steward-run/<ID>.events.jsonl` |
| run state | `fatty-worktrees/.steward-run/<ID>.json` / `.active` |
| PR state | `gh pr list --repo <repo> ...` |

The command-centre root is resolved from `--root`, then `$FATTY_HOME`, then an
upward search for `fatty-worktrees/`, then the built-in default.

## Layout

```
main.go                 entrypoint
internal/config         path resolution
internal/state          run-state, services, PRs, event parsing (unit-tested)
internal/ui             shared lipgloss palette
internal/cli            status / logs / inspect / doctor subcommands
internal/tui            Bubble Tea dashboard
```
