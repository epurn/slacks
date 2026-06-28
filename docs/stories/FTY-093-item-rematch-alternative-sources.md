---
id: FTY-093
state: ready_with_notes
primary_lane: estimator
touched_lanes:
  - backend-core
risk: high
tags:
  - estimator
  - evidence
  - corrections
  - provenance
approved_dependencies:
  - FTY-044
  - FTY-045
  - FTY-051
  - FTY-062
  - FTY-079
  - FTY-092
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/contracts/corrections.md
  - docs/contracts/estimation-jobs.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
review_focus:
  - re-resolve-recomputes-from-chosen-source-deterministic
  - provenance-honest-new-source-not-user-edited
  - item-identity-and-timeline-place-preserved
  - chosen-source-validated-server-side-no-arbitrary-egress
  - alternatives-listing-bounded-no-personal-context-egress
autonomous: true
---

# FTY-093: Item Re-match — List Alternative Evidence Sources + Re-resolve to a Chosen Source

## State

ready_with_notes

> Gated on **FTY-092** (the provenance read-model that surfaces an item's source
> in the daily-summary item DTO). FTY-093 rewrites the item's `evidence_sources`
> provenance to the new source; FTY-092's read-model is what makes that new source
> visible to the client — so FTY-093 needs **no** DTO change of its own and the
> steward must not assign it until FTY-092 merges. See **Planning Notes** for the
> pinned product decisions (the `*_estimated` re-snapshot, and re-match-is-not-a-
> `user_edit`-correction).

## Lane

estimator

## Dependencies

- FTY-044 (USDA generic-food resolution: `products` cache, `resolve_grams` +
  serving math, `evidence_sources` provenance — reused to recompute)
- FTY-045 (evidence-retrieval contract: source hierarchy, lookup status,
  normalized nutrition-fact schema)
- FTY-051 (corrections contract: the `*_estimated` snapshot columns and the
  `user_edit` value-override lever this capability is deliberately distinct from)
- FTY-062 (official-source resolution step: the pipeline that already resolves
  text → candidates → a chosen source; this story adds the "list and re-aim"
  operations on top of it)
- FTY-079 (sanitized search adapter: reused for the optional search-fallback
  candidates; no new search UX or provider)
- **FTY-092** (provenance read-model — the re-matched item reports its new source
  through the existing item DTO)

## Outcome

A user whose entry matched the **wrong food** (Fatty heard "turkey", matched
chicken) can fix it without delete-and-retype: the backend can (a) **list
alternative source matches** for an existing food item — drawn from the same
hardened providers the estimator already uses (other USDA / Open Food Facts
matches, an optional sanitized search-fallback) — and (b) **re-resolve** the item
to a caller-chosen candidate, recomputing kcal + macros from **that** source at the
item's current portion and rewriting its `evidence_sources` provenance to the new
source. The entry keeps its identity and place in the timeline, and its provenance
updates **honestly** to the new source — it is **not** marked `user_edited`,
because the value now comes from a real source, not a manual override. This is the
"Change match" lever of the §4a correction sheet (distinct from the portion stepper
in FTY-092 and from the manual value override in FTY-051).

## Scope

Two cohesive halves of one "Change match" capability on the estimator boundary —
the read half (list candidates) and the write half (re-aim to a chosen candidate).
They ship together because re-resolve may only target a candidate the listing step
surfaced (the server-side trust anchor, below); a half on its own is unusable.

### (a) List alternative source candidates for an existing item

- A new estimator capability that, given an existing `derived_food_items` row,
  returns a **bounded** list of alternative source candidates for the item's
  identity, produced by running the **existing** resolution providers (USDA FDC,
  Open Food Facts, and — when the search provider is enabled — the FTY-079
  sanitized search + FTY-062 official-source path) in a *list-candidates* mode that
  surfaces multiple energy-bearing matches rather than only the first one
  (`FATTY_FDC_MAX_RESULTS` / `FATTY_SEARCH_MAX_RESULTS` already bound the provider
  fan-out).
- Accept an **optional caller-supplied query override** (the corrected term, e.g.
  "turkey") so the user can re-aim to a different food, not just re-rank the
  original name. The override is a single item-identity string that passes through
  the **same** `sanitize_query` chokepoint (FTY-079) — item identity only, no
  profile/history/metrics, control-stripped, length-bounded.
