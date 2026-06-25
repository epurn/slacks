# Review Policy

Every PR needs a separate reviewer phase before merge.

## Author Phase

The author implements the change, updates tests/docs/contracts, runs checks, and completes the PR template.

The author must not self-approve or merge based only on their own review.

## Reviewer Phase

A reviewer inspects the diff using `docs/review-checklist.md`.

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

The `reviewer-gate` GitHub workflow checks that at least one approval exists on
the current PR head SHA from an eligible reviewer other than the PR author.
Branch protection should require this workflow and should not allow authors to
merge based only on their own review.

Long term, reviewer enforcement can move from repository workflow code to an
external required status or check owned by trusted project infrastructure.

## Emergency Exception

Emergency security fixes may use an accelerated review, but still require a post-merge review and written follow-up issue.
