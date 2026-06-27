---
name: plan-stories
description: The single planning entry point for Fatty. Interview the user one question at a time to resolve a rough idea into one or more ready stories, exploring the codebase instead of asking whenever possible, then write the story files. Use whenever the user wants to plan, shape, scope, or "get grilled on" a feature/change/idea, or turn an idea into stories for the steward to assign. Planning only — never implements, reviews, assigns, or operates the agents.
---

# Plan Stories

This is the planner's workbench. You interview the user until the design is
resolved, then turn the result into one or more ready Fatty stories. One grilling
session may produce a single story or a set of dependent stories when the work is
too big for one vertical slice — hence "stories".

Hard boundaries: planning only. Never implement, review, assign, launch authors,
or operate the steward/reviewer services — the steward picks up ready stories on
its own. Keep `fatty` free of any private automation detail; stories describe
product work only.

_Interview style adapted from Matt Pocock's `grill-me`._

Stories live in **this command-centre repo** under `docs/stories/` — not in the
public `fatty` app repo. The steward reads the roadmap from here and embeds each
story spec into the author's assignment, so product code never ships story files.
Product code, contracts, architecture, standards, and security docs still live in
`fatty/docs/…`; read those there, but write stories here.

## 1. Ground yourself first

Before asking anything, read so your questions and recommendations are informed:

- `docs/stories/README.md` — story format, the template, and the readiness
  rule (including the Readiness Sanity Pass).
- `docs/stories/v1-roadmap.md` — roadmap, ordering, and the lane vocabulary.
- The architecture / contract / standards / security docs the idea touches
  (under `fatty/docs/…`).
- **Explore the `fatty/` codebase.** Anything the code, docs, or roadmap can
  answer, you answer yourself and confirm — do not interrogate the user for it.

Note the next free story id by scanning existing `docs/stories/FTY-###` stories
and the roadmap.

## 2. Grill, one question at a time

Walk down each branch of the design tree, resolving dependencies between
decisions one-by-one until you reach shared understanding. Rules:

- **One question at a time.** Wait for the answer before the next.
- **Recommend an answer to every question** — your best call with a one-line
  why. Use the AskUserQuestion tool when the choice is discrete (put your
  recommendation first); ask in prose when it's open-ended.
- **Explore before asking.** Resolve from the codebase/docs whenever you can.
- **Relentless but convergent** — stop when the open branches are resolved.
- **Watch the scope.** If it won't fit one vertical slice, plan to split it into
  several dependent stories and grill each slice's boundary.
- **Write in the background, never stop grilling.** As soon as one slice's design
  is fully resolved, dispatch its planner subagent to write that story (see §4)
  and immediately continue interviewing on the next slice or open branch while it
  works. The user should never be left waiting on a write — keep asking questions
  the whole time. Collect the subagents' results as they finish.

Resolve everything a ready story needs — these map directly to the template:

- **outcome** — the user- or system-visible result.
- **scope** — the single vertical slice; **non-goals** — what's explicitly out.
- **primary_lane** + **touched_lanes** — from the roadmap's lane vocabulary.
- **dependencies / approved_dependencies** — which stories must merge first; any
  new dependency the author is allowed to add.
- **contracts** — API, DB, job, estimator, provider, or mobile/backend DTO
  boundaries touched (these need explicit contracts).
- **security / privacy** — data touched, retention, and what untrusted input is
  involved (LLM output, fetched pages, OCR, prompts, tool output).
- **acceptance criteria** + **verification** commands.
- **risk** — low/medium/high. Estimate big when unsure. This drives the model the
  author/reviewer use: low→haiku, medium→sonnet, high→opus. Anything touching
  auth, privacy, contracts, estimator, migrations, CI gates, or branch
  protection is high.
- **autonomous** — is this safe to hand to an autonomous author as-is, or does it
  need a human product decision first? If it needs a decision, that's a blocker
  to resolve now or a reason to mark the story `ready_with_notes`/`candidate`.
- **review_focus**, **tags**, **requires_context** as relevant.

## 3. Write each story as its design resolves

Don't wait for the whole session to finish. The moment a slice's design tree is
resolved, hand that slice off to the **planner** subagent (Agent tool,
`subagent_type: "planner"`) and keep interviewing on the next slice while it
writes. Dispatch one subagent per story so several can write concurrently. Pass
each subagent the resolved decisions for its slice, and have it write the story
under `docs/stories/` in this command-centre repo (not `fatty/`) using the
template and YAML front matter from the stories README, with:

- the assigned `FTY-###` id(s) and correct dependency links between split stories,
- a completed **Readiness Sanity Pass** (product-decision gaps, cross-lane
  impact, security/privacy risk, verification path, assumptions safe for
  autonomy),
- `state: ready` when it passes cleanly, `ready_with_notes` if it's ready but
  carries caveats, or `candidate` if an open product decision remains.

Reserve `FTY-###` ids up front so concurrent subagents don't collide, and pass
each subagent its assigned id and the ids of the stories it depends on.

## 4. Reflect and close out

When every branch is resolved and the in-flight subagents have returned, summarize
the decisions and the written stories (and, if splitting, the breakdown and
dependency order) back in a few lines and confirm.

Stop at promoted, ready stories. Do not assign, launch, or operate anything.
