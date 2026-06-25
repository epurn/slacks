# Branching and PRs

## Branches

Use:

- `story/<id>-<slug>`
- `fix/<id>-<slug>`
- `security/<id>-<slug>`
- `chore/<slug>`

Do not work directly on `main`.
For parallel autonomous work, use one story branch per fresh worktree created
from current `origin/main`.

## Pull Requests

Every PR must include:

- story, contract, or ADR reference,
- summary of changes,
- tests and verification,
- security impact,
- privacy impact,
- reviewer phase checklist.

## Main Branch Protection

Configure GitHub `main` with:

- require pull request before merge,
- require native approval until the reviewer app owns an external required status,
- dismiss stale approvals,
- require latest-push approval,
- require conversation resolution,
- require status checks:
  - `governance`,
  - `separate-reviewer`,
  - future backend/mobile/security checks,
- block force pushes,
- block deletions,
- apply rules to administrators where practical.

The `separate-reviewer` status check is the automated reviewer gate, but native GitHub approval remains required until the reviewer app owns an external required status or check that PR authors cannot edit through repository workflows.

## Merge Style

Use squash merge for a clean linear history unless a release branch needs a different strategy.

## Bootstrap

For the initial empty repository, push the governance scaffold to `main`, then enable branch protection immediately. After protection is enabled, all further work should use PRs.

## Worktree Cleanup

After a PR merges, the story steward or event router may clean up the associated
local worktree and branch only when there is no unpushed work. If cleanup is
uncertain, leave the worktree in place and report a blocked cleanup task.