- Each returned candidate carries: `source_type`, `source_ref`, a display name, the
  match `basis` (`per_100g` / `per_100ml` / `per_serving`), and a compact
  facts preview (e.g. calories per the basis) so the client can show the choices.
  Candidates whose facts are not schema-valid / energy-bearing are excluded (a
  `partial` lookup is not an offerable match).
- The candidate's facts are extracted/validated **server-side during listing**
  (USDA/OFF via their existing cache + clients; official-source via the FTY-078
  hardened fetch already in FTY-062). For USDA/OFF this populates/reuses the global
  `products` cache; for official-source the extracted facts are retained per
  `data-retention.md` (facts + URL + hash, never the raw page).

### (b) Re-resolve the item to a chosen candidate

- A new estimator capability that takes the existing item plus a **chosen candidate
  reference** (a `source_ref` / opaque candidate id from the listing step) — and
  **never** caller-supplied nutrition values — and re-aims the item:
  1. **Re-derive the chosen source's facts server-side** from that reference (USDA/
     OFF cache or the FTY-062 official-source path), so the client cannot inject
     facts. A chosen reference that does not correspond to a candidate the server
     can re-derive is rejected; nothing mutates.
  2. **Recompute at the current portion.** Keep the item's current `amount` /
     quantity (the FTY-092 portion is the user's choice), run `resolve_grams`
     against the **new** source's `default_serving_g`, then `scale_facts` to new
     `calories`/`protein_g`/`carbs_g`/`fat_g`, rounded 0.1 (the FTY-044 serving
     math, reused unchanged). If the new source cannot cost the current quantity
     (e.g. a count unit with no serving size), route to `needs_clarification`
     rather than fabricate — never a silent guess.
  3. **Rewrite provenance to the new source.** Update the item's `evidence_sources`
     row (`source_type`, `source_ref`, `content_hash`, `fetched_at`, the immutable
     facts snapshot, `product_id` link, `assumptions`) to the chosen source. The
     item keeps its `id`, `log_event_id`, name slot, and timeline position.
  4. **Re-snapshot `*_estimated` to the newly computed values.** A re-match is a
     fresh source-backed estimate, not a manual override, so the estimated/original
     snapshot is reset to the new source's computed values and the item is **not**
     marked `user_edited`. (See **Planning Notes** for why this differs from the
     FTY-051 "captured once" rule, which governs `user_edit` overrides.)
- Re-resolve is otherwise **deterministic**: given the same provider/cache
  responses, the same chosen reference yields the same recomputed item and
  provenance.

## Non-Goals

- The **mobile correction-sheet UI** for Change-match (FTY-100) — this is the
  backend capability + thin exposed operation only.
- The **portion / quantity stepper** (FTY-092) — that adjusts amount and preserves
  provenance; this changes the *source*.
- The **manual value override** lever (FTY-051) — a direct edit that marks the item
  `user_edited` and appends a `user_edit` correction row. Re-match is explicitly
  **not** that path and writes no `user_edit` correction.
- **Free-form new-food creation** beyond selecting among surfaced/searched
  candidates (no "type the macros yourself" here — that is the override lever).
- **Net-new search providers or a full search UX** — reuse the FTY-079 adapter and
  its sanitized single-string query; this story adds no provider and no open-ended
  browsing.
- A **second network fetch on re-resolve** — re-resolve re-derives from the
  candidate the listing step already validated/cached; it issues no fresh arbitrary
  fetch from a caller-supplied URL.
- Any **daily-summary DTO** change — the new provenance reaches the client through
  FTY-092's read-model.
- An **audit/history row for the re-match itself** — deferred; provenance carries
  the change of source honestly. (`corrections` v1 is `user_edit`-only and is for
  value overrides.)

## Contracts

- **Evidence-retrieval / estimator job contract** (`evidence-retrieval.md`,
  `food-resolution.md`): an additive **re-match capability** — a *list-alternatives*
  operation and a *re-resolve-to-chosen-source* operation — layered on the existing
  resolution pipeline. It changes **neither** the source hierarchy, the lookup-status
  vocabulary, nor the fallback rule; it reuses the normalized-fact schema, the
  serving math, and the `evidence_sources` record shape. Document the two operations
  and the server-side-only re-derive trust rule in the contract.
- **No schema migration.** Re-resolve is an in-place `UPDATE` of the existing
  `derived_food_items` resolution columns + its `evidence_sources` row (and a re-set
  of the existing `*_estimated` columns from FTY-051). No new table or column.
- The **chosen-source reference** the listing operation returns and the re-resolve
  operation consumes is a stable estimator-boundary value (a `source_ref` /
  candidate id), echoed back by reference only — never facts.
- The backend-exposed operation is a **thin pass-through** to the estimator
  capability (request validation + object-level authz + delegate); all resolution,
  recompute, and persistence logic lives in the estimator package.

## Security / Privacy

- **No new untrusted-input trust boundary.** Egress flows only through the existing
  hardened source clients — USDA/OFF clients and the FTY-078 hardened fetcher / FTY-079
  sanitized search — during the **listing** step. Re-resolve performs no fresh
  arbitrary fetch. The SSRF/egress and query-sanitization guarantees are inherited,
  not reintroduced; this story must not bypass them.
- **No personal-context egress.** The optional query override and all provider
  queries are item-identity only, through the FTY-079 `sanitize_query` chokepoint —
  no profile, body metrics, goals, history, or account identifiers (per FTY-079 /
  the evidence-retrieval data-minimization rule). A test proves no personal context
  egresses on alternatives listing.
- **Server never trusts client-supplied facts.** Re-resolve accepts a chosen
  candidate **reference** only and re-derives the facts server-side; a client cannot
  inject nutrition values through this path (that would be the FTY-051 override lever,
  which is explicitly marked `user_edited`).
- **Object-level authorization, fail-closed.** Both operations load the item scoped
  to the owning user; a cross-user or unknown item is a `404` (no existence
  disclosure, no mutation), matching the FTY-051 corrections authz posture.
- **No-raw-content retention.** Any official-source candidate stores facts + URL +
  hash + timestamp only — never the raw page/payload/OCR (per `data-retention.md`).
- Rated **high**: it drives the official-source egress path (via listing) and
  rewrites persisted evidence + derived values; the surfaces are mitigated upstream
  but the orchestration must keep them intact.

## Acceptance Criteria

- For an existing food item, the **list-alternatives** operation returns a bounded
  list of energy-bearing candidates (`source_type`, `source_ref`, display name,
  `basis`, facts preview) drawn from the existing providers, including USDA matches
  beyond the first; with an optional sanitized query override it returns candidates
  for the corrected term. Non-schema-valid / `partial` matches are excluded.
- A test proves alternatives listing egresses **no personal context** — provider
  queries carry item identity only, through the FTY-079 sanitization chokepoint.
- **Re-resolve** to a chosen candidate recomputes `calories`/macros from that source
  at the item's current portion (reusing `resolve_grams` + `scale_facts`, rounded
  0.1), rewrites the `evidence_sources` row to the new `source_type`/`source_ref`/
  facts/hash/`fetched_at`/`assumptions`, and re-sets `*_estimated` to the newly
  computed values. The item is **not** marked `user_edited` and **no** `user_edit`
  correction row is written.
