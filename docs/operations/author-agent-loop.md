# Author Agent Loop

This document defines how Codex should autonomously build Fatty.

## Roles

- **Author agent:** implements stories and opens PRs. In local Codex, this is the current coding agent.
- **Story steward:** separate local `fatty-steward` GitHub App identity that manages queue health, worktree assignment, memory routing, and author launches.
- **Reviewer agent:** separate local `fatty-reviewer` GitHub App identity that approves, comments, or requests changes.
- **Event router:** deterministic local code that decides whether there is actionable work before waking an LLM.
- **Merger:** GitHub native auto-merge behind branch protection.

The author agent must not approve its own PR.
The steward must not review or merge implementation work it authored.

## Default Loop

1. Inspect open PRs first.
2. If any PR has requested changes, fix the highest-priority rejected PR before starting new work.
3. If CI is failing for an authored PR, debug and fix that PR.
4. If PRs are waiting only for reviewer approval, do not sit idle.
5. Run the deterministic steward router or equivalent lane check.
6. Choose the next `ready` or `ready_with_notes` story from `docs/stories/v1-roadmap.md` that does not conflict with open PRs.
7. Start that story from current `origin/main`, not from another unmerged story branch.
8. Implement one thin slice on a story branch.
9. Open a PR and allow the reviewer agent to run.

Waiting for review is normal queue time. The author agent should keep building independent slices while the reviewer agent evaluates already-open PRs.
If deterministic checks find no actionable work, exit quietly instead of waking an LLM to confirm emptiness.

## Story Steward

Use `docs/operations/story-steward-orchestrator.md` and `agents/playbooks/story-steward.md` for queue coordination.

The steward may:

- create, split, promote, demote, and reorder stories,
- assign fresh worktrees,
- update durable memory when it will save future work,
- create story-only planning PRs.

The steward may not:

- change v1 product goals without recorded rationale,
- inspect secrets by default,
- make paid service commitments without approval,
- review or merge its own implementation.

## Story Metadata

Every `ready` or `ready_with_notes` story must include YAML front matter with:

- `id`,
- `state`,
- `primary_lane`,
- `touched_lanes`,
- `risk`,
- `tags`,
- `approved_dependencies`,
- `requires_context`,
- `review_focus`,
- `autonomous`.

Every promoted story must include a readiness sanity pass in the story file.
Plain `ready` means no material caveats. Use `ready_with_notes` when assumptions
are safe for autonomy but should remain visible.

## PR Rejection Monitor

Periodic checks should look for:

- open PRs with `reviewDecision=CHANGES_REQUESTED`,
- failed required checks,
- reviewer comments from `fatty-reviewer[bot]`,
- unresolved conversations,
- stale PRs with no reviewer activity.

If a PR is blocked by review or CI, the author agent should:

1. fetch the PR branch,
2. inspect reviewer comments and failing checks,
3. make a narrow fix,
4. run verification,
5. push to the same PR branch,
6. summarize the fix in the PR.

## Starting New Work

New work may start only when:

- no authored PR has requested changes,
- no authored PR has failing CI that the author can fix,
- the next story is marked `ready` or `ready_with_notes`,
- the story has acceptance criteria,
- the story has YAML metadata and a readiness sanity pass,
- the story's dependencies are merged,
- the story's lane does not overlap with open unmerged PRs.

New work must start from `origin/main`:

```sh
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c story/<id>-<slug>
```

If local checkout state prevents switching safely, use a fresh worktree or report the blocker instead of rebasing unrelated work.

## Worktrees

Parallel implementation must use one story per worktree:

```text
/Users/epurn/workspace/fatty
/Users/epurn/workspace/fatty-worktrees/
  FTY-010-monorepo-scaffold/
  FTY-012-backend-skeleton/
```

Worktrees are created from current `origin/main`. Authors should not juggle
multiple story branches in one checkout or independently choose new work while
already assigned.

## Parallel Work Lanes

Use lanes to avoid accidental conflicts. Only one open PR should actively edit a lane's ownership files unless the later PR is explicitly a fix for the earlier PR.

| Lane | Ownership | Examples |
| --- | --- | --- |
| `governance` | Agent rules, workflows, story process, review policy | `AGENTS.md`, `agents/`, `.github/`, `docs/operations/`, `docs/stories/` |
| `backend-core` | FastAPI app, config, service layout, health checks | `apps/api/`, backend tests, backend tooling |
| `mobile-core` | Expo app shell, navigation, iOS UI primitives | `apps/mobile/`, mobile tests, mobile tooling |
| `contracts` | API schemas, DTOs, job payloads, estimator schemas | `docs/contracts/`, shared contract packages |
| `infra` | Docker Compose, database, Redis, Celery, migrations tooling | `compose.yaml`, `infra/`, deployment docs |
| `estimator` | LLM provider config, estimator jobs, nutrition/exercise calculators | estimator packages, provider adapters, calculator tests |
| `security-privacy` | Threat model, retention, auth controls, hardening tests | `docs/security/`, security tests, auth policy |

Lane rules:

- If an open PR touches a lane, choose a story from another lane while it waits for review.
- If a story needs two lanes, declare both in the PR and avoid starting other stories in either lane.
- Cross-lane contracts should be added before dependent implementation when possible.
- Dependency upgrades are their own lane unless required by the story.

## Conflict Check

Before starting a new story:

1. List open PR files with `gh pr diff --name-only` or GitHub PR metadata.
2. Identify each open PR's lane from changed paths.
3. Identify the candidate story's lane from `docs/stories/v1-roadmap.md`.
4. Skip candidates whose lane overlaps with open unmerged PRs.
5. Prefer the next ready or ready-with-notes story in a different lane.

## Story Source

Use `docs/stories/v1-roadmap.md` as the initial source of truth until GitHub Issues are fully populated. Once issues exist, keep the roadmap as the ordered map and link each row to the issue.

## Branches

New branches must use:

- `story/<id>-<slug>` for roadmap stories,
- `fix/<id>-<slug>` for review or CI fixes,
- `security/<id>-<slug>` for security/privacy issues.

If a branch was opened before this rule existed, keep the PR branch stable and include the story ID in the PR title or body. Do not close and recreate a review-ready PR solely to rename its head branch.

## Automation

A recurring Codex automation should periodically check PR state and continue this loop. It should not bypass review gates, approve its own PRs, or merge directly.

Automation may continue building independent `ready` or `ready_with_notes` stories while earlier PRs wait for review. It must fix rejected or failing PRs before starting additional new stories.
Automation must use deterministic routing first. If all PRs are only waiting on
human/native approval and no non-conflicting ready story is available, it should
pause, exit quietly, or avoid scheduling another wakeup until a relevant event.
