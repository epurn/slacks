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

The `reviewer-gate` GitHub workflow checks that at least one approval exists from a reviewer other than the PR author. GitHub branch protection should require this workflow and normal review approval before merge.

## Emergency Exception

Emergency security fixes may use an accelerated review, but still require a post-merge review and written follow-up issue.

