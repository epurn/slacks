---
id: FTY-135
state: ready
primary_lane: estimator
touched_lanes: []
review_focus:
  - single-dedup-append-helper
  - behaviour-preserving
  - no-source-ref-order-change
risk: low
tags:
  - estimator
  - evidence
  - source-refs
  - refactor
  - consistency
approved_dependencies: []
requires_context:
  - docs/contracts/evidence-retrieval.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-135: Route All Evidence Source-Ref Recording Through the Canonical Helper (estimator)

## State

ready

## Lane

estimator

## Dependencies

- **None to schedule.** `approved_dependencies: []` — the canonical helper
  (`evidence_utils._record_source_ref`, FTY-082) and both call sites are merged.
  This is a behaviour-preserving consistency cleanup.
- **Serialization note:** one of four estimator-lane release-audit fix-stories
  (FTY-131/132/135/137) serializing on the estimator lane by changed-file path. This
  story edits `backend/app/estimator/exercise_step.py` and
  `backend/app/estimator/label_step.py`; the others edit different estimator files,
  so there is no content overlap, but they cannot author simultaneously. **Rebase on
  whatever estimator work merges first** before opening the PR.

## Outcome

"Append a consulted source system to the run's evidence, de-duplicated" has **one**
implementation across the estimator. `evidence_utils._record_source_ref`
(`backend/app/estimator/evidence_utils.py` ~24–27) is that canonical dedup-append —
already used by `food_step` (3 call sites) and `official_step` (2 call sites) — but
two steps still hand-roll the same operation:

1. **`exercise_step.py` (~117–120)** appends to `context.source_refs` directly under
   its own inline `if version_ref not in context.source_refs:` guard, then appends
   both the MET-table version ref and the table source.
2. **`label_step.py` (~223–224)** appends the user-label source type directly under
   its own inline `if USER_LABEL_SOURCE_TYPE not in context.source_refs:` guard.

Two inline patterns for one operation invite drift (e.g. a future change to the
dedup/recording semantics landing in `_record_source_ref` and silently missing these
two copies). After this story, all five-plus source-ref recordings go through the one
helper. **Behaviour is preserved** — same source-ref strings, same de-duplication.

## Scope

- **`exercise_step._record_evidence`:** replace the inline
  `if version_ref not in context.source_refs:` block with **two**
  `_record_source_ref` calls — one for the MET-table version ref
  (`f"met_table:{MET_TABLE_VERSION}"`) and one for `MET_TABLE_SOURCE`. Each call does
  its own dedup, so the two refs are each appended-once, preserving the resulting
  `source_refs` contents. (See the Behaviour note below on the de-dup equivalence.)
  Leave the `context.assumptions` handling (the `NET_ACTIVE_FORMULA` /
  `met_table_version=` appends) **unchanged** — `_record_source_ref` records
  *source refs*, not assumptions.
- **`label_step` (~223–224):** replace the inline
  `if USER_LABEL_SOURCE_TYPE not in context.source_refs:` append with a single
  `_record_source_ref(context, USER_LABEL_SOURCE_TYPE)` call.
- **Import** `_record_source_ref` from `app.estimator.evidence_utils` in both files
  (the same import `official_step`/`food_step` already use).
- **Add/extend focused unit tests** asserting the source-ref contents and idempotency
  are unchanged for both steps (see Verification).

## Non-Goals

- **No behaviour change.** Same source-ref strings, same order of first-appearance,
  same idempotency (calling a step twice does not duplicate a ref). This is a
  consolidation, not a semantics change.
- **No change to `context.assumptions` recording** in `exercise_step` — only the
  *source-ref* appends move to the helper; the assumptions block stays as-is.
- **Do not change `_record_source_ref` itself**, its signature, or its leading
  underscore. It already serves `food_step`/`official_step`; this story makes two
  more callers use it, nothing more.
- **Do not touch `food_step`, `official_step`, `fdc.py`, or `off.py`** — they already
  route through the helper (or, for fdc/off, only use `_content_hash`).
