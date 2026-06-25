# Review Policy

Every PR needs a separate reviewer phase before merge.

## Role Phases

Planning, stewardship, authoring, and reviewing are separate roles.

The planner creates, refines, and promotes stories. The steward picks up ready
stories, identifies lane conflicts, assigns author work, watches PR state, and
routes PRs to reviewers. Authors implement. Reviewers inspect current PR heads.

Role routing must preserve the public repository boundary: private automation
state, runner configuration, durable agent memory, thread IDs, credentials, and
machine-specific paths do not belong in this repo.

Steward and reviewer loops should be deterministic pollers, not long-running
Codex sessions. Pollers may run continuously as ordinary code, but each Codex
invocation should handle one bounded task and then exit.

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