- The re-matched item keeps its `id`, `log_event_id`, name slot, and timeline
  position; its provenance (via FTY-092's read-model) reports the **new** source.
- Re-resolve takes a candidate **reference** only; supplying a reference the server
  cannot re-derive (or arbitrary client-supplied facts) is rejected and nothing
  mutates.
- A re-match whose chosen source cannot cost the current quantity routes to
  `needs_clarification` (no fabricated number), consistent with FTY-044 routing.
- Cross-user / unknown item on either operation returns `404` with no mutation and
  no existence disclosure.
- Re-resolve is deterministic for the same chosen reference and provider/cache
  responses (proven with stubbed providers).
- `make verify` passes (with stubbed search/fetch providers).

## Verification

- `make verify` (the backend / estimator package verify, as run by FTY-062 and
  FTY-082), including estimator unit tests:
  - **alternatives-listing**: multiple USDA candidates surfaced (beyond the first
    energy-bearing match); query-override produces candidates for the corrected
    term; `partial`/no-energy matches excluded; bounded count.
  - **no-personal-context-egress**: the listing query carries item identity only
    through `sanitize_query` (reuses the FTY-079 assertion pattern).
  - **re-resolve determinism + recompute**: given stubbed provider/cache facts, the
    chosen reference yields the exact recomputed `calories`/macros at the current
    portion (serving-math reuse) — pinned values.
  - **provenance honesty**: after re-resolve the `evidence_sources` row reflects the
    new source, `*_estimated` is re-snapshotted to the new values, the item is not
    `user_edited`, and no `user_edit` correction row exists.
  - **identity/timeline preserved**: same `id` / `log_event_id` / position; current
    `amount` retained.
  - **trust boundary**: a chosen reference the server cannot re-derive (and any
    attempt to pass facts directly) is rejected with no mutation; re-resolve issues
    no fresh arbitrary network egress.
  - **needs-clarification**: a re-match the new source cannot cost routes to
    clarification, not a fabricated number.
  - **authz**: cross-user / unknown item → `404`, fail-closed, on both operations.
- No migration to apply (in-place updates only); assert the absence of a new
  migration is intentional in the story's review.

## Readiness Sanity Pass

- **Product decision gaps:** resolved and pinned — (1) re-resolve keeps the user's
  current portion and recomputes from the new source at that portion; (2) it
  **re-snapshots** `*_estimated` to the new values and does **not** mark the item
  `user_edited`, because a re-match is a fresh source-backed estimate, not a manual
  override (this is the honest-provenance crux and the deliberate divergence from
  the FTY-051 "captured once" rule, which governs `user_edit` overrides); (3) the
  chosen source must be a candidate the listing step surfaced, re-derived
  server-side. These are recorded in **Planning Notes**.
- **Cross-lane impact:** primary lane **estimator** (the alternatives + re-resolve
  capability, serving-math reuse, evidence rewrite). The exposed operation is a
  **thin** backend-core pass-through (validate + authz + delegate) — the estimator
  already owns `derived_food_items` / `evidence_sources` writes, so backend-core is
  a ride-along touch, not a second serializing code boundary. **Flag:** if the
  exposed endpoint grows non-trivial recompute/persistence logic, that is the split
  signal into a separate backend-core story — keep it thin.
- **Security/privacy risk:** high — drives the official-source egress path (listing)
  and rewrites persisted evidence + derived values. Mitigated by reusing the
  hardened fetch / sanitized search (no new boundary), server-side-only fact
  re-derivation (no client-supplied facts), no-raw-page retention, fail-closed
  object-level authz, and no-fabrication clarification routing.
- **Verification path:** `make verify` with stubbed providers — listing
  (multi-candidate, sanitized, no personal egress), re-resolve (deterministic
  recompute, provenance honesty, identity preserved, trust boundary,
  needs-clarification), authz.
- **Assumptions safe for autonomy:** yes — gated behind FTY-092 (enforced by the
  steward via dependencies); the recompute reuses settled FTY-044 serving math and
  the FTY-045 fact schema; the contract semantics are pinned here.
- **Sizing:** 1 primary lane + 1 ride-along (backend-core, thin pass-through);
  **5** review_focus (at the ceiling) and **7** requires_context (under the 8
  ceiling); **one** big rock — the additive estimator re-match operation. No new
  table (in-place update) and **no** new untrusted-input boundary (reuses
  FTY-078/079). The read (list) and write (re-resolve) halves are one cohesive
  boundary that cannot be usefully split, so this stays a single story within the
  guardrail. Research not warranted: the source facts come from already
  evidence-backed providers (USDA/OFF/official); no nutrition-science decision turns
  on this mechanical re-resolution.

## Planning Notes

- **Re-match vs. `user_edit` (FTY-051).** The corrections contract snapshots
  `*_estimated` exactly once and marks any value change `user_edit`. That rule
  governs the **manual override** lever. A **re-match** is a *re-resolution* to a
  different real source, so it instead **re-snapshots** `*_estimated` to the new
  source's computed values and leaves the item un-`user_edited` — the provenance
  honestly reflects the new source. Document this distinction in
  `evidence-retrieval.md` so a later reader does not "fix" it back to user_edit.
- **No re-match audit row in v1.** `corrections` stays `user_edit`-only; the change
  of source is carried by the rewritten `evidence_sources` provenance. A dedicated
  re-match audit trail is a candidate follow-up, not part of this slice.
- **Listing reuses provider fan-out already paid for.** USDA `/foods/search` and the
  search adapter already return up to `MAX_RESULTS`; today the resolver takes the
  first energy-bearing match. Listing surfaces the rest — no new provider call shape,
  just a list-mode that does not discard the alternates.
