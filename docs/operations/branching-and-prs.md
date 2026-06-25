# Branching and PRs

## Branches

Use:

- `story/<id>-<slug>`
- `fix/<id>-<slug>`
- `security/<id>-<slug>`
- `chore/<slug>`

Do not work directly on `main`.
Base feature branches on current `origin/main`.

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
- require at least one native approving review,
- dismiss stale approvals,
- require review on the latest push,
- require conversation resolution,
- require status checks:
  - `governance`,
  - `separate-reviewer`,
  - future backend/mobile/security checks,
- block force pushes,
- block deletions,
- apply rules to administrators where practical.

The `separate-reviewer` status check is the automated non-author review gate.
It must evaluate approval on the current PR head SHA. Native review protection
is still required so workflow and governance changes cannot weaken their own
merge gate.

## Merge Style

Use squash merge for a clean linear history unless a release branch needs a different strategy.

## Bootstrap

For the initial empty repository, push the governance scaffold to `main`, then enable branch protection immediately. After protection is enabled, all further work should use PRs.
