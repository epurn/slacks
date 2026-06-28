---
id: FTY-092
state: ready_with_notes
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
risk: high
tags:
  - provenance
  - corrections
  - daily-summary
  - read-model
  - nutrition-data
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/daily-summary.md
  - docs/contracts/corrections.md
  - docs/contracts/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
review_focus:
  - provenance-preserving-amount-adjust
  - is-edited-derivation-correctness
  - read-model-source-descriptor
  - object-level-authz
  - sensitive-value-no-logging
autonomous: true
---

# FTY-092: Entry Provenance in the Read-Model + Provenance-Preserving Portion Adjust

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- FTY-045 (evidence-retrieval contract: `source_type` / `source_ref` taxonomy)
- FTY-051 (corrections audit + derived-item edit: the rescale rule and the
  `corrections` table this story extends)
- FTY-071 (daily-summary / Today read-model this story enriches per item)

## Outcome

The redesigned Today timeline shows an **always-on source icon** per item and a
**"✎ edited"** marker, and the correction sheet's portion stepper lets a user
change the amount (1 cup → 1.5 cups) and have kcal/macros recompute **without**
marking the item user-edited (the design's "fixing the amount does not turn the
item into a manual override", §4a). This story delivers the backend half of both:
(1) the Today/daily read-model exposes, per item, a **source descriptor** and an
**`is_edited`** flag so the mobile client renders the source icon + ✎ without
joining three tables itself; and (2) editing an item's **amount** becomes a
**provenance-preserving** adjustment — it recomputes values proportionally but
keeps the original evidence/source and leaves the item un-edited, distinct from a
direct **value override**, which stays a user edit. No mobile UI here (FTY-098/100).

## Scope

### 1. Per-item provenance in the Today/daily read-model

- Today, an item's provenance is split across tables — `evidence_sources`
  (`source_type` / `source_ref`, linked per item via `derived_food_item_id`),
  the paired `value` / `value_estimated` columns on `derived_food_items`, and the
  append-only `corrections` rows. The read-model the timeline consumes carries
  **no** per-item source or edit signal, so a client would need a three-way join
  to render the source icon + ✎.
- Add to the **derived food/exercise item read DTO** (the per-item shape the Today
  timeline reads — the same item DTO `corrections.md` returns from its `PATCH` and
  whatever read path lists a day's items; see Planning Notes on locating every
  read path) two fields, computed server-side:
  - **`source`** — a small descriptor the client renders directly:
    - `source_type` — the `evidence-retrieval.md` hierarchy enum on the item's
      `evidence_sources` row (`trusted_nutrition_database`, `product_database`,
      `official_source`, `user_label`, `model_prior`);
    - `label` — a human, display-ready string mapped deterministically from
      `source_type` / `source_ref` (e.g. "USDA", "Open Food Facts", "Label scan",
      the official-source host, "Estimated"), so the client maps icon + text from
      one field rather than re-deriving it;
    - `ref` — the `source_ref` string (`usda_fdc:<id>`, `open_food_facts:<barcode>`,
      `official_source:<url>`, `user_label:<hash>`, `model_prior`) for the sheet's
      deeper provenance line.
    - A `model_prior` item surfaces its `source_type` plainly so the client can
      render the "≈ rough estimate · make it exact" treatment (§4a) — the
      descriptor is sufficient to distinguish a rough estimate from a sourced match.
  - **`is_edited`** — a boolean, **true iff the item carries at least one
    value-override correction** (see §2 for the exact definition). A never-edited
    item and an item that has only been **amount-adjusted** are both `false`.
- The descriptor is **read-only and derived** — no new persisted provenance column,
  no de-normalization. It is computed from the existing `evidence_sources` row and
  the `corrections` history at read time.

### 2. Provenance-preserving portion / amount adjustment

- Redefine the FTY-051 **quantity/amount edit** as a **provenance-preserving
  adjustment** rather than a value override:
  - Editing an item's `quantity`/amount still recomputes calories/macros
    proportionally by the existing deterministic ratio rescale
    (`ratio = new / old`, rounded to 0.1) — the math is unchanged.
  - The resulting `corrections` rows (the `quantity` change **and** each rescaled
    field) are tagged with a **new `CorrectionSource` value, `amount_adjust`**, not
    `user_edit`. They remain an honest immutable audit trail of the change.
  - The item's **evidence/source is unchanged**: the `evidence_sources`
    `source_type` / `source_ref` snapshot stays exactly as resolved. A portion fix
    is not a re-resolution and never rewrites provenance.
  - The item's `is_edited` stays **false**.
- A **direct value override** (editing `calories`, a single macro, or
  `active_calories`) is unchanged from FTY-051: it keeps `source = user_edit`,
  appends exactly one correction row, does not change the amount, and now sets
  `is_edited` **true** (the advanced third lever / ✎, §4a).
- **`is_edited` definition (the load-bearing distinction):** an item is edited iff
  there exists a correction for it whose `source == user_edit` (a value override).
  `amount_adjust` corrections never make an item edited. This is what lets a 1 cup →
  1.5 cups portion fix recompute the numbers while the item keeps its original
  source icon, and a manual "300 → 280 kcal" override carries the ✎.

### Contract updates

- **`corrections.md`** — add the `amount_adjust` `CorrectionSource` value; redefine
  the quantity-edit rescale to tag its rows `amount_adjust` (not `user_edit`) and to
  leave provenance untouched; document the `is_edited` derivation (presence of any
  `user_edit` correction) as the canonical rule.
- **`daily-summary.md`** — document the per-item provenance read shape (the `source`
  descriptor + `is_edited`) on the Today/daily item read-model, so consumers
  (mobile, FTY-098/100) have a named contract for the source icon + ✎.

## Non-Goals

- **Change-match / re-resolution to a different source** (misheard "turkey" →
  "chicken"), which *does* update provenance honestly — that is **FTY-093**.
- **Macro targets** and any target provenance — **FTY-094**.
- **Any mobile UI**: the timeline source icon, the ✎ marker, and the portion
  stepper sheet — **FTY-098 / FTY-100** consume this contract.
- Re-running the estimator or any LLM on an amount adjust — adjustments stay a
  deterministic rescale (FTY-051 discipline).
- New persisted provenance/summary columns or a de-normalized read table — the
  descriptor and `is_edited` are computed reads.
- Changing the daily-summary **aggregate** totals math (FTY-071) — this enriches the
  per-item read shape only.

## Contracts

- **`corrections.md`** (public contract change): a new `CorrectionSource` value
  `amount_adjust`; the quantity-edit rescale re-tagged `amount_adjust` and declared
  provenance-preserving (evidence untouched); the `is_edited` derivation rule. The
  value-override path (`user_edit`, single row, `is_edited = true`) is unchanged.
- **`daily-summary.md`** (read-model contract): the per-item `source` descriptor
  (`source_type`, `label`, `ref`) and `is_edited` flag added to the Today/daily item
  read shape, consumed by the mobile timeline/sheet (FTY-098/100).
- **Reads, does not redefine:** the `evidence-retrieval.md` `source_type` /
  `source_ref` taxonomy and `food-resolution.md` derived-item + `evidence_sources`
  shapes (the descriptor is mapped from these); the FTY-051 rescale math and
  snapshot columns; the FTY-071 finalized-state filter and object-level authz.

## Security / Privacy

- The read-model exposes **only the authenticated user's own** items. Object-level
  authorization on every read path, failing closed as `404` on cross-user access
  (no existence oracle), mirroring `daily-summary.md` / `log-events.md`. Proven by a
  negative authorization test.
- The `source` descriptor and `is_edited` flag are derived from the user's own
  `evidence_sources` + `corrections`; **no other user's data is reachable**, and the
  `evidence_sources` global-vs-user split (`evidence-retrieval.md`) is respected —
  only user-owned provenance is read, no cross-user cache leakage.
- `source_ref` for an `official_source` item is the **URL only** (already the stored
  shape) — no headers, body, or query secrets are surfaced.
- Item values, macros, and provenance refs are **sensitive personal nutrition data**:
  never logged; logs use user/item ids, not values (per `security-baseline.md`).
- **No new untrusted input and no new trust boundary**: this is a read-model
  exposure of already-resolved, already-stored data plus a re-tagging of an existing
  deterministic edit path. The amount adjust takes the same validated `quantity`
  input FTY-051 already bounds.
- Rated **high**: it changes the public corrections semantics and the read contract
  for sensitive nutrition data, and the `is_edited` distinction is trust-bearing (a
  wrong flag mislabels provenance to the user) — even though it adds no migration of
  a new table and no external egress.

## Acceptance Criteria

- The Today/daily item read DTO exposes, per item, a `source` descriptor
  (`source_type`, display `label`, `ref`) derived from the item's `evidence_sources`
  provenance, and an `is_edited` boolean — so a client renders the source icon + ✎
  without joining `evidence_sources` / `derived_items` / `corrections` itself.
- **`is_edited` is correct across three cases**, each tested: a never-edited item →
  `false`; an item that has **only** been amount-adjusted → `false`; an item with a
  **value override** (`user_edit`) → `true`.
- **Amount adjust preserves provenance:** editing an item's `quantity` recomputes
  calories/macros by the FTY-051 ratio rescale, tags the resulting correction rows
  (`quantity` + each rescaled field) `amount_adjust` (not `user_edit`), leaves the
  `evidence_sources` `source_type` / `source_ref` unchanged, and leaves `is_edited`
  `false`. Proven by a single test asserting the rescaled values, the
  `amount_adjust`-tagged rows, unchanged provenance, and `is_edited = false`.
- **Value override marks edited:** a direct edit to `calories` / a macro /
  `active_calories` keeps `source = user_edit`, appends exactly one correction row,
  does not change the amount, and sets `is_edited = true` — proven by a test
  contrasting it with the amount-adjust case.
- A `model_prior` item surfaces its `source_type` (and a "rough estimate" `label`)
  so the client can render the "≈ rough estimate · make it exact" treatment.
- The read-model returns only the owner's items; a cross-user read fails closed
  (`404`, negative authorization test); a missing/invalid token returns `401`.
- Values and provenance refs are never logged.
- If a `CorrectionSource` enum migration is required for `amount_adjust`, it applies
  (`alembic upgrade head`) and rolls back cleanly against a throwaway database. No
  backfill is performed (pre-v1, no production data); the new semantics apply going
  forward.
- `make verify` passes.

## Verification

- Run `make verify` (API + corrections + read-model + authz tests).
- `is_edited` derivation tests: never-edited → `false`; amount-adjusted-only →
  `false`; value-overridden → `true`.
- Provenance-preserving amount-adjust test: assert rescaled values, the
  `amount_adjust`-tagged correction rows, unchanged `evidence_sources` provenance,
  and `is_edited = false`.
- Value-override test: assert `user_edit` source, single correction row, unchanged
  amount, and `is_edited = true` — contrasted with the amount-adjust case.
- Source-descriptor mapping test: each `source_type` / `source_ref` maps to the
  expected `label` + `ref`; a `model_prior` item surfaces the rough-estimate
  descriptor.
- Negative authorization test proving a cross-user read fails closed (`404`), plus a
  `401` test for missing/invalid token.
- Apply / roll back the `CorrectionSource` enum migration against a throwaway
  database if one is required.

## Planning Notes

- **Locating the read paths.** The provenance descriptor + `is_edited` must appear
  on every read path that surfaces a Today timeline item — at minimum the
  derived-item DTO defined in `food-resolution.md` / returned by the `corrections.md`
  `PATCH`, and any day-listing read the timeline consumes. The author should add the
  fields to the shared item DTO/serializer so all read paths inherit them, rather
  than patching one endpoint. Documenting the shape in `daily-summary.md` is the
  read-model contract anchor; FTY-071's aggregate totals are untouched. Non-blocking.
- **`amount_adjust` storage.** `CorrectionSource` is the existing `source` field on
  `corrections` (FTY-051). Adding `amount_adjust` is additive — a new enum value (an
  `ALTER TYPE … ADD VALUE` migration if it is a PG enum, or no migration if stored as
  a string). Either path is acceptable; if a migration is added it must apply/roll
  back. Non-blocking which storage form.
- **`is_edited` is derived, not stored.** It is computed from the presence of a
  `user_edit` correction, so it never drifts from the audit trail and needs no
  backfill. If a read-time existence check per item is a performance concern on long
  timelines, an indexed exists-query or a per-day batched lookup is acceptable — keep
  it a derived read, not a denormalized column. Non-blocking.
- **Defensive null source.** A finalized item should always have an `evidence_sources`
  row (model-prior included, per the Fallback Rule). If a record is absent, surface a
  null/unknown descriptor defensively rather than failing the read. Non-blocking.
- **Clean break.** FTY-051 currently tags quantity-rescale corrections `user_edit`,
  which would wrongly mark a portion fix as edited. There is no production data, so
  this is a clean redefinition with no migration of existing rows. Note the behaviour
  change in the PR.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking. The design (§4 source icon + ✎; §4a
  portion-first, provenance-preserving) fixes the behaviour; the `is_edited`
  definition (any `user_edit` correction), the `amount_adjust` tagging, and the
  descriptor fields are specified. Read-path wiring, enum storage form, and the
  derived-`is_edited` query shape are documented non-blocking notes.
- **Cross-lane impact:** one serializing boundary — **backend-core**. `contracts`
  (corrections.md + daily-summary.md edits documenting this lane's work) and
  `security-privacy` (own-items-only read) ride along as touched lanes, matching the
  FTY-051 / FTY-071 precedent; no second code-ownership lane. No mobile work (that is
  FTY-098/100, which consume this contract).
- **Security/privacy risk:** high — sensitive nutrition data, public corrections
  semantics change, and a trust-bearing `is_edited` flag; mitigated by own-items-only
  object-level authz (fail-closed `404`, negative test), no value logging, URL-only
  `official_source` ref, and no new untrusted input or egress.
- **Verification path:** `make verify` + the three `is_edited` cases +
  amount-adjust-preserves-provenance test + value-override-marks-edited test +
  descriptor-mapping test + negative authz/`401` tests + enum migration rollback if
  one is added.
- **Assumptions safe for autonomy:** yes — all open items (read-path location, enum
  storage, derived-`is_edited` query, defensive null source) are documented
  non-blocking choices; the prerequisites (FTY-045/051/071) are merged.
- **Sizing:** one boundary (backend-core); one coupled public-contract big rock (the
  `is_edited` read flag is *defined by* the amount-adjust-vs-override tagging, so the
  read-model and the corrections-semantics changes cannot be split without leaving a
  flag with no meaning). No new table, no new untrusted-input boundary. `review_focus`
  = 5 (at the ceiling), `requires_context` = 7 (within 8). Within the scope guardrail;
  not split. Change-match (FTY-093) and macro targets (FTY-094) are deliberately
  carved out as separate dependents.
- **Evidence research:** not warranted — the decisions here are product/architecture
  (read-model shape, correction-source semantics, provenance preservation), already
  settled by `ux-design.md` §4/§4a; no health/nutrition/behavioural question whose
  answer being wrong carries real cost hinges on this story.
