---
name: plan-stories
description: The single planning entry point for Fatty. Interview the user one question at a time to resolve a rough idea into one or more ready stories, exploring the codebase instead of asking whenever possible, then write the story files. Use whenever the user wants to plan, shape, scope, or "get grilled on" a feature/change/idea, or turn an idea into stories for the steward to assign. Planning only — never implements, reviews, assigns, or operates the agents.
---

# Plan Stories

This is the planner's workbench. You interview the user until the design is
resolved, then turn the result into one or more ready Fatty stories. One grilling
session may produce a single story or a set of dependent stories when the work
spans more than one boundary — hence "stories".

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

This is the **story** workbench — one feature/idea, or decomposing an
already-resolved design, into well-sized boundary stories. Whole-product or large
UX *design* belongs in the `design` skill first (it produces the UX design doc you
then slice); dogfooding an already-designed product belongs in `polish`. Fatty is
pre-v1 with no users, so per `docs/design-philosophy.md` you may write stories that
break behaviour, schemas, or contracts when that's the right call — don't default
to additive-only.

## 1. Ground yourself first

Before asking anything, read so your questions and recommendations are informed:

- `docs/stories/README.md` — story format, the template, and the readiness
  rule (including the Readiness Sanity Pass).
- `docs/stories/v1-roadmap.md` — roadmap, ordering, and the lane vocabulary.
- The architecture / contract / standards / security docs the idea touches
  (under `fatty/docs/…`), plus any UX design doc under `fatty/docs/design/` the
  idea implements.
- `docs/design-philosophy.md` (command centre) — the living taste your stories
  must honor (the author and reviewer enforce it). When a decision expresses a
  durable principle, note it for that doc.
- **Explore the `fatty/` codebase.** Anything the code, docs, or roadmap can
  answer, you answer yourself and confirm — do not interrogate the user for it.

Note the next free story id by scanning existing `docs/stories/FTY-###` stories
and the roadmap.

**Lane vocabulary** (a story's `primary_lane` + `touched_lanes`). Lanes serialize
concurrent *code* ownership, so pick the lane(s) where the story's **code** lives:

- `backend-core` — FastAPI backend (`backend/`)
- `mobile-core` — Expo/RN app (`mobile/`)
- `estimator` — estimation pipeline / calculators / LLM providers (any `estimator` path)
- `contracts` — shared contract code/schemas (`contracts/`, `packages/contracts/`)
- `infra` — Docker/compose/deploy (`infra/`, compose files)
- `governance` — CI, scripts, repo meta/process config

Two lanes are **non-serializing** (cross-cutting; they never block other work, so
declaring them costs nothing but they aren't the "real" lane): `security-privacy`
(a review concern — its code is in backend-core/estimator) and `docs` (shared
spec/standards text). A story's real serializing lane is always a code lane above.

## 2. Grill, one question at a time

Walk down each branch of the design tree, resolving dependencies between
decisions one-by-one until you reach shared understanding. Rules:

- **One question at a time.** Wait for the answer before the next.
- **Recommend an answer to every question** — your best call with a one-line
  why. Use the AskUserQuestion tool when the choice is discrete (put your
  recommendation first); ask in prose when it's open-ended.
- **Explore before asking.** Resolve from the codebase/docs whenever you can.
- **Relentless and deep — do NOT wrap early.** Go in depth: exhaust each branch
  and the sub-branches it opens before moving on. Default to *more* questions, not
  fewer; a session that ends after only a few questions is too light. The only
  stop conditions are: the user explicitly says stop, or you genuinely have a
  clear, complete, unambiguous understanding — NOT merely "enough to write a
  story." When in doubt, ask the next question.
- **Watch the scope — enforce the guardrail in §2a.** A story is **one boundary**
  (one serializing code lane). If the work spans more than one code lane, split it
  into dependent per-boundary stories joined by a contract and grill each boundary.
  Over-scoped stories don't get built — the author runs out of turns flailing and
  the run fails; size is a correctness requirement, not a nicety.
- **Write in the background, never stop grilling.** As soon as one slice's design
  is fully resolved, dispatch its planner subagent to write that story (see §4)
  and immediately continue interviewing on the next slice or open branch while it
  works. The user should never be left waiting on a write — keep asking questions
  the whole time. Collect the subagents' results as they finish.

### Ground evidence-sensitive decisions in research (background, concurrent with the interview)

Fatty's guidance must be science/evidence-backed, not folk wisdom or guesswork (the **Evidence-backed by default** principle in `docs/design-philosophy.md`). When a planning decision turns on a factual, health, nutritional, or behavioural question where real evidence exists (e.g. weigh-in frequency, macro splits, deficit/pace rates, habit formation), launch background research (the `deep-research` skill or a research subagent) to ground it — concurrently with continuing the interview, never blocking the user. Fold the cited finding back into the decision: recommend the evidence-based answer, flag where it overrides intuition, and record the evidence basis in the story. Reserve research for decisions where being wrong has real cost and evidence can settle it; don't research the obvious, the purely preferential, or what the codebase/docs already answer.

### 2a. Scope guardrail (hard split rules)

One story = one author run = **one boundary**: the code work in a single
serializing lane (backend-core, mobile-core, estimator, contracts, infra,
governance) an author can finish and open a PR for in a bounded number of turns.
A user-visible feature is delivered by a small DAG of boundary stories joined by
an explicit contract — **never one story that spans lanes**. This isn't only
sizing: lanes serialize code ownership, so single-boundary stories run in parallel
across lanes, stay convergent, and force the contract at the seam to be explicit.
A too-wide story never converges — the author burns its turn budget and the run
fails with no PR. So size every story against the rules below.

**A story MUST be split if it breaches two or more of:**

- **review_focus ≥ 6** distinct concerns. Five is the ceiling; six means too
  many independent things to get right at once.
- **requires_context ≥ 9** docs. Eight is the ceiling; more and the author
  can't hold the spec plus its context in one run.

**A story MUST be split (regardless of counts) when it crosses a boundary —
spans more than one code lane, or bundles more than one of these "big rocks"
(each is its own boundary story):**

- **more than one serializing code lane** — keep the code in one lane; pull any
  second code lane into its own boundary story behind a contract. The
  non-serializing lanes (security-privacy, docs) ride along and don't count.
- a **public contract change** (API/provider/DTO/job/estimator boundary, e.g. a
  `…-provider` version bump),
- a **schema/DB migration** that introduces a new table,
- a **new untrusted-input trust boundary** (LLM vision/image, fetched pages,
  OCR, uploaded files) with its own validation + retention + egress rules.

Canonical decomposition: pull the **contract change** into its own prerequisite
story, the **migration/new table + its retention/security rules** into a second,
and have the **feature logic** depend on both. The dependent story stays small
because the hard parts are already contracted upstream.

These are limits, not targets: most stories should sit well under them. When a
story is near a limit, prefer splitting and grill each slice's boundary. A
genuinely cohesive slice that lands on one limit and nothing else can ship — but
say why in the Readiness Sanity Pass.

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
- **review_focus**, **tags**, **requires_context** as relevant. `requires_context`
  must list **only docs that exist in the author's `fatty` worktree** — i.e.
  public `fatty/docs/...` paths (architecture, standards, contracts, security).
  Never list command-centre-only paths like `docs/stories/...`: the author builds
  from `fatty` origin/main and can't see them (it already gets the full spec
  embedded), so a `docs/stories/*` entry is a dead pointer that makes the run
  hunt for a missing file.

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
