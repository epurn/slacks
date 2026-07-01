# Branching and PRs

## Branches

Use:

- `story/<id>-<slug>`
- `fix/<id>-<slug>`
- `security/<id>-<slug>`
- `chore/<slug>`

Do not work directly on `main`.
Base feature branches on current `origin/main`.

## Coordination Flow

1. Promote a story only when it meets the story readiness rule.
2. Pick up a ready story when its dependencies are complete and its lanes are
   unoccupied.
3. Work on a branch from current `origin/main`.
4. Open a PR with verification, security, privacy, and story context.
5. Route the PR to an independent reviewer.
6. New commits after a review require a fresh current-head review before merge.

Implementation and review of the same change must be done by different parties.
Credentials, machine-specific paths, and local automation state stay outside this
repo.

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
- keep native required approving review count at zero for the app-reviewer flow,
- require conversation resolution,
- require status checks:
  - `governance`,
  - `reviewer-approved`,
  - `mobile-e2e` (mobile end-to-end Maestro smoke gate, FTY-161),
  - future backend/mobile/security checks,
- block force pushes,
- block deletions,
- apply rules to administrators where practical.

The `reviewer-approved` commit status is the automated non-author review gate.
The reviewer agent sets it for the current PR head SHA. This custom status is
the required reviewer gate because GitHub's native required-review rule may not
count approvals submitted by the `fatty-reviewer` app as eligible native
approvals.

## Merge Style

Use squash merge for a clean linear history unless a release branch needs a different strategy.

## Bootstrap

For the initial empty repository, push the governance scaffold to `main`, then enable branch protection immediately. After protection is enabled, all further work should use PRs.
