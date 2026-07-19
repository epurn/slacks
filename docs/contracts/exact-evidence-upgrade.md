# Contract: Exact Evidence Upgrade

## Purpose

The **exact evidence upgrade** is the correction sheet's `Make it exact` lever
(`docs/design/ux-design.md` §4a): for a **low-trust or incomplete food item**,
the user supplies product evidence — a typed or scanned barcode, or a
nutrition-label photo — Slacks builds a server-held **proposal**, previews the
resulting item, and **applies it in place** only after the user confirms. It is
**source replacement, not a manual value override**, and covers **food items
only**. This page fixes the proposal read shape (`proposal_ref` / `kind` /
`quality` / `failure_reason` / preview / costability), the exact-vs-fallback
quality rules, and the re-match apply semantics; it introduces no new source
tier, lookup status, or evidence-record field.

## Owner

contracts lane, with backend / mobile touch. The contract lives here
(`docs/contracts/exact-evidence-upgrade.md`). Backend implementation:
`backend/app/estimator/exact_evidence.py`,
`backend/app/estimator/barcode_proposal.py`,
`backend/app/estimator/label_proposal.py`,
`backend/app/schemas/exact_evidence.py`,
`backend/app/services/exact_evidence.py` (FTY-307–FTY-309); mobile consumption:
`mobile/api/exactEvidence.ts` (FTY-310–FTY-313). The entry-point routing,
amount-preservation, costability, and no-silent-exact rules live in
`food-resolution.md` (**Exact Evidence Upgrade Routing — FTY-306**); the audit
semantics in `corrections.md`; label-image retention in `label-upload.md` /
`log-attachments.md`.

## Version

2 (FTY-396, contract only): extracts this sub-contract **verbatim** from
[evidence-retrieval.md](evidence-retrieval.md) into its own page — no semantic,
wording, field, table, vocabulary, or ordering change. `evidence-retrieval.md`
keeps its `## Exact Evidence Upgrade — FTY-306` heading as a forwarding pointer
to this page, so existing references naming that section still resolve.

1 (FTY-306, contract only): defines the exact evidence upgrade — the correction
sheet's `Make it exact` lever — as an in-place source replacement for low-trust
or incomplete food items: a server-built barcode/label proposal (opaque
`proposal_ref`, `kind`, `quality` `exact`/`fallback`/`none`, `failure_reason`,
preview, costability flag) that the user previews and explicitly applies, with
re-match semantics (provenance rewrite, `*_estimated` re-snapshot, one `re_match`
audit row, `is_edited = false`). No new source tier, lookup status, normalized
fact schema, or retention change. Backend implementation is FTY-307–FTY-309;
mobile consumption is FTY-310–FTY-313.

## Exact Evidence Upgrade — FTY-306

The **exact evidence upgrade** is the correction sheet's `Make it exact` lever
(`docs/design/ux-design.md` §4a): for a **low-trust or incomplete food item**, the
user supplies **product evidence** — a typed or scanned barcode, or a
nutrition-label photo — Slacks builds a server-held **proposal** from that
evidence, previews the resulting item, and **applies it in place** only after the
user confirms. Nothing about the selected item changes until apply; there is no
automatic replacement.

It is **source replacement, not a manual value override**: applying a proposal
uses the same re-resolution semantics as **Item Re-match — FTY-093** (provenance
rewrite, `*_estimated` re-snapshot, one `re_match` audit row, `is_edited = false`
until a later manual override — `corrections.md`), differing only in where the new
source comes from. **Change match** fixes a *wrong* source by search; **Make it
exact** asks the user for *product evidence* and then applies the resulting exact
source — or an honestly-labelled fallback — explicitly. It covers **food items
only**; exercise items never expose this path (an exercise burn has no evidence
source to upgrade).

This section is the contract; the backend implementation is split into
**FTY-307–FTY-309** and the mobile consumption into **FTY-310–FTY-313**. The
entry-point routing, amount-preservation, costability, and no-silent-exact rules
for the existing-item flow live in `food-resolution.md` (**Exact Evidence Upgrade
Routing — FTY-306**); the label-image retention boundary lives in
`label-upload.md` / `log-attachments.md`.

### Eligibility (which items offer `Make it exact`)

Only **low-trust or incomplete** food items are eligible for the entry point:

- **`model_prior`** items — rough/default-prior estimates, including `as_logged`
  rough totals (FTY-301);
