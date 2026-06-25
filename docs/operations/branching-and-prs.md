# Branching and PRs

## Branches

Use:

- `story/<id>-<slug>`
- `fix/<id>-<slug>`
- `security/<id>-<slug>`
- `chore/<slug>`

Do not work directly on `main`.

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
- require conversation resolution,
- require status checks:
  - `governance`,
  - `separate-reviewer`,
  - future backend/mobile/security checks,
- block force pushes,
- block deletions,
- apply rules to administrators where practical.

The `separate-reviewer` status check is the enforceable non-author review gate. Do not also require GitHub's native approval count for the autonomous queue; local GitHub App approvals can satisfy the workflow while still appearing as `REVIEW_REQUIRED` to GitHub's native review decision.

## Merge Style

Use squash merge for a clean linear history unless a release branch needs a different strategy.

## Bootstrap

For the initial empty repository, push the governance scaffold to `main`, then enable branch protection immediately. After protection is enabled, all further work should use PRs.
