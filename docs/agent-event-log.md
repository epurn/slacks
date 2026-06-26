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
- `roadmap_state_mismatch` — a roadmap-table State disagrees with the story
  file's front-matter `state:`. Only the actionable direction (a story that
  looks ready in its file but is not promoted in the table — a starvation risk)
  is `level: warn`; the benign post-merge direction (table merged, file not yet)
  is `level: debug` since the file is reconciled separately. `fields`:
  `story_id`, `table_state`, `file_state`.
- `story_merged` — the steward git-confirmed a story's branch merged and
  recorded it in its **own run-state** (`<run_dir>/merged-stories.json`), NOT in
  the fatty repo. `info`. `fields`: `story_id`. The fatty checkout is left
  pristine so `health.sync_base` can fast-forward it; the steward overlays these
  ids as `merged` when routing each cycle, so a merged story is never
  re-assigned even if the origin roadmap still lists it as ready.
- `prune_closed_pr` — a `PR-<n>` fix-job's PR is no longer open, so its run-state
  (`<run_dir>/PR-<n>.json` + `.log`) and worktree were cleaned up. `info`.
  `fields`: `pr`. Story prune (`prune_merged_branch`) only covers roadmap
  stories; this reconciles the transient PR fix-jobs that story prune skips, so
  merged/closed PRs no longer linger as phantom runs-in-flight. Runs only on a
  real poll where the open-PR set is authoritative; the local branch is deleted
  only when git confirms it merged (a closed-unmerged branch keeps its commits).
- `prune_orphan_worktree` — a directory under the worktree root matched no
  registered git worktree and no active run-state, so it was removed. `info`.
  `fields`: none beyond `run_id` (the dir name).
- `orphan_worktree_kept` — an unregistered directory still held a `.git`, so the
  orphan sweep left it in place rather than risk destroying a working tree with
  history. `warn`. `fields`: none beyond `run_id` (the dir name).
