---
name: release-audit
description: Drive a Fatty release from "all stories merged" to a cut tag — the full-system audit, fix loop, test plan, and release prep. Use when the user wants to run the release runbook, do the v1 (or any milestone) audit, check whether the product is release-ready, or "run the audit / test plan". Read-only finder; all fixes route through the normal steward/author/reviewer loop, and the tag/deploy is a human step.
---

# Release Audit

Drive a release end to end from the command centre. This skill **operates the
release runbook** at `docs/release-runbook.md` — that doc is the source of truth
for *what* each phase covers; this skill is *how you run it* with the user.

The whole point is **separation of duties — finder ≠ fixer**. In this skill you
(Claude, with the user) are the **finder**: you audit read-only and produce a fix
plan. You never write product code. Fixes land as scoped stories the planner
writes and the steward/author/reviewer loop merges. The tag/release/deploy is a
human action. If you ever find yourself about to edit a file under `fatty/`, stop
— that's the author's job, not this skill's.

## 0. Ground yourself

Read first so the audit is informed, not generic:

- `docs/release-runbook.md` — the phases, the definition of "release-ready", the
  roles, and the Phase 3 test gate. **Follow it; this skill doesn't restate it.**
- `docs/stories/v1-roadmap.md` — milestone/acceptance checklist and remaining
  story states.
- The `fatty/docs/…` architecture, contracts, standards, and security docs for
  whatever the audit touches. Explore the `fatty/` code directly.

Confirm with the user which release/milestone is being audited (default: v1).

## 1. Gate check — are we even ready to audit?

Per the runbook's "release-ready" definition, the audit is meaningful only once
the feature stories are merged. Check the roadmap and PR state:

```sh
# Any v1 story still open?
grep -nE '\| (ready|ready_with_notes|needs_attention|in_progress) \|' docs/stories/v1-roadmap.md
gh pr list --repo epurn/fatty --state open --json number,title,headRefName,reviewDecision
```

- If feature stories remain → say so and **stop**. The audit waits; offer to
  `triage-prs` instead. Don't audit a half-merged tree.
- If everything's merged → proceed to Phase 1.

(FTY-080 staying `candidate` is expected — that's Phase 4, gated on this audit.)

## 2. Phase 1 — Full-system audit (read-only)

Run the whole-repo deep sweep across the runbook's six dimensions (correctness /
security-privacy / contracts / reuse-smells / tests / docs). This is broader than
per-PR review: drive the real end-to-end flows, not just diffs.

For a thorough sweep, fan out **read-only** `Explore` agents (one per dimension,
in parallel) over `fatty/`, then synthesize — never spin up writers. Keep each
finding concrete: file:line, what's wrong, why it blocks (or doesn't), suggested
fix shape.

**Output: a written fix plan** in command-centre plan mode (use `EnterPlanMode`).
Prioritized findings, each tagged blocking / non-blocking. Nothing is fixed here
— the finder stays read-only. Present the plan and triage it with the user
(accept-as-is decisions get recorded).

## 3. Phase 2 — Fix loop (hand off; never fix here)

For each **approved blocking** finding, the fix is a story, not an edit:

- Use the **`plan-stories`** skill / `planner` subagent to write scoped
  fix-stories. Obey the scope guardrail and the `requires_context`-must-be-
  `fatty/docs` rule. Don't bundle findings into one over-wide story.
- The **steward** assigns them; **authors** fix; the **reviewer** reviews; they
  merge — the normal loop (use `agents-status` / `agents-control` to observe, not
  to merge by hand).
- **Re-audit** the affected areas until the plan is clean. Quality is fixed
  before merge, never re-deferred to yet another follow-up.

## 4. Phase 3 — Test plan (the gate)

Run the runbook's Phase 3 checklist from a clean checkout and report each line
green/red with evidence (don't claim green you didn't see):

- `make verify` (governance + backend + mobile + contracts),
- the security adversarial suite (SSRF / private-IP / metadata / redirect /
  oversize / bad-content-type fail closed; query sanitization; no
  image/prompt/raw-response logging; discard-by-default retention),
- migrations apply **and** roll back on a throwaway DB,
- per-milestone acceptance spot-checks against merged code,
- an end-to-end smoke of log → estimate → edit.

Any red → back to Phase 2. Surface failures with the actual output; never paper
over a skip.

## 5. Phase 4 — Release prep + publish

Only once Phases 1–3 are clean:

1. Tell the user to **promote FTY-080 from `candidate` → `ready`** (it's the
   mechanical release-prep PR; the steward then assigns it). This is a human
   promotion gate on purpose — don't flip it silently.
2. It merges through the normal loop.
3. **The human** cuts the release: `git tag v1.0.0`, GitHub release with the
   CHANGELOG, deploy. Outside agent permissions by design — do not run these.

## Close out

Summarize: what the audit found, what shipped as fix-stories, the test-gate
result, and the single remaining human action (promote FTY-080, then tag). If
this was the first hand-run, note which parts were mechanical enough to fold
deeper into this skill next time.
