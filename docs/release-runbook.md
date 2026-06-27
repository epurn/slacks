# Release Runbook — Fatty v1

How we take Fatty from "all roadmap stories merged" to a cut release. This is a
command-centre process doc (it describes how we *operate* a release, not product
code). **Manual for now** — the human drives it from the command centre, with
Claude; crystallize into a skill only after running it by hand a few times.

The mechanical tail of this runbook is the author story **FTY-080 (v1 release
prep)**, which is gated behind every other v1 story. The runbook is the larger
process that must be clean *before* FTY-080's PR is cut.

## Definition of "release-ready"

All of these hold:

1. Every v1 roadmap story is **merged** (no `ready` / `needs_attention` left).
2. A **full-system audit** has run and its findings are all either fixed or
   explicitly accepted (see Phase 2).
3. The **test plan** (Phase 3) is green end to end.
4. The **release-prep PR** (FTY-080) is merged: consistent `v1.0.0`, accurate
   CHANGELOG, README matches reality, full `make verify` green, boundary check
   green.

Only then does a human cut the tag + GitHub release + deploy.

## Roles (separation of duties — finder ≠ fixer)

- **Reviewer / Claude (read-only)** — *finds*. Runs the full-system audit and
  per-PR review. Never writes repo files; runs tests/builds/sim when judgment
  warrants (`FATTY_REVIEWER_ALLOW_TOOLS=1`).
- **Planner** — turns approved audit findings into scoped fix-stories.
- **Steward** — assigns the fix-stories and routes PR fixes (the normal loop).
- **Author** — *fixes*. Implements the fix-stories and `fix-pr` work.
- **Human (you) + Claude in the command centre** — drive the audit, approve the
  fix plan, and cut the actual release. (Manual for now.)

Routine quality is **never deferred to follow-up stories**: the reviewer requests
changes, the steward routes a `fix-pr`, the author fixes it before merge. The
audit below is the *additional* whole-repo deep sweep, not a substitute for that.

## Phase 1 — Full-system audit (reviewer-owned, read-only)

A deliberately strict, whole-repo deep sweep — broader than per-PR review.
Dimensions:

- **Correctness / full-system functional** — does the end-to-end product work:
  account/profile → log event → estimator (text/barcode/label/official-source) →
  edit/saved-foods → weight + daily summary. Drive the real flows.
- **Security / privacy** — the heaviest lane. Untrusted-input boundaries (LLM
  output, fetched pages, OCR, uploads), SSRF/egress, secret handling, data
  minimization, retention (discard-by-default), the public-repo boundary. This
  overlaps and depends on **FTY-073 (security pass)**.
- **Contracts** — every API/DTO/job/provider/estimator boundary has a current
  `docs/contracts/*` spec and matching tests; no silent drift.
- **Code reuse / smells / maintainability** — duplication, dead code, leaky
  abstractions, inconsistent patterns across `backend/`, `mobile/`, `contracts/`.
- **Tests** — coverage of the critical paths; adversarial/negative suites exist
  for the security boundaries; no untested new behavior.
- **Docs** — `docs/architecture`, `docs/standards`, `docs/security`,
  `docs/contracts` match the shipped code; README + `.env.example` are accurate.

Output: a written **fix plan** (prioritized findings), produced in command-centre
plan mode. Nothing is fixed in this phase — finder stays read-only.

## Phase 2 — Fix loop

1. Triage the fix plan with the human; drop or accept non-blocking items
   (record accepted-as-is decisions).
2. Approved blocking items → **scoped fix-stories** (planner), obeying the scope
   guardrail and the `requires_context`-must-be-`fatty/docs` rule.
3. The steward assigns them; authors fix; the reviewer reviews; they merge — the
   normal loop. Quality issues are fixed before merge, never re-deferred.
4. **Re-audit** the affected areas until the plan is clean.

## Phase 3 — Test plan (the gate)

Green across the board, from a clean checkout:

- `make verify` (root) = governance + each package's `verify.sh`:
  - **backend**: `uv run ruff check . && ruff format --check . && mypy && pytest`
  - **mobile**: `npm run typecheck && npm run lint && npm test`
  - **governance**: `scripts/verify-governance.py` (public-repo boundary, required
    files, no forbidden paths)
- **Security adversarial suite** (from FTY-073 and the estimator stories): SSRF /
  private-IP / metadata / redirect-to-private / oversize / bad-content-type all
  fail closed; query sanitization (no personal context egresses); no
  image/prompt/raw-response logging; discard-by-default attachment retention.
- **Migrations** apply and roll back cleanly against a throwaway DB.
- **Per-milestone acceptance** — spot-check each milestone's acceptance criteria
  against the merged code (the roadmap's Acceptance column is the checklist).
- **Smoke** — a real end-to-end run of the core logging → estimate → edit flow.

## Phase 4 — Release prep + publish

1. **FTY-080** (author): version → `v1.0.0` everywhere, CHANGELOG by milestone,
   README final pass, full `make verify` green. Stops at the release-ready PR.
2. Reviewer approves, it merges.
3. **Human** cuts the release: `git tag v1.0.0`, GitHub release with the
   CHANGELOG, deploy. (Outside author/agent permissions by design.)

## Status

Manual, but driven by the **`release-audit` skill** (`.claude/skills/release-audit/`)
— it walks these phases with the human. The human still runs Phase 1–2 in
command-centre plan mode; the steward/author/reviewer loop does the fixes; FTY-080
is the only automated piece. Tighten the skill (fold in more of the mechanical
checks) after the first full hand-run.
