# Story Steward Orchestrator

Fatty uses a separate steward agent package for queue coordination. The steward
may use an LLM for planning judgment, but the always-on service must route work
with deterministic code first.

## Roles

- **Event router:** cheap local code that inspects GitHub state, story metadata,
  worktree assignments, and concurrency limits.
- **Story steward:** separate `fatty-steward` GitHub App identity that manages
  the queue, story state, memory hygiene, and worktree assignments.
- **Author agent:** separate `fatty-author` identity that implements or fixes
  exactly one assigned story or PR.
- **Reviewer agent:** separate `fatty-reviewer` identity that reviews PRs.
- **Merger:** GitHub native auto-merge behind branch protection.

The steward manages work. The reviewer judges work. The author writes work.
No role approves or merges its own implementation.

## Router Actions

The router may emit only these actions:

- `no_action`: nothing is actionable; exit silently.
- `assign_story`: create a fresh worktree and launch an author job.
- `fix_blocked_pr`: launch an author fix job for a rejected or failing PR.
- `invoke_steward`: run steward Codex for planning, splitting, promotion,
  demotion, or blocker triage.
- `cleanup_merged`: clean safe merged worktrees and update state.

If all open PRs are only waiting on human/native approval and no safe
non-conflicting story is ready, the router must not wake an LLM.

## Wake Conditions

Invoke steward judgment only when deterministic checks find:

- ready queue below threshold,
- repeated blocker or stale story state,
- planning notes that need story files,
- merged PR requiring state cleanup,
- candidate story promotion, split, or dependency ordering,
- open PR lane changes that make new assignment possible.

## Worktree Rules

Parallel implementation uses one story, one branch, one worktree, one author
context.

```text
/Users/epurn/workspace/fatty
/Users/epurn/workspace/fatty-worktrees/
  FTY-010-monorepo-scaffold/
  FTY-012-backend-skeleton/
```

Worktrees must be created from current `origin/main`. Do not stack feature work
on unmerged feature branches. Cleanup is allowed only when there is no unpushed
or uncommitted work.

## Steward Limits

The steward may reorder within a milestone, split stories, create prerequisite
stories, promote or demote stories after a sanity pass, update memory, and
assign worktrees.

The steward must not change v1 product goals, delete user-approved scope, make
paid service commitments, inspect secrets, bypass branch protection, or merge
its own work.

