---
id: FTY-012
state: ready
primary_lane: backend-core
touched_lanes:
  - contracts
  - infra
risk: medium
tags:
  - skeleton
  - backend
  - logging
  - tooling
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/security/security-baseline.md
  - docs/architecture/system-overview.md
review_focus:
  - logging-redaction
  - settings-validation
  - scope-control
  - verify-command
autonomous: true
---

# FTY-012: Backend App Skeleton

## State

ready

## Lane

backend-core

## Dependencies

- FTY-010

## Outcome

A minimal FastAPI application exists with a health endpoint, typed settings, structured logging, and a pytest harness, all wired into root `make verify`. This is the backend foundation every later backend, estimator, and contract story builds on.

## Scope

- Establish the backend Python toolchain as **uv** with a committed `uv.lock`. This sets the dependency-locking convention for all subsequent backend stories.
- Create a FastAPI app exposing a single health endpoint (`GET /healthz`) that returns a typed (Pydantic) response.
- Add Pydantic-based typed settings loaded from environment variables, with validation at startup.
- Add structured logging configured to avoid emitting secrets, tokens, raw prompts, or personal data per the coding standards and security baseline.
- Provide a pytest harness with at least one health-endpoint test.
- Plug package-level lint, typecheck, and test commands into root `make verify`.
- Route handlers delegate behavior to a service layer even at skeleton stage.

## Non-Goals

- Alembic / database migrations (explicitly deferred to FTY-020, which lands the first real model).
- Database models or persistence wiring.
- Auth, user model, or identity handling.
- Celery task definitions or estimator job logic.
- External provider integrations (LLM, search, nutrition).
- Any user-facing behavior beyond the health endpoint.

## Contracts

- The health endpoint response shape and path (`GET /healthz`) become a contract that FTY-011 (Docker Compose healthcheck) and later infra stories rely on.
- The settings environment-variable names become a contract consumed by FTY-011's compose env and later stories.
- Root `make verify` remains the single verification entry point; backend checks must plug into it.

## Security / Privacy

No user data is stored or processed. Typed settings read provider keys and secrets from environment variables only and must never log them. Structured logging must be configured so secrets, tokens, raw prompts, and personal data are never emitted — this logging-redaction posture is a security-sensitive convention that later stories inherit, which is why this story is rated medium rather than low.

## Acceptance Criteria

- `make verify` passes from a fresh checkout, running backend lint, typecheck, and tests.
- `GET /healthz` returns a typed HTTP 200 response.
- Settings load from environment variables with validation; missing/invalid required settings fail clearly at startup.
- A health-endpoint test passes in the pytest harness.
- Logs contain no secrets, tokens, or personal data.
- `uv.lock` is committed and dependencies are locked.

## Verification

- Run `make verify`.

## Planning Notes

- Exact FastAPI/uv project layout and minor toolchain details may be finalized in the implementation PR as long as the uv lockfile convention and the contracts above are honored.
- New third-party packages beyond the minimal FastAPI/uv/pytest set require a planning PR updating story metadata first.

## Readiness Sanity Pass

- Product decision gaps: none — toolchain (uv), endpoint shape, and migrations-deferral are all resolved.
- Cross-lane impact: sets backend toolchain, settings, and logging conventions consumed by infra (FTY-011) and all later backend stories.
- Security/privacy risk: medium; no user data, but establishes logging-redaction and secret-handling conventions that must fail safe.
- Verification path: `make verify`.
- Assumptions safe for autonomy: yes; scope is bounded, no DB/auth/providers, dependencies locked.
