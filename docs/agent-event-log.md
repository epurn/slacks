# Agent Event Log

Structured telemetry contract for the Fatty agent system. Every agent emits
machine-readable events as **JSON Lines** (one JSON object per line) so the
`fatop` monitor can render a uniform, live view without scraping prose. This is
private command-centre telemetry — it must never live in or be committed to the
public `fatty` repo.

The human-readable text logs (`logs/*.out.log`, `.steward-run/<ID>.log`) are
kept as-is. The event log is **additive**.

## Envelope

Each line is one object with this exact shape:

```json
{
  "ts": "2026-06-25T18:03:11.482Z",
  "agent": "steward",
  "run_id": "FTY-010",
  "level": "info",
  "event": "assign_story",
  "msg": "FTY-010 ready; lane contracts available",
  "fields": { "lane": "contracts", "story_id": "FTY-010" }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `ts` | string | UTC ISO-8601, millisecond precision, `Z` suffix. |
| `agent` | string | `steward` \| `reviewer` \| `author`. |
| `run_id` | string | Story id (`FTY-010`), `PR-<n>`, or `service` for the always-on loops. |
| `level` | string | `debug` \| `info` \| `warn` \| `error`. |
| `event` | string | Stable lower_snake_case enum (see below). |
| `msg` | string | Short human summary; safe to show raw. |
| `fields` | object | Event-specific structured payload. May be empty `{}`. |

Consumers MUST ignore unknown `event` values and unknown `fields` keys, and MUST
tolerate malformed lines (skip them). Producers SHOULD keep `fields` keys stable.

## File locations

| Agent | Event file |
| --- | --- |
| steward | `fatty-steward-agent/logs/steward.events.jsonl` |
| reviewer | `fatty-reviewer-agent/logs/reviewer.events.jsonl` |
| author (service-level) | `fatty-author-agent/logs/author.events.jsonl` |
| author (per run, Claude stream) | `fatty-worktrees/.steward-run/<ID>.events.jsonl` |

The per-run author stream is the wrapped `claude --output-format stream-json`
output for one assignment, so `fatop inspect <ID>` can replay turns and tool
calls. The service-level files are append-only across the process lifetime.

## Event catalogue (initial)

### steward
- `poll_cycle` — a poll tick ran. `fields`: `event_kind`, `occupied_lanes`.
- `decision` — a routing decision. `fields`: `action`, `lane`, `story_id`, `reason`.
- `author_launch` — author process spawned. `fields`: `story_id`, `mode`, `lanes`.
- `pr_blocked` — open PR needs author attention. `fields`: `pr`, `reasons`.
- `steward_judgment` — model woken for bounded judgment. `fields`: `reason`.

### reviewer
- `watch_start` — watch loop began. `fields`: `repo`, `interval`, `auto_merge`.
- `review_start` — reviewing a PR head. `fields`: `pr`, `model`, `files`.
- `review_posted` — review submitted. `fields`: `pr`, `decision`.
- `status_set` — commit status set. `fields`: `pr`, `context`, `state`.
- `auto_merge_enabled` — native auto-merge turned on. `fields`: `pr`.
- `review_skip` — head already reviewed / draft. `fields`: `pr`, `reason`.

### author
- `run_start` — assignment picked up. `fields`: `story_id`, `mode`, `model`.
- `claude_event` — wrapped Claude stream event. `fields.kind` is normalized to
  `assistant` (model text), `tool_use` (a turn that only calls tools),
  `tool_result` (the user-role result, summarized as `↳ result`/`↳ error`),
  `result` (final), or passthrough (`system`, `rate_limit_event`, ...).
  Control-plane chatter (`system`, `rate_limit_event`) and empty turns are
  emitted at `level: debug`, so fatop hides them at the default `≥info` filter
  but they remain available when you drop the level. Everything is still
  captured — nothing is dropped at write time.
- `run_timeout` — the watchdog killed a hung `claude` (idle or hard timeout);
  the run is then reported as `BLOCKED`. `fields`: `story_id`.
- `run_result` — terminal outcome. `fields`: `event` (`DONE`/`BLOCKED`...),
  `pr`, `summary`.

## Feature flags

- `FATTY_EVENTS_DISABLE=1` — disable all event emission for an agent.
- `FATTY_AUTHOR_STREAM_EVENTS=0` — disable only the author Claude stream capture
  (the service-level author events still emit).
- `FATTY_AUTHOR_IDLE_TIMEOUT` — seconds of no Claude output before the watchdog
  kills the run (default 600; 0 disables).
- `FATTY_AUTHOR_HARD_TIMEOUT` — max total seconds for one Claude run before the
  watchdog kills it (default 3600; 0 disables).
