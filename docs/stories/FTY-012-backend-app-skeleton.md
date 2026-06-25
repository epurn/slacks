---
id: FTY-012
state: ready_with_notes
primary_lane: backend-core
touched_lanes:
  - contracts
risk: low
tags:
  - fastapi
  - backend
  - scaffold
approved_dependencies:
  - fastapi
  - uvicorn
  - pydantic-settings
  - pytest
  - httpx
requires_context:
  - docs/stories/README.md
  - docs/architecture/system-overview.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - test-harness
  - config-boundaries
  - logging-hygiene
autonomous: true
---

# FTY-012: Backend App Skeleton

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- FTY-010

## Outcome

Fatty has a typed FastAPI backend skeleton with health checks, settings, logging, and tests wired into root verification.

## Scope

- Add a FastAPI application package under the backend area.
- Add typed settings loaded from environment variables.
- Add a health endpoint suitable for local and Compose checks.
- Add structured logging setup that avoids sensitive values.
- Add backend unit tests and wire them into root verification.

## Non-Goals

- Database models or migrations.
- Authentication.
- Estimation jobs.
- Provider integrations.
- Production deployment configuration.

## Contracts

- Backend app entrypoint.
- Health endpoint response shape.
- Settings module boundary.
- Root verification command integration.

## Security / Privacy

Settings must not read or print secrets during normal startup. Logs must not include tokens, raw prompts, personal profile data, or food history.

## Acceptance Criteria

- Backend app starts locally through a documented command.
- Health endpoint returns a stable JSON shape.
- Tests cover the app factory/settings defaults/health route.
- Root `make verify` runs backend checks.
- Example configuration documents required values without secrets.

## Verification

- Run `make verify`.
- Run backend tests directly if package tooling adds a package-specific command.

## Planning Notes

- Keep route handlers thin from the start.
- Use Pydantic settings for config; do not introduce a larger framework.

## Readiness Sanity Pass

- Product decision gaps: none for backend skeleton.
- Cross-lane impact: creates API app boundary consumed by infra, auth, logging, and estimator stories.
- Security/privacy risk: low; config/logging hygiene is the main concern.
- Verification path: `make verify` plus backend tests.
- Assumptions safe for autonomy: yes.
