---
id: FTY-040
state: merged
primary_lane: contracts
touched_lanes:
  - backend-core
  - estimator
  - infra
  - security-privacy
review_focus:
  - idempotency
  - retry-policy
  - state-machine-contract
  - estimation-run-retention
risk: high
tags:
  - estimator
  - jobs
  - celery
  - contracts
approved_dependencies: []
requires_context:
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/adr/0002-product-architecture.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-040: Estimator Job Contract

## State

ready_with_notes

## Lane

contracts

## Dependencies

- FTY-030

## Outcome

Creating a pending log event enqueues an async estimation job that moves the event through the status state machine and records an auditable estimation run, with a pluggable pipeline ready for the parse and calculation steps.

## Scope

- Define and migrate `estimation_jobs` and `estimation_runs` contracts (payloads, statuses, retries; run records storing model/provider, schema version, tool names, source references, assumptions, validation errors, and sanitized traces per the data-retention doc).
- On log-event creation (FTY-030), enqueue a Celery job (Redis broker). Extend the FTY-030 create path to publish the job.
- Implement an idempotent, retry-aware worker that: claims a pending event, creates an `estimation_runs` record, transitions `pending → processing`, runs a **pluggable pipeline** whose parse/calc steps are stubbed (filled by FTY-042/043/044), and transitions to `completed`, `failed`, or `needs_clarification`.
- Define the retry policy (bounded retries, exponential backoff, idempotency key on event/run) and document it.

## Non-Goals

- Actual NL parsing (FTY-042), exercise math (FTY-043), or food resolution (FTY-044) — the pipeline steps are stubbed here.
- LLM provider integration (FTY-041).
- Clarification answer flow / UI (later story).
- Derived item, evidence, or product tables (owned by the step stories).

## Contracts

- `estimation_jobs` payload + `estimation_runs` record schema become estimator contracts.
- The job enqueue trigger (event create → job) and the worker's status-transition behavior extend the FTY-030 event status state machine (implementing `processing`, `failed`, `needs_clarification` transitions defined there).
- The pluggable pipeline step interface is a contract FTY-042/043/044 implement against.

## Security / Privacy

`estimation_runs` must store sanitized traces only — no raw prompts, no secrets, no full personal history (security baseline + data-retention). Jobs carry event/user ids, not sensitive payloads in logs. Worker enforces user ownership when loading events. Rated high: estimator contracts, migrations, async trust boundary, and retention rules.

## Acceptance Criteria

- Creating a pending event enqueues a job; the worker processes it idempotently (re-delivery does not double-write).
- The worker creates an `estimation_runs` record and drives `pending → processing → completed/failed/needs_clarification`.
- Retry policy is enforced and documented; a failing step retries up to the bound then marks `failed`.
- `estimation_runs` persists model/provider/schema-version/tool-names/source-refs/assumptions/validation-errors/sanitized-trace fields; no raw prompts or secrets are stored or logged.
- Migrations apply and roll back; records carry user ownership.
- `make verify` passes (job + migration + idempotency/retry tests).

## Verification

- Run `make verify`, including idempotency and retry tests and a worker integration test driving a stub pipeline end-to-end.
- Apply/roll back the `estimation_jobs` / `estimation_runs` migrations.

## Planning Notes

- Exact retry count, backoff curve, and idempotency-key construction are documented defaults that may be tuned in the PR; conservative values to start.
- This story assumes the FTY-011 worker service and FTY-012 backend exist; it depends on FTY-030 for the events it processes.

## Readiness Sanity Pass

- Product decision gaps: none blocking — enqueue-on-create + pluggable stubbed pipeline resolved.
- Cross-lane impact: backbone the estimator step stories plug into; extends the FTY-030 state machine.
- Security/privacy risk: high; async trust boundary + run-record retention, mitigated by sanitized traces and ownership checks.
- Verification path: `make verify` + idempotency/retry + worker integration tests.
- Assumptions safe for autonomy: yes; retry/idempotency params are documented tunables (notes).
