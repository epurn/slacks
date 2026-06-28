---
id: FTY-108
state: merged
primary_lane: governance
touched_lanes:
  - security-privacy
review_focus:
  - dependency-update-config
  - ecosystem-coverage
  - schema-validity
risk: low
tags:
  - governance
  - dependabot
  - supply-chain
  - security
approved_dependencies: []
requires_context:
  - .github/dependabot.yml
  - docs/security/security-baseline.md
autonomous: true
---

# FTY-108: Expand Dependabot to the App Dependencies (governance)

## State

ready

## Lane

governance

## Dependencies

- None to schedule. This **extends merged governance** (FTY-000): the repo already
  ships `.github/dependabot.yml` with a single `github-actions` ecosystem. This
  story is a config-only addition under `.github/` (governance per the steward's
  `lane_for_path`) — no app code changes.

## Outcome

The backend Python deps, the mobile npm tree, and the Docker base images receive
automated vulnerability/update PRs, not just GitHub Actions. Today
`.github/dependabot.yml` declares **one** ecosystem (`github-actions`), so
FastAPI/SQLAlchemy/Celery (`backend/uv.lock`), Expo/React-Native
(`mobile/package-lock.json`), and the pinned base images
(`python:3.12-slim-bookworm`, `postgres:16.4-alpine`, `redis:7.4-alpine`) get
**zero** automated update or CVE PRs. The security baseline's Supply Chain
section (`docs/security/security-baseline.md`) mandates both "pinned or locked
dependencies" **and** "enable dependency update automation" — the pinning is in
place but the automation only covers CI. This closes that gap, the highest
value-to-effort item the audit surfaced.

## Scope

- **Add Dependabot update configs** to `.github/dependabot.yml`, alongside the
  existing `github-actions` entry (which is unchanged), for:
  - **Backend Python** — the `uv` ecosystem against the lockfile at
    `directory: "/backend"` (`pyproject.toml` + `uv.lock`).
  - **Mobile npm** — the `npm` ecosystem at `directory: "/mobile"`
    (`package-lock.json`).
  - **Docker base images** — the `docker` ecosystem at `directory: "/backend"`
    (the `Dockerfile` `FROM python:3.12-slim-bookworm` and the pinned
    `ghcr.io/astral-sh/uv` / Node copies). See Planning Notes on the
    Compose images (`postgres`, `redis`).
- **Set sane defaults per ecosystem** to avoid PR spam: a `weekly` schedule, an
  `open-pull-requests-limit` (mirror the existing `5`), and dependency
  **grouping** (e.g. a single grouped PR per ecosystem for minor/patch updates)
  so a week's bumps arrive as a few reviewable PRs rather than dozens. These are
  small, reversible config choices — see Planning Notes.
- **Keep the file valid and schema-correct** Dependabot config (version 2).

## Non-Goals

- **No dependency bumps in this PR.** This adds the *config* that produces update
  PRs; it does not upgrade any package. The version-bump PRs Dependabot opens are
  reviewed separately.
- **No change to the pinning/locking strategy.** Lockfiles and pinned image tags
  stay as-is; Dependabot proposes bumps against them.
- **No merge automation / auto-merge.** No auto-approve, no automerge rules — every
  Dependabot PR still goes through the normal review gate.
- **No app code, CI workflow, or `Dockerfile`/`docker-compose.yml` edits.** Config
  coverage only.

## Contracts

- No public product contract. The only changed artifact is
  `.github/dependabot.yml` (a repo governance config). The committed images and
  lockfiles it targets are referenced read-only.

## Security / Privacy

- **Pure security-positive supply-chain change.** It directly satisfies the
  baseline's "enable dependency update automation" requirement for the app deps
  that currently have none, surfacing CVE/update PRs for the backend, mobile, and
  base-image surfaces. No secrets, tokens, or private automation details enter the
  public repo — Dependabot config is GitHub-native and references only directory
  paths and ecosystems already public in the repo.
- **No new trust boundary, no runtime behaviour change.** Config-only; nothing
  executes differently until a proposed bump is independently reviewed and merged.

