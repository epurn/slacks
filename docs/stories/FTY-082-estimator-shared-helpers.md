---
id: FTY-082
state: merged
primary_lane: estimator
touched_lanes:
  - backend-core
risk: medium
tags:
  - estimator
  - evidence
  - refactor
  - maintainability
approved_dependencies:
  - FTY-062
requires_context:
  - docs/architecture/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/contracts/evidence-retrieval.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - single-shared-content-hash-no-divergence
  - single-shared-source-ref-recorder
  - behavior-identical-no-hash-change
autonomous: true
---

# FTY-082: Deduplicate Estimator Evidence Helpers (`_content_hash`, `_record_source_ref`)

## State

ready

## Lane

estimator

## Dependencies

- FTY-062 (the official-source step is one of the call sites being unified)

## Outcome

The evidence-fingerprint hash and the source-ref recorder each live in exactly
one place, imported by every estimator step that needs them. This removes a
correctness-risk: three independent copies of `_content_hash` can silently
diverge and produce mismatched fingerprints across evidence tiers (breaking fact
matching and cache reuse). Behavior is byte-for-byte identical to today.

## Scope

- Create a single shared home (e.g. `app/estimator/evidence_utils.py`, or an
  existing shared module such as `food_serving`/`facts` if a natural fit already
  exists — match the pattern already used for `resolve_grams` / `scale_facts`).
- Move **`_content_hash(source_ref, facts) -> str`** there as one canonical
  implementation; import it in:
  - `app/estimator/fdc.py` (was lines ~129-133)
  - `app/estimator/off.py` (was lines ~107-111)
  - `app/estimator/official_step.py` (was lines ~453-457)
- Move **`_record_source_ref(context, source_ref)`** (append-if-absent to
  `context.source_refs`) there as one canonical implementation; import it in:
  - `app/estimator/food_step.py` (was lines ~407-411)
  - `app/estimator/official_step.py` (was lines ~460-464)
- Delete the now-duplicated local definitions. Keep call sites unchanged
  otherwise.

## Non-Goals

- Any change to the hashing algorithm, the fingerprint inputs, or the resulting
  hash values — this is a pure move/dedup; existing stored hashes must remain
  reproducible.
- Unifying the per-100g conversion helpers (`_to_per_100g` / inline label
  conversion) — out of scope here.
- The `_source_type` source-tier mapping — out of scope (separate smell, not
  addressed in this story).
- Any mobile or contracts change.

## Contracts

- None. No API, DTO, job payload, or evidence schema changes; the evidence
  fingerprint value is unchanged.

## Security / Privacy

- No behavior change to any trust boundary. The hash still fingerprints
  normalized public-source nutrition facts (no user context); the source-ref
  recorder still only manipulates an in-memory list. Rated **medium** only
  because it touches multiple estimator modules; the risk is a refactor
  regression, not a new surface.

## Acceptance Criteria

- Exactly one definition of `_content_hash` and one of `_record_source_ref`
  remain in the codebase; the five former local copies are gone and import the
  shared versions.
- For identical inputs, `_content_hash` returns the **same** value it returned
  before the refactor (add/keep a deterministic test pinning a known
  (source_ref, facts) → hash so divergence is impossible).
- All existing estimator/evidence tests (fdc, off, official, food resolution)
  pass unchanged — barcode/USDA/official fingerprinting and cache-on-repeat
  behavior identical.
- `make verify` passes.

## Verification

- `make verify`, plus:
  - a deterministic `_content_hash` value test (pins the exact fingerprint for a
    fixed input so a future edit can't silently change it);
  - the existing fdc/off/official/food-step suites green (no behavior drift);
  - a grep/import check that no duplicate local definitions remain.

## Readiness Sanity Pass

- **Product decision gaps:** none — mechanical dedup with a clear target shape
  already used elsewhere in the package.
- **Cross-lane impact:** estimator (call sites) + backend-core (shared module).
  One touched lane.
- **Security/privacy risk:** medium — no boundary change; regression risk only,
  mitigated by a pinned-hash test and the existing suites.
- **Verification path:** `make verify` + pinned-hash determinism test + existing
  evidence suites.
- **Assumptions safe for autonomy:** yes — exact files/lines and the canonical
  shape are specified; no value may change.
- **Sizing:** 1 touched lane, 3 review_focus, 5 requires_context — within the
  scope guardrail. Pure refactor across 4 estimator files + 1 shared module.
