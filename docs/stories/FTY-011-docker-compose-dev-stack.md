---
id: FTY-011
state: merged
primary_lane: infra
touched_lanes:
  - backend-core
  - contracts
risk: low
tags:
  - skeleton
  - infra
  - docker
  - tooling
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/security/security-baseline.md
  - docs/architecture/system-overview.md
review_focus:
  - scope-control
  - secret-hygiene
  - dependency-hygiene
autonomous: true
---

# FTY-011: Docker Compose Dev Stack

## State

ready_with_notes

## Lane

infra

## Dependencies

- FTY-010
- FTY-012

## Outcome

A developer can bring up the full local backend stack with a single `docker compose up`: Postgres, Redis, the FastAPI API, and a Celery worker, over plain HTTP for local development.

## Scope

- Add a `docker-compose.yml` defining four services: Postgres, Redis, API (FastAPI), and a Celery worker.
- API and worker build from the backend package created in FTY-012.
- Pin image versions for Postgres and Redis (e.g. `postgres:<N>`, `redis:<N>`) per the security baseline's pinned/locked-dependencies principle.
- Add healthchecks for Postgres and Redis; the API service waits for them to be healthy before starting.
- Provide a `.env.example` for compose (database URL, Redis URL, and other non-secret config), with the real `.env` gitignored.

## Non-Goals

- TLS, reverse proxy, or HTTPS termination (explicitly deferred to FTY-072, Self-host setup).
- Production hardening, resource limits, or orchestration beyond local dev.
- Object storage / S3-compatible services.
- Auth, estimator jobs, or actual Celery task definitions.
- Hosted/cloud deployment configuration.

## Contracts

- The compose service names, exposed ports, and environment-variable names become a contract that subsequent infra and backend stories rely on. Document them in `.env.example` and/or compose comments.
- The API service depends on FTY-012's `GET /healthz` endpoint shape for its healthcheck.

## Security / Privacy

No user data. No secrets are committed: only `.env.example` with placeholder, non-secret values is checked in; the real `.env` stays gitignored. Provider keys are never baked into images. Low risk.

## Acceptance Criteria

- `docker compose up` starts Postgres, Redis, API, and worker.
- The API health endpoint is reachable over HTTP from the host.
- The Celery worker connects to Redis successfully.
- Postgres and Redis healthchecks pass and the API waits on them.
- No secrets or real `.env` exist in the repository; `.env.example` is present and placeholder-only.

## Verification

- Run `docker compose up` and confirm all four services reach a healthy/running state.
- `curl` the API health endpoint over HTTP and confirm a 200 response.
- Run `make verify` to confirm repo checks still pass.

## Planning Notes

- This story assumes the FTY-012 backend skeleton has merged, since the API and worker build from that package — hence the FTY-012 dependency in addition to FTY-010. If sequenced before FTY-012 merges, hold implementation until the backend entrypoints exist.
- Specific image patch versions and minor compose ergonomics may be finalized in the implementation PR provided versions remain pinned.

## Readiness Sanity Pass

- Product decision gaps: none — HTTP-only scope and service set are resolved; TLS is an explicit non-goal.
- Cross-lane impact: establishes the local infra contract (service names, ports, env vars) consumed by later backend and infra stories.
- Security/privacy risk: low; no user data, no committed secrets, pinned images.
- Verification path: `docker compose up` + health curl + `make verify`.
- Assumptions safe for autonomy: yes, with the noted sequencing dependency on FTY-012 — captured as a ready_with_notes caveat.
