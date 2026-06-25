---
name: grill-me
description: Interview the user relentlessly about a feature, change, or design until you reach shared understanding, then turn the resolved plan into a ready Fatty story. Use when the user wants to plan something, stress-test an idea, "get grilled", or work an idea up into a story. This is the front door to planning; it ends in story creation.
---

# Grill Me → Story

Interview the user relentlessly about every aspect of the plan until you reach a
shared understanding, then capture the result as a ready Fatty story. This is the
planning role only — never implement, review, assign, or operate services.

_Adapted from Matt Pocock's `grill-me` skill._

## 1. Ground yourself first

Before asking anything, read so your questions and recommendations are informed:

- `fatty/docs/stories/README.md` — story format and the readiness rule.
- `fatty/docs/stories/v1-roadmap.md` — roadmap, ordering, and lane vocabulary.
- The product/architecture/contract/standards/security docs the idea touches.
- **Explore the `fatty/` codebase.** If a question can be answered by reading the
  code, explore the code instead of asking the user.

## 2. Grill, one question at a time

Walk down each branch of the design tree, resolving dependencies between
decisions one-by-one. Rules:

- **Ask exactly one question at a time.** Wait for the answer before the next.
- **Recommend an answer to every question** — your best call, with a one-line
  why. Use the AskUserQuestion tool when the choice is discrete (put your
  recommendation first); ask in prose when it's open-ended.
- **Explore before asking.** Anything the codebase, docs, or roadmap can answer,
  you answer yourself and confirm rather than interrogate.
- **Be relentless but convergent** — keep going until the open branches are
  resolved, not forever.

Cover the decisions a ready story needs:

- outcome and the single vertical slice in scope; explicit non-goals,
- primary lane and touched lanes; story dependencies (what must merge first),
- contracts touched (API, DB, job, estimator, provider, DTO boundaries),
- security and privacy impact; what untrusted input is involved,
- acceptance criteria and the verification commands,
- risk tier (low/medium/high — estimate big when unsure; this drives model
  choice: haiku/sonnet/opus),
- whether it is safe to run autonomously, or needs a human decision first.

## 3. Reflect the shared understanding

When the tree is resolved, summarize the decisions back in a few lines and get a
final confirmation that you've got it right.

## 4. Turn it into a story

Hand off to story creation — delegate to the **planner** subagent (Agent tool,
`subagent_type: "planner"`) so the role boundary holds, passing the resolved
decisions. The planner writes a ready story under `fatty/docs/stories/` using the
template in the stories README. (The `plan-story` skill is the same handoff if
you prefer to drive it directly.)

Stop at a promoted, ready story. Do **not** assign it, launch an author, or touch
the steward/reviewer services — the steward picks up ready stories on its own.
Keep `fatty` free of any private automation detail; stories describe product work
only.
