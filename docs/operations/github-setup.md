# GitHub Setup

This document records repository settings required for CI and reviewer
enforcement.

## Required Workflows

The first commit must include:

- `.github/workflows/governance.yml`

Required status checks on `main`:

- `governance`
- `reviewer-approved`
- `mobile-e2e` (the mobile end-to-end Maestro smoke gate, FTY-161)

## Branch Protection

Configure `main` with:

- require a pull request before merging,
- require conversation resolution,
- require status checks before merging,
- require branches to be up to date before merging,
- require the `governance` status check,
- require the `reviewer-approved` status check,
- require the `mobile-e2e` status check (FTY-161),
- keep native required approving review count at zero for the app-reviewer flow,
- block force pushes,
- block deletions,
- include administrators when practical.

Fatty enforces non-author review with the required `reviewer-approved` commit
status published by the reviewer agent. The status may pass only after approval
from an eligible reviewer on the current PR head SHA. This custom status is the
merge gate because GitHub's native required-review rule may not count approvals
submitted by the `fatty-reviewer` app as eligible native approvals.

## Auto-Merge

For the autonomous flow, the reviewer enables GitHub native auto-merge on a PR
after it approves the current head; GitHub then merges automatically once
`governance`, `mobile-e2e`, and `reviewer-approved` are green and branch
protection is satisfied. This requires:

- **Repo-level auto-merge enabled.** Settings → General → "Allow auto-merge",
  or:

  ```sh
  gh api --method PATCH repos/OWNER/REPO -f allow_auto_merge=true
  ```

  Without this, `gh pr merge --auto` fails and the PR is left unmerged.

- **A logged-in local `gh` identity** on the machine running the reviewer — it
  sets merge intent using `gh` (`gh auth login`). Branch protection still gates
  the actual merge.

- Squash auto-merge is compatible with `required_linear_history`. Note that
  `required_conversation_resolution` and `enforce_admins` mean an unresolved
  review thread blocks the merge until resolved — even for you.

## GitHub CLI Setup

After the initial commit is pushed, this can be configured with the GitHub API:

```sh
gh api \
  --method PUT \
  repos/OWNER/REPO/branches/main/protection \
  --input docs/operations/main-branch-protection.json
```

GitHub may reject required status checks until each workflow has run at least once. If that happens, open a tiny PR, let all required checks run, then apply the protection again.

## Manual Setup Path

When branch protection is available:

1. Open GitHub repository settings.
2. Go to Branches.
3. Add a branch protection rule for `main`.
4. Enable "Require a pull request before merging".
5. Set required native approving reviews to zero.
6. Leave stale approval dismissal disabled.
7. Leave latest-push native approval disabled.
8. Enable conversation resolution.
9. Enable required status checks.
10. Require branches to be up to date before merging.
11. Require `governance`.
12. Require `reviewer-approved`.
13. Require `mobile-e2e` (FTY-161).
14. Block force pushes and deletions.
15. Apply to administrators if the plan allows it.
