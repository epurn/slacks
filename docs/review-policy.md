# Review Policy

Every PR needs a separate reviewer phase before merge.

## Author Phase

The author implements the change, updates tests/docs/contracts, runs checks, and completes the PR template.

The author must not self-approve or merge based only on their own review.

## Reviewer Phase

A reviewer inspects the diff using `agents/reviewer/review-checklist.md`.

The reviewer should prioritize:

- correctness,
- regressions,
- missing tests,
- security risks,
- privacy risks,
- contract drift,
- maintainability,
- user-facing behavior.

## Automated Gate

The `reviewer-gate` GitHub workflow checks that at least one approval exists on the current PR head SHA from an eligible reviewer other than the PR author. The initial eligible reviewer is the local `fatty-reviewer[bot]` GitHub App identity, pinned by GitHub user id and Bot type. GitHub branch protection should require this workflow.

Keep GitHub's pull-request requirement enabled, but do not also require GitHub's native approving review count for the autonomous queue. GitHub may not count local GitHub App approvals as native collaborator approvals, which would block safe parallel automation even when the required `separate-reviewer` check has passed.

## Emergency Exception

Emergency security fixes may use an accelerated review, but still require a post-merge review and written follow-up issue.
