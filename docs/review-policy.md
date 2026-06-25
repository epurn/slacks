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

The `reviewer-gate` GitHub workflow checks that at least one approval exists on the current PR head SHA from an eligible reviewer other than the PR author. The initial eligible reviewer is the local `fatty-reviewer[bot]` GitHub App identity, pinned by GitHub user id and Bot type. GitHub branch protection should require this workflow and native approval while the reviewer signal is still implemented as repository workflow code.

The long-term autonomous merge gate should move from repository workflow code to an immutable external GitHub App status or check. Until then, native approval protects workflow and governance changes from editing their own review gate.

## Emergency Exception

Emergency security fixes may use an accelerated review, but still require a post-merge review and written follow-up issue.
