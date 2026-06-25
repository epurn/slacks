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
- require conversation resolution,
- require status checks before merging,
- require branches to be up to date before merging,
- require the `governance` status check,
- require the `separate-reviewer` status check,
- require at least one native approving review until the reviewer app owns an external required status,
- dismiss stale approvals when new commits are pushed,
- require approval of the latest reviewable push,
- block force pushes,
- block deletions,
- include administrators when practical.

Fatty enforces non-author review with two gates for now: GitHub's native required approval and the required `separate-reviewer` workflow. The workflow checks for an approval from the eligible `fatty-reviewer[bot]` app identity on the current PR head SHA. Native approval remains required until the reviewer app can publish an immutable external required status or check that PR authors cannot edit through repository workflows.

## Private Repository Plan Caveat

GitHub may reject branch protection on a private repository depending on the account or organization plan.

Observed bootstrap response for this private repo:

```text
Upgrade to GitHub Pro or make this repository public to enable this feature.
```

If that happens, the workflows are still installed and will run, but GitHub will not block direct pushes or unreviewed merges. The enforcement options are:

1. Upgrade the repository owner/organization plan.
2. Make the repository public.
3. Keep the repository private and treat PR review as a manual rule until branch protection is available.

## GitHub CLI Setup

After the initial commit is pushed, this can be configured with the GitHub API:

```sh
gh api \
  --method PUT \
  repos/epurn/fatty/branches/main/protection \
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
