---
id: FTY-084
state: merged
primary_lane: governance
touched_lanes:
  - contracts
risk: low
tags:
  - docs
  - contracts
  - release
  - diagnostics
approved_dependencies: []
requires_context:
  - docs/architecture/system-overview.md
  - docs/architecture/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/security/data-retention.md
  - docs/security/threat-model.md
review_focus:
  - healthz-liveness-endpoint-documented
  - docs-match-shipped-behavior
  - no-version-or-changelog-changes
autonomous: true
---

# FTY-084: Release Docs Polish — Document `/healthz` and Close Audit Doc Gaps

## State

ready

## Lane

governance

## Dependencies

- none

## Outcome

The documentation matches the shipped product on the specific points the release
audit flagged: the `/healthz` liveness probe is contracted alongside its sibling
diagnostics, the evidence source hierarchy is listed completely in the
architecture overview, and a few low-risk clarity gaps (port config, retention
deletion scope, OFF default) are corrected. Docs-only; no product code changes.

## Scope

Each item is small and independent:

1. **Document `GET /healthz`** (liveness). It is implemented
   (`backend/app/routers/health.py`) and tested (`backend/tests/test_health.py`)
   but uncontracted. Add it where its siblings already live: `food-resolution.md`
   documents `/healthz/sources` and `/healthz/egress` — add a short "Liveness &
   Diagnostics" note covering all three (`/healthz` → `{"status": "ok"}`).
2. **List all evidence source types** in `docs/architecture/system-overview.md`
   (~line 27): include user-provided nutrition label images (FTY-064) and the
   USDA-vs-OFF roles, aligning with `evidence-retrieval.md`'s full hierarchy.
3. **Self-host port note** in `README.md`: one line noting `POSTGRES_PORT`,
   `REDIS_PORT`, and `API_PORT` can be set in `.env` to avoid host port
   conflicts.
4. **Retention deletion scope** in `docs/security/data-retention.md`: clarify that
   users delete user-created data (corrections, weight entries, saved foods,
   attachments) and accounts (account deletion cascades), matching the contracts
   (no per-event DELETE endpoint exists).
5. **OFF default clarity** in `.env.example`: make explicit that
   `FATTY_OFF_ENABLED` defaults to `true` (enabled, no key required).
6. **Threat-model reference clarity** in `docs/security/threat-model.md`: clarify
   what the "FTY-073 security pass" reference points to (the security test suite
   under `backend/tests/security/`), since story IDs are not otherwise tracked in
   the public repo.

## Non-Goals

- **No version bumps and no CHANGELOG edits** — those belong to FTY-080 (release
  prep); this story must not touch versioning to avoid overlap.
- No product code, schema, endpoint, or behavior changes.
- The mobile API-client boilerplate dedup (separate non-blocking follow-up).

## Contracts

- Adds documentation for the existing `GET /healthz` endpoint (behavior
  unchanged). No request/response shape changes anywhere.

## Security / Privacy

- Docs-only. Item 6 reduces ambiguity about how the threat model was reconciled;
  item 4 makes the deletion/retention story match the actual endpoints. No
  behavior change, no new surface. Rated **low**. (Per item 6, prefer describing
  the security test suite rather than introducing private story-tracking detail
  into the public repo, honoring the public-repo boundary.)

## Acceptance Criteria

- `GET /healthz` is documented (response shape + purpose) alongside
  `/healthz/sources` and `/healthz/egress`.
- The architecture overview lists the full evidence source set (label images +
  USDA + OFF + official search/fetch) consistent with `evidence-retrieval.md`.
- README notes the configurable host ports; `.env.example` states the OFF default
  explicitly; `data-retention.md` deletion scope matches the contracts;
  `threat-model.md` clarifies the security-pass reference.
- No version string or CHANGELOG entry is added or changed by this story.
- `make verify` (governance + docs checks) passes; the public-repo boundary check
  stays green.

## Verification

- `make verify` (governance boundary + any docs/link checks).
- Manual read-through diff confirming each of the six items is addressed and that
  no versioning/CHANGELOG content changed.

## Readiness Sanity Pass

- **Product decision gaps:** none — every item documents already-shipped
  behavior; wording is the author's discretion.
- **Cross-lane impact:** governance (docs) + contracts (the `/healthz` note).
  One touched lane.
- **Security/privacy risk:** low — docs-only; explicitly preserves the
  public-repo boundary and changes no behavior.
- **Verification path:** `make verify` + a read-through diff.
- **Assumptions safe for autonomy:** yes — concrete files/lines and intended
  edits are enumerated; non-goals fence it off from FTY-080.
- **Sizing:** 1 touched lane, 3 review_focus, 5 requires_context — within the
  scope guardrail. Six small, independent docs edits.