- **`user_text`** items with missing or roughly gap-filled macros — a user-stated
  calorie total whose macros are `unknown`/`null` in the read shape, or carry a
  non-null `estimate_basis`: `comparable_reference` for the comparable aggregate
  (FTY-281), `reference_source` for the single-source reference lookup, or
  `model_prior` for the model-prior cold-pass (FTY-350);
- **`reference_source`** items — rough estimates transcribed from searched
  public reference pages, including snippet-derived records (FTY-314).

Already source-backed items — `user_label`, `product_database`,
`trusted_nutrition_database`, `official_source` — keep the normal correction
levers (amount stepper, Change match, manual value override) and **do not** show
the exact-upgrade nudge. Eligibility is derived from fields the **public read
model already contracts** (`daily-summary.md` → **`source` descriptor**): the
descriptor's `source_type` and `estimate_basis` plus the item's nullable macro
facts — no new persisted flag, no new read-model field, and no new
source-hierarchy tier. `daily-summary.md` contracts the matching client-side
nudge signal in the same terms, and the propose route evaluates the same rule
server-side from the item's `evidence_sources` row (rejecting an ineligible
target with `not_upgradeable`, `food-resolution.md`), so the rendered nudge and
the server-validated eligibility can never disagree. For a `user_text` macro
gap-filled by the comparable aggregate, a single-source reference lookup, or the
model-prior cold-pass, `estimate_basis` is still **read-time-derived** from the
item's own content-free assumptions marker and records only the fill tier; it
adds no persisted column and does not change the item's `source_type`, which
stays `user_text`.

### Proposal (read shape)

A proposal is built **server-side** from the supplied evidence and held
server-side as the trust anchor apply re-derives from; the client receives a
preview plus an opaque reference, never a writable fact set. Stable fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `proposal_ref` | string | **Opaque, server-generated** reference to the server-held proposal — the only key `apply` accepts, never nutrition facts supplied by the client. Scoped to the owning user **and** the targeted item; a ref that does not resolve to a server-held proposal for that user + item is rejected with no mutation. |
| `kind` | enum | `barcode` \| `label` — which evidence kind produced the proposal. |
| `quality` | enum | `exact` — the evidence resolved through its exact source (barcode → `product_database`, label → `user_label`); `fallback` — exact evidence failed but a lower-trust estimator source produced a better rough result (see **Fallback quality** below); `none` — neither exact evidence nor a fallback could be produced (nothing applyable). |
| `failure_reason` | string \| null | `null` for `exact`; **required** for `fallback` and `none`. A **closed, content-free** label (e.g. `barcode_no_match`, `barcode_invalid`, `label_unreadable`, `not_a_label`, `source_unavailable`, `no_usable_facts`; the concrete vocabulary is fixed by FTY-307/FTY-308) suitable for calm client copy such as "No exact match from that barcode" — never raw provider output, OCR text, fetched content, or image data. |
| `preview` | object \| null | The would-be item, costed at the **current amount** when possible: the read-model `source` descriptor the applied item would carry (`source_type`, display `label`, `ref`, optional `estimate_basis` — `daily-summary.md`), `calories` / `protein_g` / `carbs_g` / `fat_g`, the current `amount`, and the proposal's serving label. `null` when `quality = none`. When the current amount cannot be costed, the preview carries the source facts on the proposal's own basis instead of invented totals (see the flag below). |
| `can_cost_current_amount` | bool | Whether the proposal's source can cost the item's **current** amount (serving math resolvable). When `false`, apply requires an explicit amount from the user — the contract forbids applying with a silently guessed portion (`food-resolution.md`). |

A `quality = none` proposal is a **failure read**, not an applyable object: it
carries the `failure_reason` for calm client copy and nothing else to apply. The
preview is a **read projection** — previewing creates no correction row, no
evidence rewrite, and no item mutation.

### Exact quality (no new tier)

An **exact** proposal resolves through the existing exact sources and reuses
their record shapes unchanged:

- **Barcode** — the hardened Open Food Facts path (`food-resolution.md`
  **Barcode Source — FTY-060**): normalized digits, GTIN length check, hardened
  fetch, per-100g canonicalisation, plausibility bound, global `products` cache
  row. Applying yields `source_type = product_database`,
  `source_ref = open_food_facts:<barcode>`.
- **Label** — the schema-validated label extraction path (`label-extraction.md`):
  image validated as data, `NutritionPanel` extraction, deterministic
  per-serving → per-100g math. Applying yields `source_type = user_label`,
  `source_ref = user_label:<content_hash>`.

