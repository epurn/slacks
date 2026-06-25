---
id: FTY-011
state: ready_with_notes
primary_lane: infra
touched_lanes:
  - backend-core
risk: low
tags:
  - docker
  - self-host
  - dev-env
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/architecture/system-overview.md
review_focus:
  - local-dev
  - secret-hygiene
  - scope-control
autonomous: true
---

# FTY-011: Docker Compose Dev Stack

## State

ready_with_notes

## Lane

infra

## Dependencies

- FTY-010

## Outcome

Fatty has a local Docker Compose stack shape for self-host-friendly development, including database, queue, API, and worker service definitions.

## Scope

- Add a Compose file for local development services.
- Include Postgres and Redis service definitions with development-safe defaults.
- Add API and worker service placeholders that match the repository layout from FTY-010.
- Document required local environment variables through example files only.
- Keep root verification working without requiring Docker to be running.

## Non-Goals

- Production deployment hardening.
- Hosted-service infrastructure.
- Real auth, estimator, or database schema behavior.
- Secret management beyond example configuration and `.gitignore` hygiene.

## Contracts

- Compose service names become local development contracts for later backend and worker stories.
- Environment variable names introduced here must be documented in example config only.

## Security / Privacy

Do not commit real credentials, provider keys, personal data, or production-like passwords. Use local-only example values and require overrides for anything sensitive.

## Acceptance Criteria

- `compose.yaml` or equivalent local Compose file defines Postgres, Redis, API, and worker services.
- Example environment configuration documents required local values without secrets.
- Root docs explain how to start and stop the local stack.
- `make verify` still passes without requiring running containers.

## Verification

- Run `make verify`.
- If Docker is available, validate the Compose file syntax.

## Planning Notes

- Use official Postgres and Redis images.
- API and worker commands may remain placeholders until backend tooling exists.

## Readiness Sanity Pass

- Product decision gaps: none for local development stack shape.
- Cross-lane impact: introduces service names consumed by backend and worker stories.
- Security/privacy risk: low if only example credentials are committed.
- Verification path: `make verify`; optional Compose syntax validation.
- Assumptions safe for autonomy: yes.
