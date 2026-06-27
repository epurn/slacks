---
id: FTY-077
state: merged
primary_lane: security-privacy
touched_lanes:
  - backend-core
risk: high
tags:
  - attachments
  - retention
  - migration
approved_dependencies: []
requires_context:
  - docs/contracts/log-events.md
  - docs/security/data-retention.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
review_focus:
  - attachment-retention-default
  - migration-rollback
  - upload-constraints
autonomous: true
---

# FTY-077: log_attachments Table + Discard-by-Default Retention

## State

ready

## Lane

security-privacy

## Dependencies

(none — additive migration + DTO)

## Outcome

A user-owned `log_attachments` table exists to hold an uploaded image **only when
the user explicitly saves it**. By default no raw image is persisted. This is the
storage + retention prerequisite for nutrition-label extraction (FTY-061); it
ships no extraction logic of its own. Resolves the `log-events.md` "excluded:
`log_attachments` (FTY-060/061)" placeholder.

## Scope

- Introduce the **`log_attachments` table + DTO** via an **additive, reversible**
  migration (no destructive change to prior tables). The migration number follows
  the latest applied migration at implementation time.
- **Retention default = discard** per `data-retention.md`: an uploaded image is
  retained only while needed and discarded afterward unless the user explicitly
  saves it. An explicit save writes exactly one `log_attachments` row; the default
  flow persists no raw image.
- **Upload constraints:** enforce image **size** and **content-type** limits;
  reject oversized or non-image input **deterministically and fail-closed**
  before the bytes are stored or handed onward.
- The table stores the saved image owned by the user, with the metadata needed to
  retrieve and delete it; it never stores model output (that's evidence, FTY-061).

## Non-Goals

- The provider vision contract (FTY-076) and the extraction pipeline / schema /
  evidence write (FTY-061).
- Mobile capture / upload UI (FTY-064).
- `evidence_sources` storage — that is extracted facts, not the raw image.

## Contracts

- **`log_attachments` table + DTO**: new user-owned table; default behavior
  persists no raw image; resolves the `log-events.md` placeholder. Coordinate so
  only one migration creates the table if FTY-060 lands first.

## Security / Privacy

- **Discard by default.** No raw image is persisted unless the user explicitly
  saves the attachment; avoid long-term raw image/OCR retention.
- **Upload constraints fail closed:** oversize/invalid content-type is rejected
  deterministically before storage.
- **User-owned + deletable:** the row carries enough to retrieve and delete the
  saved image on user request.
- Rated **high**: a new retention surface and a schema migration.

## Acceptance Criteria

- The `log_attachments` migration **applies and rolls back cleanly** against a
  throwaway database and is **additive** (no destructive change to prior tables).
- A **retention test** proves the default flow writes **no** attachment row, and
  an **explicit-save** flow writes exactly **one**.
- **Negative tests** prove oversize and invalid-content-type uploads are rejected
  fail-closed before storage.

## Verification

- `make verify` including the retention test and the oversize/invalid-upload
  negatives.
- Apply/roll back the `log_attachments` migration against a throwaway database.

## Readiness Sanity Pass

- **Product decision gaps:** none — discard-by-default with explicit-save opt-in,
  per `data-retention.md`.
- **Cross-lane impact:** security-privacy (retention) + backend-core (table,
  migration, DTO). One touched lane.
- **Security/privacy risk:** high — new retention surface + migration; mitigated
  by discard-by-default, fail-closed upload limits, and migration apply/rollback
  tests.
- **Verification path:** `make verify` (retention + upload negatives) + migration
  apply/rollback on a throwaway db.
- **Assumptions safe for autonomy:** yes — additive and reversible; coordinate
  table ownership with FTY-060 if it lands first.
- **Sizing:** 1 touched lane, 3 review_focus, 5 requires_context — within the
  scope guardrail. Carved out of the former oversized FTY-061 as the storage +
  retention slice.
