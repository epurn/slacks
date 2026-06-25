# Author Agent Loop

This document defines how Codex should autonomously build Fatty.

## Roles

- **Author agent:** implements stories and opens PRs. In local Codex, this is the current coding agent.
- **Reviewer agent:** separate local `fatty-reviewer` GitHub App identity that approves, comments, or requests changes.
- **Merger:** GitHub native auto-merge behind branch protection.

The author agent must not approve its own PR.

## Default Loop

1. Inspect open PRs first.
2. If any PR has requested changes, fix the highest-priority rejected PR before starting new work.
3. If CI is failing for an authored PR, debug and fix that PR.
4. If PRs are waiting only for reviewer approval, leave them alone unless stale.
5. If there is no active blocked PR, choose the next `ready` story from `docs/stories/v1-roadmap.md`.
6. Implement one thin slice on a story branch.
7. Open a PR and allow the reviewer agent to run.

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
- the next story is marked `ready`,
- the story has acceptance criteria.

## Story Source

Use `docs/stories/v1-roadmap.md` as the initial source of truth until GitHub Issues are fully populated. Once issues exist, keep the roadmap as the ordered map and link each row to the issue.

## Branches

Use:

- `story/<id>-<slug>` for roadmap stories,
- `fix/<id>-<slug>` for review or CI fixes,
- `security/<id>-<slug>` for security/privacy issues.

## Automation

A recurring Codex automation should periodically check PR state and continue this loop. It should not bypass review gates, approve its own PRs, or merge directly.

