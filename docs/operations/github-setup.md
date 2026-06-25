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
- do not require GitHub's native approving review count for the autonomous queue,
- block force pushes,
- block deletions,
- include administrators when practical.

Fatty enforces non-author review through the required `separate-reviewer` workflow instead of GitHub's native required-review count. This is intentional: local GitHub App reviews satisfy the workflow gate, but GitHub may not count those app approvals as native collaborator approvals. The workflow requires an approval from a non-author reviewer on the current PR head SHA, so stale approvals after branch updates do not pass.

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
5. Do not enable a native required approval count for the autonomous queue.
6. Enable conversation resolution.
7. Enable required status checks.
8. Require branches to be up to date before merging.
9. Require `governance`.
10. Require `separate-reviewer`.
11. Block force pushes and deletions.
12. Apply to administrators if the plan allows it.
