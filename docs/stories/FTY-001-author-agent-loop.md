# FTY-001: Author-Agent Loop And PR Rejection Monitor

## State

ready

## Lane

governance

## Dependencies

- FTY-000

## Outcome

Codex can operate Fatty's author loop autonomously: inspect blocked PRs, fix rejected or failing work first, and continue independent queued stories while earlier PRs wait for review.

## Scope

- Define the author, reviewer, and merger roles.
- Document the PR rejection monitor behavior.
- Document how the author agent chooses the next non-conflicting story.
- Define parallel work lanes and conflict checks.
- Keep the root agent instructions small by moving detail into playbooks.
- Make governance verification check that the loop and roadmap docs exist.

## Non-Goals

- Implement product code.
- Replace GitHub branch protection or the separate reviewer gate.
- Build a full GitHub Issues synchronization system.
- Allow the author agent to approve or merge its own work.

## Contracts

- `AGENTS.md` remains the top-level agent contract.
- `docs/operations/author-agent-loop.md` defines the loop contract.
- `docs/stories/v1-roadmap.md` defines the initial queued story order.

## Security / Privacy

This story changes development automation only. It must preserve the non-author review gate, avoid new secrets, and keep automation from bypassing branch protection.

## Acceptance Criteria

- The author loop prioritizes requested changes and failing CI before new work.
- The loop may continue non-conflicting ready stories while other PRs wait only for review.
- New work starts from current `origin/main`, not from an unmerged feature branch.
- Parallel work lanes are documented.
- Recurring PR monitoring is configured outside the repo for local Codex automation.
- Governance verification covers the loop and roadmap documents.

## Verification

- Run `make verify`.
- Confirm PR #4 has a separate reviewer result before merge.

