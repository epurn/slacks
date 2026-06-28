---
id: FTY-088
state: merged
primary_lane: infra
touched_lanes:
  - docs
risk: medium
tags:
  - self-host
  - llm-provider
  - claude-code
  - packaging
  - diagnostics
  - secret-handling
approved_dependencies:
  - FTY-087
  - FTY-089
requires_context:
  - docs/operations/local-dev-stack.md
  - docs/architecture/repo-layout.md
  - docs/security/security-baseline.md
review_focus:
  - claude-code-available-to-worker-runtime
  - one-time-claude-login-and-persistent-session-documented
  - provider-selection-and-no-api-key-documented
  - healthz-shows-claude_code-availability-without-leaking-secrets
autonomous: true
---

# FTY-088: Claude Code self-host packaging + setup

## State

ready

## Lane

infra

## Dependencies

- FTY-087
- FTY-089 (so the CHANGELOG/README capstone documents both provider-access paths)

## Outcome

A self-hoster can run Fatty estimation through the new `claude_code` LLM provider
(FTY-087) on their own server, on their Claude subscription, with no API key.
This story makes that provider *usable in a real deployment*: the locally
first-party Claude Code CLI is present in the runtime that executes estimation
(the Celery worker), the operator has a documented one-time `claude login` step
whose session survives container restarts, selecting the provider is a single
documented `.env` change, and `GET /healthz/sources` tells the operator whether
Claude Code is installed and the session is valid — all without baking or leaking
any credential. After this story the FTY-087 adapter has a deployment path; the
adapter logic itself is out of scope here.

## Scope

This story is packaging + setup + diagnostics + docs. It provisions Claude Code
for the runtime and documents how to use it; it does not implement the provider
adapter (that is FTY-087).

1. **Make Claude Code available to the estimation runtime.** The Celery
   `worker` service (which runs estimation) — and, for parity/diagnostics, the
   `api` service, since both build from the same `backend/` image — must be able
   to invoke the `claude` CLI in headless mode. **Chosen approach: install the
   Claude Code CLI inside the `backend/` Docker image** rather than mounting a
   host binary. Rationale, from the existing setup:
   - The image is `python:3.12-slim-bookworm` built with `uv`; `api` and
     `worker` share it (`docker-compose.yml`), so one install covers both
     estimation and diagnostics.
   - Claude Code is distributed for the container's own OS/arch; a host-install +
     bind-mount of the binary is brittle and wrong across the host↔container
     boundary (e.g. a macOS host binary cannot run in the linux container). An
     in-image install is the only approach that reliably gives the linux worker a
     runnable `claude`.
   - Add the CLI install as its own cached layer in `backend/Dockerfile`,
     pinned per the security baseline's pinned-dependency principle (pin the CLI
     version and, if a Node runtime is required, the Node version). **No
     credentials are added to the image** — only the binary/runtime.
