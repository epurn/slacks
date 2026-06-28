# Stories

Stories define user-visible or system-visible outcomes.

Prefer GitHub issues for active stories. This directory can hold longer story specs when an issue is too small for architectural detail.

Use `v1-roadmap.md` as the ordered v1 story map.

## Scope guardrail

One story = one author run = **one boundary**: the code work in a single
serializing lane (backend-core, mobile-core, estimator, contracts, infra,
governance) an author can finish and open a PR for within its turn budget. A
user-visible feature is delivered by a small DAG of boundary stories joined by an
explicit contract — **never one story that spans lanes** (this is why the roadmap
splits e.g. backend FTY-030 from mobile FTY-031, and weight into 070-backend +
074-mobile). Lanes serialize code ownership, so single-boundary stories run in
parallel and stay convergent. An over-scoped story does not ship — the author runs
out of turns flailing and the run fails with no PR (see FTY-061). **Size is a
correctness requirement, not a preference.**

Split — regardless of counts — when a story **crosses a boundary**: it does code
work in more than one serializing lane, or it bundles more than one **big rock** —
a public contract change (provider/API/DTO/job/estimator boundary), a schema
migration that adds a table, or a new untrusted-input trust boundary (vision/image,
fetched pages, OCR, uploads). Pull each second lane / big rock into its own
boundary story; dependents depend on it and stay small. The non-serializing lanes
(security-privacy, docs) ride along and don't count as a second boundary.

Also split when it breaches **two or more** size limits:

| Field | Ceiling | Split signal |
| --- | --- | --- |
| `review_focus` | 5 | ≥ 6 concerns |
| `requires_context` | 8 | ≥ 9 docs |

Record the sizing decision in the Readiness Sanity Pass when a story sits near a limit.

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
