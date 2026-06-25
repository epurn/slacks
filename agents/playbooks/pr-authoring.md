# PR Authoring Playbook

Use this before opening or updating a pull request.

## PR Must Explain

- the story or contract,
- what changed,
- what did not change,
- tests and verification,
- security impact,
- privacy impact,
- follow-up work that is intentionally out of scope,
- dependency additions and the story approval for them.

## PR Must Not

- hide failed checks,
- include unrelated refactors,
- include secrets or real user data,
- add unapproved dependencies for the story,
- claim review is complete without a separate reviewer,
- leave behavior undocumented when contracts changed.

## Suggested PR Size

Prefer PRs that can be reviewed in one sitting. Split work when a change spans unrelated domains or requires different reviewers.
