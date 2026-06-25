---
id: FTY-001
state: merged
primary_lane: governance
touched_lanes:
  - governance
risk: medium
tags:
  - agent-ops
  - reviewer-gate
  - story-steward
approved_dependencies: []
requires_context:
  - agents/playbooks/story-slicing.md
  - agents/playbooks/story-steward.md
review_focus:
  - reviewer-separation
  - autonomy-safety
  - governance-verification
autonomous: true
---

# FTY-001: Author-Agent Loop And PR Rejection Monitor

## State

merged

## Lane

governance

## Dependencies

- FTY-000

## Outcome

Codex can operate Fatty's author loop autonomously: inspect blocked PRs, fix rejected or failing work first, and continue independent queued stories while earlier PRs wait for review.

## Scope

- Define the author, reviewer, and merger roles.
- Define the story steward and deterministic event router roles.
- Document the PR rejection monitor behavior.
- Document when automation should exit quietly instead of waking an LLM.
- Document how the author agent chooses the next non-conflicting story.
- Document worktree assignment and durable memory structure.
- Document story metadata, readiness sanity pass, blocker, secret, and dependency policies.
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
- `docs/operations/story-steward-orchestrator.md` defines the steward/router contract.
- `docs/stories/v1-roadmap.md` defines the initial queued story order.
- `agents/state/author-loop.md` and `agents/memory/index.md` define durable agent memory entry points.

## Security / Privacy

This story changes development automation only. It must preserve the non-author review gate, avoid new secrets, and keep automation from bypassing branch protection.

## Acceptance Criteria

- The author loop prioritizes requested changes and failing CI before new work.
- The loop may continue non-conflicting ready stories while other PRs wait only for review.
- Empty monitor checks do not wake an LLM or keep running noisily when no work is actionable.
- New work starts from current `origin/main`, not from an unmerged feature branch.
- Parallel work lanes are documented.
- Worktree assignment is documented as one story, one branch, one worktree.
- A deterministic steward router exists for cheap no-action/start-story/steward decisions.
- Ready story metadata and readiness sanity pass rules are documented.
- Durable memory entry points exist and are intentionally sparse.
- Recurring PR monitoring is configured outside the repo for local Codex automation.
- Governance verification covers the loop and roadmap documents.

## Verification

- Run `make verify`.
- Confirm PR #4 has a separate reviewer result before merge.

## Readiness Sanity Pass

- Product decision gaps: none.
- Cross-lane impact: governance only; future app lanes are coordinated through metadata and worktree rules.
- Security/privacy risk: preserves non-author review and keeps secrets off-limits by default.
- Verification path: `make verify`.
- Assumptions safe for autonomy: yes.
