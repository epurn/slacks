# Review Policy

Every PR needs a separate reviewer phase before merge.

## Author and Reviewer Separation

Authoring and reviewing are separate responsibilities. Whoever implements a
change must not be the one who approves it. Credentials, machine-specific paths,
and local automation state do not belong in this repo.

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

The reviewer agent publishes a required `reviewer-approved` commit status for
the current PR head SHA. The status may pass only after an eligible reviewer
other than the PR author approves that exact head. Branch protection should
require this status as the authoritative separate review gate. Do not also
require a native GitHub approving review for this self-hosted app-reviewer flow:
GitHub may not count the `fatty-reviewer` app's approval as an eligible native
review even when the custom gate correctly accepts it.

Long term, reviewer enforcement can move from repository workflow code to an
external required status or check owned by trusted project infrastructure.

## Emergency Exception

Emergency security fixes may use an accelerated review, but still require a post-merge review and written follow-up issue.
