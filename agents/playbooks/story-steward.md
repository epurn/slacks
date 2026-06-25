# Story Steward Playbook

Use this when managing the story queue, planning batches, memory routing, or
worktree assignments.

## Read First

- `agents/state/author-loop.md`
- `agents/memory/index.md`
- `docs/operations/story-steward-orchestrator.md`
- `docs/stories/v1-roadmap.md`

Then read only lane, tag, story, or memory files relevant to the task.

## Story Metadata

Every `ready` or `ready_with_notes` story must start with YAML front matter:

```yaml
---
id: FTY-010
state: ready_with_notes
primary_lane: contracts
touched_lanes:
  - backend-core
risk: low
tags:
  - scaffold
approved_dependencies: []
requires_context:
  - agents/playbooks/story-slicing.md
review_focus:
  - scope-control
autonomous: true
---
```

Use a fixed vocabulary when practical. Add tags only when existing tags would
mislead an author or reviewer.

## Readiness Sanity Pass

Before promoting a story from `candidate`, record:

```md
## Readiness Sanity Pass

- Product decision gaps:
- Cross-lane impact:
- Security/privacy risk:
- Verification path:
- Assumptions safe for autonomy:
```

Use `ready` only when there are no material caveats. Use `ready_with_notes` when
assumptions are safe but should remain visible.

## Dependency Policy

Package approvals happen during planning. Authors may install only packages in
`approved_dependencies` or packages already present in the repo. If a new
package is essential, block that story and continue elsewhere.

## Memory Policy

Memory is durable, repo-versioned context that prevents repeated reasoning,
repeated mistakes, or repeated file crawling. It is not a diary, transcript, PR
log, scratchpad, or status journal.

Create memory only when it will save future work. Reviewer or steward may
request memory updates for repeated or high-risk issues.

Authority order:

1. Latest user instruction.
2. Security/privacy policy and branch protection.
3. Current story acceptance criteria.
4. `AGENTS.md` and playbooks.
5. Durable memory.
6. Older PR discussion.

## Blocker Policy

Resolve blockers autonomously when the fix is local, reversible, and testable.
Block only the affected story when continuing would require secrets, destructive
actions, paid services, unclear product/security decisions, or broad cross-lane
churn.

## Work Selection

Choose work in this order:

1. Rejected PRs and deterministic CI failures.
2. Stories that unblock downstream work.
3. Lanes with no open PRs.
4. Lower-risk stories when value is similar.
5. Roadmap order.