## Acceptance Criteria

- `.github/dependabot.yml` is valid YAML and a schema-valid Dependabot v2 config.
- The existing `github-actions` update entry is preserved unchanged.
- New update entries exist for: `uv` at `/backend`, `npm` at `/mobile`, and
  `docker` at `/backend` — each pointing at a real directory that contains the
  corresponding manifest/Dockerfile.
- Each ecosystem sets a `schedule` (weekly), an `open-pull-requests-limit`, and a
  grouping config to bound PR volume.
- No dependency versions are changed; no app code, workflow, `Dockerfile`, or
  `docker-compose.yml` is modified.
- Root `make verify` stays green (this is CI/config only).

## Verification

- **YAML + schema:** confirm the file parses as YAML and conforms to the
  Dependabot v2 schema (a local YAML parse + schema check; e.g.
  `python -c "import yaml,sys; yaml.safe_load(open('.github/dependabot.yml'))"`
  plus a schema lint). **Note:** full Dependabot config validity is authoritatively
  confirmed by GitHub once pushed (the Dependabot config validation in the repo's
  Insights/Security tab) — local checks cover YAML well-formedness and schema shape,
  not GitHub-side resolution.
- **Directory/manifest reality check:** assert each declared `directory` holds the
  expected manifest — `/backend/pyproject.toml`, `/backend/uv.lock`,
  `/mobile/package-lock.json`, `/backend/Dockerfile`.
- **Regression:** root `make verify` passes (config-only; no app surface touched).

## Planning Notes

- **`uv` vs `pip` ecosystem:** the backend uses `uv` with `uv.lock`, so the `uv`
  package-ecosystem (which understands the lockfile) is the correct target. If the
  repo's Dependabot does not yet resolve the `uv` ecosystem, `pip` against
  `pyproject.toml` is the fallback — but prefer `uv` so updates respect the lock.
- **Compose images (`postgres:16.4-alpine`, `redis:7.4-alpine`):** the `docker`
  ecosystem at `/backend` covers the `Dockerfile` `FROM` lines. The Compose image
  tags live in the root `docker-compose.yml`; whether to add a `docker` entry at
  `/` (root) for Compose depends on GitHub's current Compose support. Including it
  is the more complete coverage; if GitHub does not resolve Compose images, scope
  the `docker` ecosystem to the `Dockerfile` and note the Compose gap rather than
  shipping an entry that errors. Pick the broadest coverage that validates cleanly.
- **Grouping + limits are a reversible call:** weekly + grouped minor/patch PRs +
  an open-PR limit keeps noise down without missing security updates (security
  updates are not subject to the open-PR limit). Easy to tune later; chosen to bias
  toward a few reviewable PRs over a flood.
- No evidence research warranted — this is a config/security-hygiene decision the
  baseline already answers, not a health/nutrition/behavioural question.

## Readiness Sanity Pass

- **Product decision gaps:** none load-bearing. The two judgment calls — the `uv`
  ecosystem (vs `pip`) and how far to push Docker/Compose coverage — are decided
  above with a clean fallback, both reversible config edits. `ready`.
- **Cross-lane impact:** primary governance; security-privacy rides along
  (non-serializing). **Single boundary, zero big rocks:** no public contract
  change, no schema migration, no new untrusted-input trust boundary — a config
  file addition in one lane.
- **Size:** `review_focus` = 3 (well under the 5 ceiling): dependency-update-config,
  ecosystem-coverage, schema-validity. `requires_context` = 2 (well under 8). Comfortably
  one story.
- **Security/privacy risk:** low — security-positive, config-only, no runtime
  behaviour change, no secrets cross into the public repo.
- **Verification path:** YAML parse + schema check + directory/manifest reality
  check + root `make verify` green; GitHub confirms config resolution post-push.
- **Assumptions safe for autonomy:** yes — a bounded, reversible config addition
  with the only judgment calls (ecosystem choice, Compose coverage, grouping)
  pinned here. No app code, no external provider, no UI.
