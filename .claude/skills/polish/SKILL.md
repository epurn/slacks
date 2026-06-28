---
name: polish
description: Dogfooding-driven design polish for Fatty. The user uses the app and dumps UX feedback (notes + screenshots); each note becomes a fix story, a design-philosophy principle, or both. Large behavioural targets are handed to the planner to decompose into properly-laned, parallelizable stories — never one cross-cutting story. The living design-philosophy doc is updated and is auto-enforced by the author and reviewer. Use when the user wants to run a polish / dogfood / "release-notes" session, give UX feedback, or refine the product's look and feel. Capture and planning only — never implements, reviews, assigns, or operates the agents.
---

# Polish

This is the design workbench. The user dogfoods the app and fires off UX
feedback; you turn that stream into two durable outputs:

1. **Stories** that achieve the behaviour the user wants — appropriately scoped,
   never cross-cutting (see §3).
2. **Design-philosophy principles** that capture the user's sensibilities so the
   same taste is enforced on every future change (see §4).

Hard boundaries: capture and planning only. Never implement, review, assign,
launch authors, or operate the steward/reviewer services. Like `plan-stories`,
you prepare work; the steward picks it up. Keep the public `fatty` repo free of
any private automation detail.

## 1. Ground yourself first

Before a session, read so your triage and recommendations are informed:

- `docs/design-philosophy.md` — the current living philosophy. Everything you
  capture is measured against, and added to, this.
- `docs/stories/README.md` and `docs/stories/v1-roadmap.md` — story format,
  readiness rule, lane vocabulary, and the next free `FTY-###` id.
- The relevant `fatty/` screens/code for whatever the user is dogfooding, so a
  vague "this feels off" can be grounded in what's actually there.

This skill leans on `plan-stories` for the heavy story-writing — read its scope
guardrail (§2a there) so the stories you hand off are sized correctly.

## 2. Capture, then triage each note

The user dogfoods and dumps feedback — short notes, plus **screenshots** (manual
for now; simulator auto-snapshot is a future nice-to-have, don't block on it).
Keep a running session log so nothing is lost while you work.

Triage **every** note into one of three buckets:

- **Fix story** — a concrete, one-off change ("this total is in the wrong
  place"). Becomes a story (directly if tiny, via the planner if it's real work).
- **Principle** — a rule that should generalize beyond this one screen ("nothing
  should take more taps than it needs"). Updates the philosophy doc (§4). A pure
  principle may produce no story at all.
- **Both** — the most valuable case: a specific complaint that is *also* a
  symptom of a deeper rule. File the fix **and** distil the principle.

The distillation — note → principle — is the heart of this skill. Don't let a
recurring complaint stay a pile of one-off fixes; name the rule underneath it.

### Ground evidence-sensitive decisions in research (background, concurrent with the interview)

Fatty's guidance must be science/evidence-backed, not folk wisdom or guesswork (the **Evidence-backed by default** principle in `docs/design-philosophy.md`). When a decision turns on a factual, health, nutritional, or behavioural question where real evidence exists (weigh-in frequency, macro splits, deficit/pace rates, habit formation, etc.), launch background research (the `deep-research` skill or a research subagent) to ground it — concurrently with continuing the interview, never blocking the user. Fold the cited finding into the decision: recommend the evidence-based answer, flag where it overrides intuition, and capture the evidence basis. Reserve research for decisions where being wrong has real cost and evidence can settle it; don't research the obvious, the purely preferential, or what the codebase/docs already answer.

## 3. Turn behavioural targets into stories — never cross-cutting

When a note implies a real behavioural change, **describe the target behaviour**
and hand it to the **planner** subagent (Agent tool, `subagent_type: "planner"`),
which owns decomposition. Do **not** write a single story that spans
frontend + backend + data model.

- The planner breaks a large target into a **laned story DAG**: independent
  slices run in parallel; dependent ones link via `dependencies`. Per the
  pre-v1 clean-break stance (`docs/design-philosophy.md`), the root of the DAG may
  be a **data-model / contract story** that the backend and frontend slices then
  depend on — breaking the schema is allowed when the UX demands it.
- Only the planner reasons about the whole; the steward and author each see one
  tidy, scoped slice. Respect the scope guardrail in `plan-stories` (§2a): if a
  slice breaches the lane/focus/context limits or bundles more than one "big
  rock," it must split further.
- Reserve `FTY-###` ids up front and pass each planner subagent its id and the
  ids it depends on, exactly as `plan-stories` does, so concurrent writes don't
  collide.

## 4. Update the philosophy doc — and occasionally propose

Fold the session's principles into `docs/design-philosophy.md` using the format
in that file (rule + the sensibility behind it + where it applies).

- **Transcribe what the user states.** Their stated sensibilities are authoritative.
- **Occasionally propose.** When several notes cluster around an unstated rule,
  you may propose a principle you infer from them — but **mark it clearly as a
  proposal and get the user's explicit yes before writing it into the doc.** Do
  not invent taste the user hasn't endorsed.
- Keep principles durable and general. A rule that only describes one screen is a
  fix story, not a principle.

This doc is **auto-enforced**: the steward embeds it into every author assignment
and the reviewer checks each PR against it (a violation is a blocking finding →
`REQUEST_CHANGES`). So adding a principle here is the act that makes the taste
stick — there is nothing else to wire.

## 5. Reflect and close out

When the session winds down, summarize back in a few lines: the fix stories
created (with ids and dependency order), the philosophy principles added or
changed, and any proposals still awaiting the user's decision. Stop at promoted,
ready stories and a committed philosophy doc. Do not assign, launch, or operate
anything.
