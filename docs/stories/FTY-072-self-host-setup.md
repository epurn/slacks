---
id: FTY-072
state: ready_with_notes
primary_lane: infra
touched_lanes:
  - contracts
  - security-privacy
risk: medium
tags:
  - infra
  - self-host
  - docker
  - docs
  - config
  - secrets
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/stories/FTY-011-docker-compose-dev-stack.md
  - docs/adr/0002-product-architecture.md
  - docs/contracts/llm-provider.md
  - docs/security/security-baseline.md
review_focus:
  - scope-control
  - secret-hygiene
  - self-host-config-contract
review_focus_notes:
  - No real secrets committed; .env.example is placeholder-only.
  - Verify the consolidated FATTY_* env-var surface matches the upstream contracts.
autonomous: true
---

# FTY-072: Self-Host Setup

## State

ready_with_notes

## Lane

infra

## Dependencies

- FTY-011
- FTY-012

## Outcome

A fresh self-hoster can stand up Fatty from a clean checkout by following a
documented path: the README plus the Docker Compose stack bring up Postgres,
Redis, the API, and the worker over plain HTTP, configured by a single,
fully-documented `.env`. First-boot migrations apply automatically, the health
endpoint responds, and the app runs with every optional provider omitted
(degrading to model-prior-with-status per evidence-retrieval) or with any
combination of providers configured.

## Scope

This is the documentation + configuration delta on top of the FTY-011 dev
compose stack. It adds no application logic.

- Add a **self-host section to the README** with prerequisites (Docker + Docker
  Compose, a free USDA FDC key if generic-food lookup is wanted, optional LLM
  and search keys) and a step-by-step bring-up: clone, copy `.env.example` to
  `.env`, generate/set the auth secret, `docker compose up`, confirm health.
- Provide a **complete, documented `.env.example`** that consolidates every
  `FATTY_*` contract variable a self-hoster needs as the single self-host config
  surface, grouped and commented:
  - **Auth / app secret** — the secret(s) backing the secure local auth path
    (e.g. the JWT signing secret), with a documented generation command and a
    placeholder-only value.
  - **Datastores** — the Postgres database URL and the Redis URL (from FTY-011).
  - **LLM provider** — the `FATTY_LLM_*` variables per
    `docs/contracts/llm-provider.md` (`FATTY_LLM_PROVIDER`, `FATTY_LLM_API_KEY`,
    `FATTY_LLM_MODEL`, `FATTY_LLM_BASE_URL`, `FATTY_LLM_TIMEOUT_SECONDS`,
    `FATTY_LLM_MAX_RETRIES`), documenting OpenAI / Anthropic /
    OpenAI-compatible / `fake` and which fields each requires.
  - **USDA FoodData Central** — the FDC API key var (per FTY-044), documented as
    optional (a free key); when omitted, generic-food USDA lookup is unavailable.
  - **Open Food Facts** — the `FATTY_OFF_*` toggle/config (per FTY-060),
    documented with its enable/disable flag; OFF needs no secret key.
  - **Official-source search** — the `FATTY_SEARCH_*` Brave config (per FTY-062),
    documented as optional and **disabled by default** (no bundled key).
- Document **first-boot migrations**: how Alembic migrations apply automatically
  on stack start (or the single documented command to run them), so a clean
  checkout reaches a migrated schema without manual schema work.
- Document **auth-secret generation**: a copy-pasteable command to produce a
  strong secret and where to place it, and that it must be set before first boot.
- Make **provider availability explicit**: document that each optional provider
  (LLM, USDA FDC, OFF, search) can be omitted, and that the app starts and
  degrades to model-prior-with-status (per evidence-retrieval) rather than
  failing, surfacing availability in health/config diagnostics.

## Non-Goals

- Production hardening: TLS/HTTPS termination, reverse proxy, backups,
  resource limits, scaling, or high availability.
- Managed/cloud deployment recipes (Kubernetes, hosted Postgres/Redis, etc.).
- Mobile app distribution / store packaging.
- Any new application logic, endpoints, or schema; this is docs + compose/env
  configuration over the existing dev stack only.

## Contracts

