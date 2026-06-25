# Author Loop State

This is a compact pointer for future agents. Keep durable detail in focused
memory files linked from `agents/memory/index.md`.

## Current Operating Rules

- Fix rejected PRs and deterministic CI failures before starting new stories.
- Continue independent ready stories only when their lanes do not overlap open
  PRs.
- New implementation work starts from current `origin/main`.
- Use one story, one branch, one worktree, one author context.
- Do not inspect `.env` or secret files by default.
- If secret access is required, block only that story and continue elsewhere.
- Ready stories require metadata and a readiness sanity pass.

## Current Constraints

- Native GitHub approval remains required until the reviewer app owns an
  immutable external status/check.
- The steward is a separate local package that routes deterministically before
  invoking LLM judgment.

## Memory Index

Read `agents/memory/index.md` only when durable memory is relevant.

