---
name: design
description: Whole-product / large-UX design for Fatty. Grills the user in depth to resolve a coherent product design — information architecture, the core flows, screen inventory, interaction & visual direction — captured as a UX design doc in fatty/docs, seeding the living design-philosophy. Resolves the WHOLE design before any slicing, then hands story-decomposition to plan-stories. Use when designing the product (or a large part of it) from the ground up, redesigning the UX, or when the screens are scaffolding that was never deliberately designed. Design & planning only — never implements, reviews, assigns, or operates the agents.
---

# Design

This is the design workbench — for resolving the **coherent whole** before any
single feature is sliced into stories. It sits above the other two planning
skills:

- **`design`** (this skill): whole-product / large-UX design → a UX design doc +
  seeded philosophy → then hands decomposition to `plan-stories`.
- **`plan-stories`**: one feature/idea → well-sized stories (or decomposes an
  already-resolved design into a story tranche).
- **`polish`**: dogfooding an *already-designed* product → fix stories + refined
  philosophy.

Reach for `design` when there is no intentional design yet (scaffolding), when
the UX is being rebuilt, or when the work is too big and cross-cutting to grill
straight into stories — you need the shape of the whole before the parts.

Hard boundaries: design & planning only. Never implement, review, assign, launch
authors, or operate the steward/reviewer services. You produce a design and the
stories that flow from it; the author builds, the steward routes.

_Interview style adapted from Matt Pocock's `grill-me`._

## 1. Ground yourself first

Before asking anything, build a real picture so questions are informed, not
generic. Resolve from the codebase/docs whenever you can — never interrogate the
user for what the repo can answer.

- `docs/design-philosophy.md` (command centre) — the living taste. Every design
  decision is measured against, and may add to, this.
- The product vision: `fatty/AGENTS.md`, `fatty/README.md`,
  `fatty/docs/architecture/system-overview.md`, and the ADRs under
  `fatty/docs/adr/`. Know the core value loop and target user cold.
- The current state: what screens/flows exist today and what they actually do
  (read the components), plus the **data model / contracts** the UX sits on
  (`fatty/docs/contracts/…`) — the design must respect what data exists, or
  consciously decide to change it.
- `docs/stories/v1-roadmap.md` — what's built and the lane vocabulary, so the
  eventual decomposition is grounded.

**Pre-v1, no users → clean-break is allowed.** Per `docs/design-philosophy.md`,
you are free to redesign or replace scaffolding, break behaviour, and change the
data model/contracts when the right design demands it. Do not default to
preserving what exists — design what's *right*, then let the decomposition carry
the breaking changes (a contract/data-model story rooting the DAG).

## 2. Grill deep — resolve the whole before any slice

Walk the design tree top-down, one question at a time. **Go in depth and do NOT
wrap early** — exhaust each layer and the branches it opens before moving on;
default to *more* questions, not fewer. The only stop conditions are: the user
says stop, or you genuinely have a complete, unambiguous design. When in doubt,
ask the next question.

- **One question at a time.** Wait for the answer before the next.
- **Recommend an answer to every question** — your best call with a one-line
  why, grounded in the vision and what exists. Use AskUserQuestion for discrete
  choices (recommendation first); prose for open-ended ones.
- **Resolve the whole, top-down, before slicing.** Unlike `plan-stories`, do
  **not** write stories as you go — a story written mid-design locks a decision
  before the whole is coherent. Hold the slicing until §5.

Design tree to descend (each layer depends on the ones above it):

1. **Product frame** — who it's for, the core value loop, what makes it
   different. Confirm against the vision; don't re-derive from scratch.
2. **Information architecture & navigation** — the top-level surfaces and how the
   user moves between them (tabs? stack? a single home?). The skeleton everything
   else hangs on.
3. **Core flow(s), end-to-end** — the primary daily loop step by step (for Fatty:
   launch → log → see your day → correct → adjust), including every state along
   the way.
4. **Screen inventory** — each surface's single job, its content hierarchy, and
   its one primary action. What earns a screen; what's a component.
5. **Interaction & input model** — how the signature interactions work (e.g. NL
   logging, in-place correction, evidence/source display, optimistic pending).