- `worktree_recovered` — a leftover worktree blocked (re)assignment (dirty tree,
  wrong branch, or a non-worktree dir — typically a dead author's remains) and
  was force-removed so it could be recreated from a clean base. `warn`. Discards
  uncommitted work by design; committed work survives on the branch ref. Gated
  by `FATTY_STEWARD_RECOVER_WORKTREES` (default on). `fields`: none beyond
  `run_id` (story id).
- `assignment_failed` — `ensure_worktree`/author launch raised for one story or
  PR, so the steward skipped just that item (warn) and kept assigning the rest
  instead of exiting non-zero and crash-looping under launchd KeepAlive. The
  item is retried next poll. `warn`. `fields`: `story_id`.
- `orphan_branch_publishing` — a local story branch with unpushed commits, no open
  PR, and no active author (an author killed/crashed after commit but before
  push+PR) was handed to the author's no-Claude `publish` mode, which pushes the
  existing commits and opens a PR (zero model cost). The normal review/merge/prune
  lifecycle then frees the lane — fully hands-off recovery. Default on; gate with
  `FATTY_STEWARD_PUBLISH_ORPHANS`. `warn`. `fields`: `story_id`, `branch`, `ahead`.
- `orphan_branch_unpublished` — the same orphan condition, but emitted only when
  `FATTY_STEWARD_PUBLISH_ORPHANS=0` disables auto-publish. The branch can never
  merge, so it would hold its lanes forever and silently starve the queue; this
  `warn` fires every poll until an operator or author publishes or deletes it.
  `fields`: `story_id`, `branch`, `ahead`, `lanes`.
- `recovered_orphan_branch` — an **empty** local story branch (no commits ahead of
  base, no PR, no active author) was reclaimed: its worktree was recovered and the
  branch deleted, freeing the slot. Safe because there is no committed work to
  lose. Gated by `FATTY_STEWARD_RECOVER_WORKTREES` (default on). `warn`. `fields`:
  `story_id`, `branch`.

Health guard + safe auto-recovery (the steward never takes a destructive remote
git action — push, force-push, rebase, branch delete — those only warn):

- `roadmap_missing_link` — a ready story's roadmap row links no story file;
  assignment is held. `warn`. `fields`: `story_id`.
- `story_file_missing` — a ready story's linked file is absent on disk;
  assignment held. `warn`. `fields`: `story_id`, `path`.
- `story_file_untracked` — a ready story's file is not committed; authors build
  from origin/`base` and would get no context, so assignment is held. `warn`.
- `story_file_unpushed` — a ready story's file is committed but not on
  origin/`base` yet; assignment is held **only** when origin was freshly
  fetched (otherwise warn-only, to avoid false holds on a stale ref). `warn`.
- `git_drift` — local `base` diverged from origin in a way the steward won't
  auto-resolve (local commits present, dirty tree, or on another branch).
  `warn`. `fields`: `ahead`, `behind`, `base`.
- `synced_base` — the steward fast-forwarded local `base` to origin/`base`
  (clean tree, no local commits) so the roadmap can't drift. `info`.
  `fields`: `base`, `behind`.
- `recovered_stale_marker` — removed a `.active` lane marker whose author
  process is gone, freeing the lane. `warn`. `fields`: `story_id`, `age_seconds`.

Held stories are routed as the non-ready sentinel state `blocked_missing_context`
for that cycle, so an author never starts a build it cannot complete.

### reviewer
- `watch_start` — watch loop began. `fields`: `repo`, `interval`, `auto_merge`.
- `review_start` — reviewing a PR head. `fields`: `pr`, `model`, `files`.
- `review_posted` — review submitted. `fields`: `pr`, `decision`.
- `status_set` — commit status set. `fields`: `pr`, `context`, `state`.
- `auto_merge_enabled` — native auto-merge turned on. `fields`: `pr`.
- `review_skip` — head already reviewed / draft. `fields`: `pr`, `reason`.
- `review_usage` — token/cost telemetry for one Claude review. `fields`: `pr`,
  `model`, `input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `total_cost_usd`, `num_turns`. Emitted even when the
  review run fails, so a costly failed review is still visible. A review whose
  input is mostly `cache_read_input_tokens` is far cheaper than its raw
  input-token count implies.

### usage-limit pause (all agents)
- `usage_limit_paused` — an agent's `claude -p` call hit a subscription usage
  limit (5-hour `session`, `weekly`, or a model-specific limit), so a shared
  pause sentinel was recorded at `$FATTY_AGENTS_STATE_DIR/usage-pause.json`
  (default `~/.config/fatty-agents/`). `warn`. `fields`: `kind`, `reset_at`
  (epoch), plus `story_id`/`pr` of the run that hit it. The author/reviewer that
  detects it records the pause; the author also emits this if it skips a run
  because a pause is already active.
- `usage_limit_waiting` — a poller (steward or reviewer) found an active pause
  and is backing off instead of doing work. `info`. `fields`: `reset_at`,
  `wait_seconds` (>= 600 — the wait cadence is floored at 10 minutes). Emitted
  each wait tick.
- `usage_limit_resumed` — the pause window elapsed (or a clean run cleared it)
  and the poller resumed normal cadence. `info`. `fields`: none beyond
  `run_id=service`.

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
- `run_usage` — token/cost telemetry for one Claude author run. `fields`:
  `story_id`, `model`, `mode`, `input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`, `total_cost_usd`,
  `num_turns`. Emitted even on a BLOCKED/failed run so a blown budget is still
  visible. Only the streaming path (`FATTY_AUTHOR_STREAM_EVENTS=1`, the default)
  carries usage; the plain path emits no result envelope. A run dominated by
  `cache_read_input_tokens` is far cheaper than its raw input count implies.

## Usage-limit auto-pause

All three agents share a pause sentinel so that when any `claude -p` call hits a
subscription usage limit, the system stops spending and resumes automatically
when the window resets — no human intervention.

- The author/reviewer detect the limit from the failed call's output (the limit
  message text — broad match, since the exact wording is version-dependent),
  parse the reset time when present, and write the sentinel.
- The steward and reviewer pollers check the sentinel each cycle; while paused
  they skip all work (the steward launches no authors) and back off to the wait
  cadence. The no-Claude author `publish` path is exempt — orphan recovery still
  runs while paused.
- A clean `claude` run clears the sentinel; an expired sentinel auto-clears, so a
  wrong/unknown reset time self-corrects within one wait interval (the next real
  run either succeeds and clears, or re-hits the limit and re-arms).

Config:
- `FATTY_AGENTS_STATE_DIR` — shared state dir for the sentinel (default
  `~/.config/fatty-agents`, where the GitHub App keys already live).
- `FATTY_PAUSE_POLL_SECONDS` — wait cadence while paused (default `600`; floored
  at `600` — polls run no more often than every 10 minutes in wait mode).
- `FATTY_PAUSE_FALLBACK_SECONDS` — retry window when the reset time can't be
  parsed from the limit message (default `600`).

## Feature flags

- `FATTY_EVENTS_DISABLE=1` — disable all event emission for an agent.
- `FATTY_AUTHOR_STREAM_EVENTS=0` — disable only the author Claude stream capture
  (the service-level author events still emit).
- `FATTY_AUTHOR_IDLE_TIMEOUT` — seconds of no Claude output before the watchdog
  kills the run (default 600; 0 disables).
- `FATTY_AUTHOR_HARD_TIMEOUT` — max total seconds for one Claude run before the
  watchdog kills it (default 3600; 0 disables).
- `FATTY_STEWARD_AUTO_SYNC` — steward fast-forwards local `base` to origin each
  poll when safe (default `1`; set `0` to only warn on drift).
- `FATTY_STEWARD_BASE_BRANCH` — the base branch the guard checks against
  (default `main`).
- `FATTY_STEWARD_ORPHAN_GRACE_SECONDS` — how long a local story branch's worktree
  must be untouched before orphan reconciliation considers it (default `300`). The
  grace window prevents reaping/warning on an author that just committed and is
  about to push.
- `FATTY_STEWARD_PUBLISH_ORPHANS` — when `1` (default), an orphaned branch with
  unpushed commits is auto-recovered by launching the author's no-Claude `publish`
  mode (push + open PR, zero model cost). Set `0` to fall back to warn-only
  (`orphan_branch_unpublished`) and recover by hand.
