# Stories

Stories define user-visible or system-visible outcomes.

Prefer GitHub issues for active stories. This directory can hold longer story specs when an issue is too small for architectural detail.

Use `v1-roadmap.md` as the ordered v1 story map.

Every story should include:

- YAML front matter when state is `ready` or `ready_with_notes`,
- outcome,
- scope,
- non-goals,
- lane,
- dependencies,
- contracts touched,
- security/privacy impact,
- acceptance criteria,
- verification plan.
- readiness sanity pass before promotion from `candidate`.

## Story Template

```md
---
id: FTY-000
state: ready
primary_lane: governance
touched_lanes: []
risk: low
tags: []
approved_dependencies: []
requires_context: []
review_focus: []
autonomous: true
---

# FTY-000: Title

## State

ready

## Lane

governance

## Dependencies

- FTY-000

## Outcome

## Scope

## Non-Goals

## Contracts

## Security / Privacy

## Acceptance Criteria

## Verification

## Readiness Sanity Pass

- Product decision gaps:
- Cross-lane impact:
- Security/privacy risk:
- Verification path:
- Assumptions safe for autonomy:
```