6. **Visual & tone direction** — layout density, type/spacing feel, colour &
   affordance language, motion. Enough that screens will feel like one product.
7. **States & edges** — empty / loading / error / pending / needs-clarification /
   offline, per surface. Designs die in their edge states; grill them.
8. **Cross-cutting** — accessibility, iPhone responsiveness, performance feel,
   privacy-visible behaviour.

## 3. Capture the design as a durable artifact

**Capture in the background — never stall the interview.** The moment a decision
resolves, capture it *concurrently* with asking the next question: in the same
turn, dispatch a background subagent to append the decision to the design doc (or
a running decisions log) AND fire the next question, then move straight on. The
user must never wait on a write between questions — question cadence is the
priority; collect the background writes as they land. (This is *decision* capture;
story decomposition still waits for the whole design, §5.)

As layers resolve, write them into a **UX design doc under
`fatty/docs/design/`** (product documentation — it belongs in the public repo and
becomes the `requires_context` anchor every UX story points at). Structure it to
mirror the design tree: product frame → IA/nav → core flows → screen inventory →
interaction model → visual/tone → states → cross-cutting. Keep it the single
source of truth for "what the product is"; it must be specific enough that a
story can implement a slice of it without re-deciding the design.

Because stories reference this doc via `requires_context` (which must resolve in
the author's `fatty` worktree), the doc has to land on `fatty` `main` before
those stories run — either committed as part of this design work (it's product
docs, not private automation) or as the root story of the tranche. Decide that
with the user at §5.

## 3a. Ground evidence-sensitive decisions in research (background, concurrent with the interview)

Fatty's guidance must be science/evidence-backed, not folk wisdom or guesswork (see the **Evidence-backed by default** principle in `docs/design-philosophy.md`). So when a design decision turns on a factual, health, nutritional, or behavioural question where real evidence exists — weigh-in frequency, macro splits, deficit/pace rates, habit formation, portion psychology, and the like — **launch background research to ground it**, concurrently with continuing the grill. Never make the user wait on it.

- Kick off the research (the `deep-research` skill, or a research subagent) in the background the moment such a question surfaces, then carry on interviewing on other branches — same concurrency discipline as background decision-capture.
- When it returns, fold the cited finding into the decision: recommend the evidence-based answer, and flag explicitly where the evidence overrides the user's (or your own) intuition. Capture the evidence basis in the design doc and, where it generalizes, as a philosophy principle.
- Reserve it for decisions where being wrong has a real cost and evidence can actually settle it. Do **not** research the obvious, the purely preferential (aesthetics, naming, tab order), or anything the codebase/docs already answer.

## 4. Seed the design philosophy

A design session is the richest source of durable principles. When a decision
expresses a rule that should generalize ("nothing should take more taps than it
needs", "every number shows where it came from"), fold it into
`docs/design-philosophy.md` using that file's format (rule + the sensibility
behind it + where it applies). Transcribe what the user states; you may
**propose** an inferred principle from a cluster of decisions, but only write it
after the user's explicit yes. This is what makes the taste auto-enforced (the
steward embeds the philosophy into author assignments; the reviewer checks
against it).

## 5. Hand decomposition to plan-stories

Only once the design is resolved and captured: switch to **`plan-stories`** to
slice it into a story tranche. Reserve `FTY-###` ids up front. Each story
implements **one boundary** (a single serializing code lane) of the design doc,
references it in `requires_context`, and links dependencies so the tranche has a
sane build order — a feature becomes a DAG of boundary stories joined by a
contract, never one cross-lane story (per the clean-break stance, a
contract/data-model story typically roots the DAG). Honor
`plan-stories`' scope guardrail (§2a there) — slices that breach the
lane/focus/context limits or bundle big rocks split further. `design` decides
*what the product is*; `plan-stories` decides *how it's cut into buildable work*.

## 6. Reflect and close out

When every layer is resolved and the in-flight writes have returned, summarize:
the design decisions, the UX design doc written, the philosophy principles added,
and the planned story tranche (breakdown + dependency order). Confirm with the
user. Stop at a captured design and ready/queued stories — do not assign, launch,
or operate anything.
