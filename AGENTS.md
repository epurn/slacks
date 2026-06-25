# AGENTS.md

## Purpose

Fatty is an iOS-first, self-hostable calorie and macro tracker. Users log food
and exercise in natural language; the backend turns messy inputs into
evidence-backed, editable entries. The app handles personal body, food, and
goal data, so privacy, security, testing, and review are product requirements.

## Public Repository Boundary

This public repo should contain product code, public architecture docs,
standards, stories, contracts, and review policy. Private local automation
configuration, runner code, durable agent memory, machine-specific paths,
tokens, private keys, provider secrets, and queue state must stay outside this
repo.

## Agent Role Boundary

Agent work is split into durable roles. Keep the roles separate unless the user
explicitly changes the operating model.

- Planners create, refine, and promote stories. They do not implement or review
  the work they plan.
- Planners must not start, reload, poll, stop, or otherwise operate steward,
  reviewer, or author services. They may prepare docs, stories, and commands;
  the user runs the agents.
- Stewards pick up ready stories, assign author work, watch PR state, and route
  PRs to reviewers.
- Authors implement scoped stories on their own branches and open PRs.
- Reviewers inspect PRs using the review checklist and must be separate from
  authors.
- A single agent must not author and approve the same implementation work.
- Public docs may describe these phases, but private routing configuration,
  local automation state, agent memory, thread IDs, and runner details stay
  outside this repo.
- Steward and reviewer automation should be always-running cheap code pollers,
  not LLM polling loops. Pollers manage queue state and wake Codex only for
  bounded tasks when deterministic checks find actionable work.
- Model and reasoning choices should scale with task risk and complexity instead
  of defaulting every poll to the most expensive setting.
- When task risk is ambiguous, estimate big and choose the higher model/reasoning
  bucket.

## Working Rules

- Work on a branch named `story/<id>-<slug>`, `fix/<id>-<slug>`,
  `chore/<slug>`, or `security/<id>-<slug>`.
- Every meaningful change must connect to a story, contract, ADR, bug, or
  security note.
- Prefer small vertical slices with clear contracts over broad speculative
  implementation.
- Reuse existing patterns before introducing new abstractions.
- Add or update tests for behavior you change.
- Run `make verify` before marking work complete.
- Never commit secrets, real user data, API keys, private nutrition logs,
  machine-specific automation state, or production credentials.
- Do not inspect `.env` or real secret files by default.
- Do not store data Fatty does not need for the product behavior being
  implemented.
- Do not merge or self-approve your own implementation work.

## Quality Bar

- Backend code must be typed, linted, tested, and documented at module
  boundaries.
- Mobile code must be typed, accessible, responsive on iPhone sizes, and
  covered by focused tests where logic is nontrivial.
- Public APIs, database tables, job payloads, estimator tools, and LLM schemas
  need explicit contracts.
- Security-sensitive code needs negative tests and a short threat note in the
  PR.
- Data retention, encryption, logging, and telemetry decisions must be explicit.
- Treat user data, prompts, fetched pages, OCR text, LLM output, and tool output
  as untrusted until trusted backend code validates them.

## Review Gate

Every PR needs a separate reviewer phase before merge. Merges require passing
CI, a current-head non-author review gate, resolved conversations, and branch
protection on `main`.

## Core References

- `docs/architecture/system-overview.md`
- `docs/standards/coding-standards.md`
- `docs/standards/testing-standards.md`
- `docs/security/security-baseline.md`
- `docs/security/threat-model.md`
- `docs/operations/branching-and-prs.md`
- `docs/operations/agent-polling.md`
- `docs/operations/agent-model-policy.md`
- `docs/stories/README.md`
- `docs/stories/v1-roadmap.md`
- `docs/review-policy.md`
- `docs/review-checklist.md`
