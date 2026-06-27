# fatop (Fatty agent monitor)

Read-only observability tooling for the command centre. A single Go binary that
renders agent state — services, runs in flight, PRs — as a live TUI, and exposes
scriptable `status` / `logs` / `inspect` / `doctor` subcommands.

## Rules

- **Read-only, with one scoped control surface.** Everything except
  `internal/control` is read-only — fatop never starts, stops, or mutates agents
  or PRs (that stays in the `agents-control` skill). The single exception is the
  Config view: `internal/control` edits the steward `.env` and sends it SIGHUP so
  the operator can tune live config (parallelism, poll interval) without a
  restart. The steward re-reads those tunables from `os.environ` each poll, so a
  hot-reload applies on the next cycle. No other mutation is allowed here.
- **Private boundary.** fatop only touches local automation state (and now the
  steward `.env`). Nothing here — source, telemetry, machine paths, or config —
  belongs in the public `fatty` repo. Control never touches the public repo.
- **Telemetry is additive.** fatop consumes the JSONL event logs described in
  `../docs/agent-event-log.md`. It must tolerate missing files and malformed
  lines without crashing.

## Structure

- `internal/state` is the only place that *reads* the filesystem / `gh`; keep it
  pure and unit-tested (`make test`). `internal/control` is the only place that
  *writes* (the steward `.env` + SIGHUP) — keep all mutation there, unit-tested,
  never in state/cli/tui. The CLI and TUI render state and call control.
- `internal/cli` and `internal/tui` share the palette in `internal/ui`.
- Add a new event type? Update `../docs/agent-event-log.md` first, then the
  producing agent, then any rendering here.

## Build & test

```sh
make build    # go mod tidy + go build
make test     # go test ./...
make vet
```
