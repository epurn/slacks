# GitHub Setup

This document records the repository settings required for CI and reviewer enforcement.

## Required Workflows

The first commit must include:

- `.github/workflows/governance.yml`
- `.github/workflows/reviewer-gate.yml`

Required status checks on `main`:

- `governance`
- `separate-reviewer`

## Branch Protection

Configure `main` with:

- require a pull request before merging,
- require at least one approving review,
- dismiss stale approvals when new commits are pushed,
- require approval of the most recent reviewable push when available,
- require conversation resolution,
- require status checks before merging,
- require branches to be up to date before merging,
- require the `governance` status check,
- require the `separate-reviewer` status check,
- block force pushes,
- block deletions,
- include administrators when practical.

## GitHub CLI Setup

After the initial commit is pushed, this can be configured with the GitHub API:

```sh
gh api \
  --method PUT \
  repos/epurn/fatty/branches/main/protection \
  --input docs/operations/main-branch-protection.json
```

GitHub may reject required status checks until each workflow has run at least once. If that happens, open a tiny PR, let both checks run, then apply the protection again.

