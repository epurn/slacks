# GitHub Setup

This document records repository settings required for CI and reviewer
enforcement.

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
- require conversation resolution,
- require status checks before merging,
- require branches to be up to date before merging,
- require the `governance` status check,
- require the `separate-reviewer` status check,
- require at least one native approving review,
- dismiss stale approvals when new commits are pushed,
- require approval of the latest reviewable push,
- block force pushes,
- block deletions,
- include administrators when practical.

Fatty enforces non-author review with the required `separate-reviewer`
workflow. The workflow checks for an approval from an eligible reviewer on the
current PR head SHA. Native review protection remains required so workflow and
governance changes cannot weaken their own merge gate.

## GitHub CLI Setup

After the initial commit is pushed, this can be configured with the GitHub API:

```sh
gh api \
  --method PUT \
  repos/OWNER/REPO/branches/main/protection \
  --input docs/operations/main-branch-protection.json
```

GitHub may reject required status checks until each workflow has run at least once. If that happens, open a tiny PR, let both checks run, then apply the protection again.

## Manual Setup Path

When branch protection is available:

1. Open GitHub repository settings.
2. Go to Branches.
3. Add a branch protection rule for `main`.
4. Enable "Require a pull request before merging".
5. Require at least one native approving review.
6. Enable stale approval dismissal.
7. Require approval of the latest reviewable push.
8. Enable conversation resolution.
9. Enable required status checks.
10. Require branches to be up to date before merging.
11. Require `governance`.
12. Require `separate-reviewer`.
13. Block force pushes and deletions.
14. Apply to administrators if the plan allows it.
