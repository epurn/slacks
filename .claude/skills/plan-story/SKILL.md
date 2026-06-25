---
name: plan-story
description: Create, refine, or promote a Fatty story. Use when the user wants to turn an idea, bug, or roadmap item into a ready, well-scoped story for the steward to assign, or to refine/promote an existing story. Planning only — never implements, reviews, or runs the agents.
---

# Plan Story

This skill drives the **planner** role. It produces ready stories; it never
implements, reviews, assigns, or operates services.

For an interactive session, start with the **`grill-me`** skill — it interviews
you to resolve the design, then hands off here to write the story. Use
`plan-story` directly when you already know what the story should be.

## Steps

1. **Read context first.**
   - `fatty/docs/stories/README.md` — story format + readiness rule.
   - `fatty/docs/stories/v1-roadmap.md` — roadmap and lane vocabulary.
   - Any ADR / architecture / contract / standards doc the work touches.

2. **Delegate to the planner subagent** for the actual drafting, so the role
   boundary is enforced. Use the Agent tool with `subagent_type: "planner"` and
   pass the idea/bug plus the context you gathered. (If working inline instead,
   follow the same boundaries: planning only.)

3. **Write the story** as a markdown file under `fatty/docs/stories/`, matching
   the existing format. A ready story has: one small vertical slice, named
   lane(s) and dependencies, referenced docs, explicit acceptance criteria and
   verification commands, security/privacy/testing notes, and a risk estimate
   (low/medium/high — estimate big when unsure). Split oversized work into
   dependent stories.

4. **Stop at promotion.** Summarize the story and whether it is ready. Do **not**
   assign it, launch an author, or touch the steward/reviewer services — that is
   the user's call, and the steward picks up ready stories on its own.

## Boundaries

- No private automation details in `fatty` (it is public): product work only.
- The planner does not implement or review the work it plans.