- Consolidates and documents the existing `FATTY_*` environment-variable
  contracts as the **self-host configuration surface**: the `FATTY_LLM_*` LLM
  provider contract (`docs/contracts/llm-provider.md`), the USDA FDC key
  (FTY-044), the `FATTY_OFF_*` Open Food Facts config (FTY-060), and the
  `FATTY_SEARCH_*` Brave config (FTY-062). No new code contract is introduced.
- Builds on the FTY-011 compose contract (service names, ports, DB/Redis env
  vars) and the FTY-012 `GET /healthz` shape. Note any compose or `.env.example`
  changes made here, since `.env.example` is itself the documented contract.

## Security / Privacy

- No secrets are committed: `.env.example` carries **placeholder values only**;
  the real `.env` stays gitignored (per FTY-011 and the security baseline). The
  PR must contain no real keys, tokens, or credentials.
- Provider keys (LLM, USDA FDC, search) are **server-side only**: read from the
  environment, never exposed to mobile/web clients and never logged, per the LLM
  provider contract and security baseline.
- The auth secret follows the security baseline's secure-local-auth-path
  requirement: generated by the self-hoster, never shipped with a default value,
  documented as required before first boot.
- Scope is HTTP-only local self-host; TLS remains a deferred production-hardening
  concern (non-goal). The README must say so plainly so a self-hoster does not
  mistake this for a production-ready deployment.
- Rated **medium**: this touches secret handling and the env-var self-host
  contract surface, but is docs + compose/env with no application logic.

## Acceptance Criteria

- From a clean checkout, following the README self-host section plus
  `.env.example` brings the full stack (Postgres, Redis, API, worker) up over
  HTTP, and the health endpoint returns 200.
- Migrations apply on first boot (automatically or via the single documented
  command) so the schema is ready without manual intervention.
- The app starts and serves health **with all optional providers omitted**
  (LLM `fake`/unset, no FDC key, OFF disabled, search disabled), degrading to
  model-prior-with-status rather than failing; availability is reflected in
  health/config diagnostics.
- The app also starts and serves health **with optional providers configured**
  (valid `FATTY_LLM_*`, FDC key, OFF enabled, `FATTY_SEARCH_*` set).
- `.env.example` documents every required and optional `FATTY_*` variable with
  placeholders only; no real secrets exist anywhere in committed files.
- A documented smoke check (`curl` the health endpoint) succeeds.
- `make verify` passes.

## Verification

- From a clean checkout, copy `.env.example` to `.env`, generate/set the auth
  secret per the README, run `docker compose up`, and confirm all four services
  reach a healthy/running state.
- Confirm migrations have applied (schema present) on first boot.
- `curl` the health endpoint over HTTP and confirm a 200 (the documented smoke
  check), once with all optional providers omitted and once with them configured.
- Grep the diff / committed tree to confirm `.env.example` is placeholder-only
  and no real secret or `.env` is present.
- Run `make verify` to confirm repo checks pass.

## Planning Notes

- Whether migrations run via a compose entrypoint/init step or a documented
  one-line command is an implementation choice, provided a clean checkout reaches
  a migrated schema by following the README.
- Exact `.env.example` variable names track the upstream contracts
  (`docs/contracts/llm-provider.md`, FTY-044, FTY-060, FTY-062); if any upstream
  story has not yet landed its variable, document the contracted name and mark it
  as forthcoming rather than inventing a divergent name.
- TLS/HTTPS, backups, and scaling are explicitly deferred — this story stops at a
  working local self-host over HTTP.

## Readiness Sanity Pass

- Product decision gaps: none — HTTP-only local self-host, single consolidated
  `.env.example`, auto-migrate on first boot, and optional-provider degradation
  are all resolved.
- Cross-lane impact: turns the existing `FATTY_*` contracts into the documented
  self-host config surface (contracts) and codifies secret handling for
  self-host (security-privacy); no application logic changes.
- Security/privacy risk: medium — secret handling and the env-var surface, with
  placeholder-only `.env.example`, gitignored `.env`, server-side-only provider
  keys, and a self-host-generated auth secret.
- Verification path: clean-checkout `docker compose up` + first-boot migration
  check + health smoke check (providers omitted and configured) + secret grep +
  `make verify`.
- Assumptions safe for autonomy: yes, with the production-hardening-deferred note
  (TLS/backups/scaling out of scope) captured as the `ready_with_notes` caveat.