2. **Document the one-time auth and make the session persist.** Auth is the
   operator's local Claude Code session (subscription-backed OAuth), created by
   running `claude login` once. Because the CLI runs in-container:
   - Mount a dedicated volume for the Claude Code config/session directory (the
     CLI's config dir, e.g. via `CLAUDE_CONFIG_DIR`) on `api`/`worker`, the same
     way `postgres-data` persists Postgres state, so the session survives
     `docker compose down`/`up` and restarts.
   - Document the one-time login as an interactive run into the container (e.g.
     `docker compose exec` / `run` the `claude login` device/OAuth flow: the CLI
     prints a URL, the operator authorizes in their browser and pastes the code).
     The session is then written into the mounted volume.
   - Document where the session lives, that the mounted dir is a **host secret**
     (restrictive permissions), and that it is never committed and never copied
     into the image.
3. **Document provider selection.** In `.env` / `.env.example`, set
   `FATTY_LLM_PROVIDER=claude_code` to select it. Document which other
   `FATTY_LLM_*` variables apply and which do not — explicitly that **no
   `FATTY_LLM_API_KEY` is needed** for this provider (auth is the local session),
   and call out the model-selection var if one applies (per FTY-087's provider
   surface). Keep `.env.example` placeholder-only (no real secrets).
4. **Surface availability via diagnostics.** Extend `GET /healthz/sources` (or a
   sibling diagnostics field on the same endpoint) so it reports a `claude_code`
   capability with `enabled` (selected as the provider) and `available` (CLI
   present **and** a valid local session detected). Detection must be cheap and
   **leak nothing**: report booleans only — never a token, session contents,
   account identity, or raw CLI output. Use a bounded, non-secret check (presence
   of the session in the config dir and/or a bounded `claude`-status probe with a
   timeout); do not block the endpoint on a network round-trip.
5. **Update docs + CHANGELOG.** Update the README **Self-Hosting** section and
   `docs/operations/local-dev-stack.md` to cover: installing/availability of
   Claude Code in the image, the one-time `claude login` + persistent session
   volume, selecting `FATTY_LLM_PROVIDER=claude_code` with no API key, and how to
   confirm availability via `/healthz/sources`. **Also update `CHANGELOG.md`**
   (the v1.0.0 entry written by FTY-080) to list the new v1 self-host
   provider-access options — the `claude_code` subscription provider (FTY-087) and
   the keyless local-model path (FTY-089) — so the shipped CHANGELOG matches the
   v1 product. (This is why this capstone also depends on FTY-089.)

## Non-Goals

- The `claude_code` provider adapter itself, including its headless invocation
  (`claude -p --output-format json --json-schema`) and tools-disabled
  enforcement — that is **FTY-087**. This story only provisions and documents.
- The local-model / Ollama self-host path (**FTY-089**).
- Any change to estimation behavior, prompts, or the estimator pipeline.
- Bundling Claude subscription credentials into the image or repo — **never ship
  credentials**.
- TLS / reverse proxy / production hardening / cloud deployment — still out of
  scope for the local self-host stack (FTY-072 boundary).
- A contract change to the LLM provider boundary — the provider boundary lands in
  FTY-087; here the only public-surface touch is the additive `/healthz/sources`
  diagnostics descriptor.

## Contracts

- **None beyond documenting the new provider option.** `FATTY_LLM_PROVIDER=
  claude_code` becomes a documented, selectable value (the provider boundary is
  FTY-087's). The `/healthz/sources` change is **additive**: a new capability
  descriptor (booleans only, no new secret-bearing field), consistent with the
  existing `SourceCapability` shape and the "no secrets, no external calls beyond
  a bounded local probe" diagnostics property.

## Security / Privacy

- **Never bake or commit credentials.** The image contains only the CLI/runtime.
  The Claude Code session lives only in the mounted host config/session
  directory, which is a **host secret**: document restrictive permissions and
  that it is gitignored and never copied into the image or repo.
- **Diagnostics leak nothing.** `/healthz/sources` reports `enabled`/`available`
  booleans only for `claude_code`. No token, session blob, account identity,
  model identifier-beyond-label, or raw CLI output may appear in the response or
  logs; the availability probe is bounded and content-free per the security
  baseline's no-secret-in-logs/responses rule.
- **Tools-disabled is FTY-087's job.** Claude Code must run with tools fully
  disabled (enforced by the FTY-087 adapter's invocation flags); this story only
  provisions the CLI and must not introduce any path that runs it with tools
  enabled.
- **Public-repo boundary stays green.** No private automation, machine paths,
  tokens, or queue state enter `fatty`; the governance/public-repo-boundary check
  must pass.
- Rated **medium**: it adds a runtime dependency and an authenticated local
  session to the deployment and touches a diagnostics endpoint, but it changes no
  estimation behavior and adds no untrusted-input trust boundary. When risk was
  ambiguous it was rounded up to medium.

## Acceptance Criteria

- The `backend/` image build installs a pinned Claude Code CLI (and any required
  pinned runtime); `claude` is invokable in both the `worker` and `api`
  containers, and **no credentials are present in the image**.
- `docker-compose.yml` mounts a persistent volume for the Claude Code config/
  session directory on `api`/`worker`, so a session created once survives
  `docker compose down && docker compose up`.
- The README Self-Hosting section and `docs/operations/local-dev-stack.md`
  document, end to end: install/availability of Claude Code, the one-time
  `claude login` interactive flow into the container, the persistent session
  volume and its host-secret permissions, selecting
  `FATTY_LLM_PROVIDER=claude_code` with **no API key**, and confirming via
  `/healthz/sources`.
- `.env.example` documents `FATTY_LLM_PROVIDER=claude_code` and the applicable
  `FATTY_LLM_*` vars (and explicitly that no API key is required), placeholder-
  only.
- `GET /healthz/sources` reports a `claude_code` descriptor with correct
  `enabled`/`available` semantics (CLI present + valid session ⇒ `available`),
  carrying **no** secret or identity, with a bounded availability check.
- `make verify` passes (governance/public-repo boundary + docs + backend tests
  for the diagnostics change), and no credential is committed or baked into the
  image.

## Verification

- `make verify` from the backend: governance/public-repo boundary green, docs
  checks green, and a test for the `/healthz/sources` `claude_code` descriptor
  that asserts (a) correct `enabled`/`available` booleans for present/absent CLI
  and present/absent session via a stubbed probe, and (b) **no** token/session/
  identity/raw-output leaks into the response or logs (no live `claude` call in
  tests).
- Image check: build the `backend/` image and confirm `claude` is on `PATH` in
  the `worker` (and `api`) container and that the image contains **no** Claude
  credentials/session files.
- Manual / CI deployment check (documented): with Claude Code installed in the
  image and a one-time `claude login` completed into the mounted session volume,
  and `FATTY_LLM_PROVIDER=claude_code` set, confirm the worker can invoke
  `claude` and `GET /healthz/sources` reports `claude_code` `available: true`;
  after `docker compose down && up` (without re-login) it is still `available`.
- Confirm no credentials are committed (`.env`, session dir gitignored) and none
  are baked into the image (governance boundary green).

## Planning Notes

- **Reference for the author (not `requires_context`):** Claude Code headless
  docs — https://code.claude.com/docs/en/headless — for the invocation surface
  the FTY-087 adapter relies on. This story provisions the CLI; FTY-087 owns the
  exact flags and the tools-disabled enforcement.
- **Approach was decided after inspecting the stack:** single shared `backend/`
  image (`api` + `worker`), `uv`/python-slim base, named-volume pattern already
  in use (`postgres-data`). In-image CLI install + a mounted session volume
  populated by a one-time interactive `claude login` is the approach that fits;
  host-binary mounting was rejected for cross-arch incompatibility. Pin the CLI
  (and Node runtime if needed) per the security baseline.
- **Diagnostics shape:** prefer extending the existing `/healthz/sources`
  `SourceCapability`-style descriptor over inventing a new endpoint, keeping the
  "booleans only, no secrets, bounded local check" property the endpoint already
  guarantees. If a `claude`-status probe is used for `available`, bound it with a
  timeout and never surface its output.
- **Depends on FTY-087** for the provider to exist and for tools-disabled
  enforcement; this story is the deployment enablement around it.

## Readiness Sanity Pass

- **Product decision gaps:** none — design is fully resolved (in-image install
  approach, persistent session volume + one-time interactive login, `.env`
  provider selection with no API key, additive `/healthz/sources` descriptor).
  Promoted to `ready` and pulled **into v1** (2026-06-28, user decision); the v1
  tag gates on it. Depends on FTY-087 (steward holds it until 087 merges).
- **Cross-lane impact:** primary `infra` (Dockerfile + compose + `.env.example`)
  with a `docs` touch (README + local-dev-stack) and a small additive backend
  diagnostics descriptor; one lane beyond primary, well under the split ceiling.
  No estimation behavior change.
- **Security/privacy risk:** medium — adds a runtime dependency and an
  authenticated local session; mitigated by never baking/committing credentials
  (image holds only the binary; session lives in a host-secret mounted volume),
  booleans-only/no-secret diagnostics with a bounded probe, tools-disabled
  enforced upstream in FTY-087, and the public-repo boundary check staying green.
- **Verification path:** `make verify` (governance boundary + docs + a
  `/healthz/sources` descriptor test with stubbed probe asserting no leakage),
  an image check that `claude` is on PATH with no baked credentials, and a
  documented manual/CI deployment check that estimation can invoke `claude` and
  the session persists across restarts.
- **Assumptions safe for autonomy:** yes — scope is bounded packaging + docs +
  an additive, non-secret diagnostics field; no contract change and no behavior
  change. Sizing: `touched_lanes` 1 / `review_focus` 4 / `requires_context` 3 —
  all under the split ceilings, and no second big rock (the provider boundary and
  tools-disabled enforcement are isolated in the FTY-087 dependency), so this
  stays a single vertical slice.
