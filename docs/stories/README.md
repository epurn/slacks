# Stories

Stories define user-visible or system-visible outcomes.

Prefer GitHub issues for active stories. This directory can hold longer story specs when an issue is too small for architectural detail.

Use `v1-roadmap.md` as the ordered v1 story map.

## Scope guardrail

One story = one author run = one vertical slice an author can finish and open a
PR for within its turn budget. An over-scoped story does not ship — the author
runs out of turns flailing and the run fails with no PR (see FTY-061, which
churned through several failed runs before being split). **Size is a correctness
requirement, not a preference.**

Split a single story into dependent stories when it breaches **two or more** of:

| Field | Ceiling | Split signal |
| --- | --- | --- |
| `touched_lanes` (beyond primary) | 2 | ≥ 3 lanes |
| `review_focus` | 5 | ≥ 6 concerns |
| `requires_context` | 8 | ≥ 9 docs |

Also split — regardless of counts — when one story bundles more than one **big
rock**: a public contract change (provider/API/DTO/job/estimator boundary), a
schema migration that adds a table, or a new untrusted-input trust boundary
(vision/image, fetched pages, OCR, uploads). Pull each big rock into its own
prerequisite story; the feature logic depends on them and stays small. Record
the sizing decision in the Readiness Sanity Pass when a story sits near a limit.

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