### Fallback quality (plainly not exact)

When exact barcode/label evidence fails (OFF miss, unreadable label, provider
unavailable, implausible facts) but the estimator can still produce a **better
rough result** from a lower-trust source — a searched reference page, a
comparable-reference aggregate, or a model-prior estimate over the evidence's
product identity — the proposal remains applyable with `quality = fallback`. A
fallback:

- carries its true low-trust provenance: `reference_source`, `model_prior`, or
  the `comparable_reference` estimate-basis marker — **never** `product_database`
  or `user_label`;
- carries a visible `failure_reason` naming why exact evidence failed, and its
  preview `source` descriptor shows the rough source label the applied item will
  show;
- **must never be presented as exact** — not in the proposal `quality`, not in
  the preview `source` descriptor, not in the applied item's provenance. The
  source descriptor and failure reason are part of the user-visible trust
  boundary;
- when applied, updates the item in place but keeps it **visibly
  rough/incomplete** (it stays exact-upgrade-eligible, and the read model keeps
  rendering its rough provenance).

### Source replacement semantics (apply)

Applying a proposal accepts **only** the opaque `proposal_ref` plus an optional
amount adjustment (`food-resolution.md` owns the operation shape). It:

1. **preserves the item's identity** — `id`, `log_event_id`, name slot, and
   timeline position are unchanged; the log event is untouched;
2. **preserves the current amount by default**; an optional user-supplied amount
   adjustment from the preview is applied **before** costing;
3. **re-derives the facts server-side** from the server-held proposal (the same
   trust posture as re-match re-resolve: the client cannot inject facts, and
   apply issues no fresh evidence egress);
4. **rewrites the item's `evidence_sources` provenance in place** to the
   proposal's source — `source_type`, `source_ref`, `content_hash`, `fetched_at`,
   the immutable facts snapshot on the source's honest `basis`, `product_id`
   link (barcode) or `NULL` (label/fallback), `assumptions`, and a reset
   `field_provenance` consistent with the new source (no stale per-field origin
   map or stale `as_logged` basis survives the rewrite, per FTY-316);
5. **re-snapshots `*_estimated`** to the newly computed values — a fresh
   source-backed estimate, not a manual override;
6. **appends one immutable `re_match` correction row** (keyed on `calories`),
   which supersedes any prior `user_edit`, so the applied item reads
   `is_edited = false` until a later genuine manual override (`corrections.md`).

### Authorization / privacy

- **Object-level, fail-closed.** Every proposal and apply operation is scoped to
  the owning user and item; a cross-user or unknown user/item id is `404` (no
  existence disclosure, no mutation), matching the corrections/re-match posture.
- **Untrusted inputs.** The barcode string and the label image are untrusted
  input. Barcode lookups stay server-side through the existing hardened OFF path;
  label images stay server-side through the existing validation/extraction path.
  The client supplies a barcode, an image, an optional `save` flag, and later the
  opaque `proposal_ref` plus an optional amount — **never calories/macros**.
- **Retention unchanged.** Raw label images follow the existing
  discard-by-default rule (`label-upload.md`, `log-attachments.md`,
  `docs/security/data-retention.md`): discarded after extraction unless the user
  explicitly opts in to saving. No image bytes, URIs, OCR text, raw provider
  output, or nutrition values are logged; evidence rows store extracted facts +
  refs + hashes only, exactly as this contract already requires.
- **Proposal retention is bounded.** The server-held proposal holds only the
  extracted/validated facts, source ref, and content hash needed for apply —
  never the raw image, raw provider output, or OCR text — is scoped to the
  owning user + item, and is short-lived (an unapplied proposal expires; it is
  not durable user history). The concrete storage mechanism is fixed by
  FTY-307–FTY-309, which document its retention per the
  `docs/security/data-retention.md` PR requirement. **As built (FTY-307):** the
  proposal is **not stored** — the `proposal_ref` is a stateless, HMAC-signed opaque
  reference (keyed by the existing application secret) whose payload *is* the bound
  proposal (owner, item, kind/quality, source type/ref, per-100g facts + basis,
  costability metadata, issued/expiry replay guard). Apply verifies the signature,
  expiry, and owner+item binding server-side and re-derives the facts from the
  verified payload; a tampered, expired, or wrong-user/wrong-item reference is
  rejected with no mutation. No new table, no migration, and no server-side proposal
  row — see `docs/security/data-retention.md`.