- **No new module, contract, schema, or migration.**

## Contracts

- **None.** `docs/contracts/evidence-retrieval.md` is referenced for what a recorded
  source ref means on a run; it is **not** modified — the recorded evidence is
  byte-identical to today.

## Security / Privacy

- **None new.** No new input, endpoint, or stored field. The recorded values are the
  same content-free metadata (MET-table version/source, the user-label source type) —
  never user weight, raw text, or PII. Positive effect: centralising the recorder
  removes the latent risk of a future evidence-recording fix landing in only some of
  the copies.

## Acceptance Criteria

- `exercise_step._record_evidence` and `label_step`'s source-ref recording no longer
  contain inline `if ... not in context.source_refs:` appends; both call
  `_record_source_ref` (exercise_step **twice** — version ref and table source).
- The resulting `context.source_refs` contents and de-duplication are **identical**
  to before for both steps: an exercise run still records the MET-table version ref
  and the table source once each; a label run still records the user-label source
  type once.
- `exercise_step`'s `context.assumptions` recording is unchanged.
- **All existing `exercise_step` and `label_step` tests pass with no assertion
  edits.**
- No change to `_record_source_ref`, `food_step`, `official_step`, `fdc`, or `off`;
  no contract/schema/migration.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **Existing exercise and label step tests stay green with zero assertion changes** —
  the primary proof the consolidation is behaviour-preserving.
- **Focused unit tests (new or extended):**
  - Exercise: after resolving an exercise candidate, `context.source_refs` contains
    exactly the MET-table version ref and `MET_TABLE_SOURCE` (once each), and a
    second resolution does not duplicate them.
  - Label: after a legible label resolution, `context.source_refs` contains the
    user-label source type once, and a repeat does not duplicate it.

## Planning Notes

- **De-dup equivalence (the one thing to get right):** today `exercise_step` guards
  *both* appends behind a single `if version_ref not in context.source_refs:`, so the
  table source is appended only when the version ref is absent. Two independent
  `_record_source_ref` calls instead dedup each ref separately. These are equivalent
  in every reachable state because the two refs are always added together and the
  version ref uniquely tracks that pairing — once the version ref is present the table
  source is present too, so the per-ref guard yields the identical `source_refs`. The
  test asserting "once each, no duplicate on repeat" locks this in. (If the
  implementer constructs a contrived pre-seeded `source_refs` where only one of the
  two is present, the two-call form is the *more* correct dedup; this is not a
  reachable production state, but note it rather than treat it as a behaviour
  regression.)
- **Helper stays private:** `_record_source_ref` keeps its leading underscore — it is
  an estimator-internal helper already imported across estimator modules; no
  visibility change is warranted.
- **No evidence research:** purely an internal code-shape consistency cleanup; no
  health/nutrition/behavioural decision is involved.

## Readiness Sanity Pass

- **Product decision gaps:** none. No health, nutrition, or behavioural question —
  this is a one-helper consolidation, so no evidence research applies.
- **Cross-lane impact:** primary **estimator**, **no touched lanes** — internal to
  the estimator pipeline. **Single boundary, zero big rocks:** no public contract
  change, no schema migration / new table, no new untrusted-input trust boundary. Two
  files, both in the one serializing estimator lane.
- **Size:** `review_focus` = 3 (well under the 5 ceiling); `requires_context` = 3
  (well under 8). Clearly one small story.
- **Security/privacy risk:** low — no new input, endpoint, or stored field; the
  recorded metadata is unchanged and content-free. The refactor *reduces* latent
  drift risk by giving the recorder a single home.
- **Verification path:** `make verify` + existing exercise/label tests unchanged
  (the behaviour-preserving proof) + focused tests asserting the source-ref contents
  and idempotency.
- **Assumptions safe for autonomy:** yes — a behaviour-preserving consolidation onto
  a merged helper, with the one subtle point (the dedup equivalence) explained and
  pinned by an idempotency test. No migration, contract, UI, or external dependency.
</content>
