---
id: FTY-080
state: merged
primary_lane: governance
touched_lanes:
  - backend-core
  - mobile-core
risk: medium
tags:
  - release
  - v1
  - changelog
  - versioning
approved_dependencies: []
requires_context:
  - docs/architecture/repo-layout.md
  - docs/architecture/system-overview.md
  - docs/standards/testing-standards.md
review_focus:
  - full-system-verify-green
  - version-consistency
  - changelog-accuracy
  - no-feature-scope-creep
autonomous: true
---

# FTY-080: v1 Release Prep

## State

merged

> This is **Phase 4 of the release runbook** (`docs/release-runbook.md`): the
> mechanical release-prep PR. Promoted `candidate → ready` on 2026-06-28 after the
> gate was satisfied: all dependencies (FTY-062/064/070/073/074/075) plus the
> release-audit fixes (FTY-081/082/083/084) are merged, and the full-system audit
> + fix loop (runbook Phases 1–3) is clean with `make verify`, the security suite,
> and migration apply/rollback all green. It prepares the release; it never
> implements features. The actual tag + GitHub release + deploy remains a human
> step (see Non-Goals).

## Lane

governance

## Dependencies

- FTY-062
- FTY-064
- FTY-070
- FTY-073
- FTY-074
- FTY-075

## Outcome

The repository is in a clean, releasable v1 state: a single source-of-truth
version, an accurate CHANGELOG, a README that describes the shipped product, and
a fully green `make verify` across every package. A human can then cut the v1 tag
and GitHub release from this PR with no further code work.

## Scope

- Set a consistent **v1.0.0** version across the repo's version sources (e.g.
  `mobile/package.json`, `backend/pyproject.toml`, and any root version marker).
  Document where the canonical version lives.
- Write a **CHANGELOG.md** for v1: a concise, user-facing summary of the shipped
  capabilities, organized by the v1 milestones (accounts/profile, logging spine,
  estimator, editing/saved-foods, evidence inputs, weight + daily summary). Derive
  it from the merged stories and the actual code — do not invent features.
- **README final pass**: confirm setup, run, and self-host instructions match the
  current code and `.env.example`; fix any drift; ensure it presents the v1 product
  accurately. Keep it honest about what is and isn't included.
- **Full-system verification is green**: `make verify` passes end to end
  (governance + backend + mobile + contracts). Fix only trivial release-blocking
  breakage; anything non-trivial is a separate story, not this one.
- Confirm the **public-repo boundary** holds: no private automation, machine paths,
  secrets, or agent files in the repo (governance check stays green).

## Non-Goals

- **No feature work.** If something is missing for v1, that is a new story, not a
  scope expansion here.
- **No git tag, GitHub release, version-control publish, or deploy** — those are
  human/CI actions outside the author's permissions. This story stops at the
  release-ready PR.
- No dependency upgrades or refactors beyond what a release blocker strictly
  requires.
- No new contracts, migrations, or endpoints.

## Contracts

- None. This is a release-coordination slice; it changes version metadata, the
  changelog, and docs only. It must not alter any API/DTO/job/provider contract.

## Security / Privacy

- Re-confirm the data-minimization, secret-handling, and public-repo-boundary
  guarantees still hold at release (the governance check enforces the boundary).
  This story adds no new data flows or egress.
- Medium risk: a release-coordination change with broad visibility but no new
  behavior; the heavy security work lands in FTY-073 (a dependency).

## Acceptance Criteria

- A single consistent **v1.0.0** version appears across all version sources, and
  the canonical location is documented.
- **CHANGELOG.md** exists and accurately summarizes the v1 capabilities by
  milestone, with no invented or unshipped features.
- The **README** matches the current setup/run/self-host reality and `.env.example`.
- **`make verify` passes** across governance, backend, mobile, and contracts.
- The governance / public-repo-boundary check is green (no private automation,
  secrets, or machine paths in the repo).

## Verification

- `make verify` (full, from a clean checkout) passes.
- Grep the version sources to confirm they all read `1.0.0`.
- Spot-check the CHANGELOG entries against merged features (each claimed capability
  has corresponding code/tests).
- Confirm the README's documented commands and `FATTY_*` config match
  `.env.example` and the package `verify.sh` hooks.

## Readiness Sanity Pass

- **Product decision gaps:** none — release prep only; no product decisions. The
  human owns the actual tag/release decision after this PR.
- **Cross-lane impact:** governance (version/changelog/docs) plus the version
  bump touching `mobile/package.json` (mobile-core) and `backend/pyproject.toml`
  (backend-core). No code behavior changes. Sequenced after all features merge,
  so lane contention is moot.
- **Security/privacy risk:** medium — broad visibility, but no new behavior or
  data flow; the boundary check and FTY-073 carry the security weight.
- **Verification path:** full `make verify` + version/changelog/README consistency
  checks.
- **Assumptions safe for autonomy:** yes — bounded to version/changelog/docs and a
  green verify; the tag/release/deploy is explicitly out of scope and human-owned.
- **Sizing:** 2 touched lanes, 4 review_focus, 3 requires_context — within the
  scope guardrail. Dependency count is high by design (it gates on all of v1) but
  dependencies do not count toward scope.
