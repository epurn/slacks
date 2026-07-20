# Contract: Prior-Correction Food Resolution

## Purpose

The prior-correction source tier of
[food-resolution.md](food-resolution.md): how the user's own hand-corrections
become a per-user resolution source at estimate time (FTY-406) and a pickable
re-match candidate + apply surface on the correction sheet (FTY-411), including
the mobile surfacing of that candidate list (FTY-407). This page was extracted
**verbatim** from `food-resolution.md` (FTY-414, contract-only — no semantic
change); the rest of the food-resolution contract (Inputs, serving math,
routing, the USDA / barcode / official / reference / model-prior tiers) stays
there.

## Owner

estimator / contracts / backend-core / security-privacy lane (same owners as
[food-resolution.md](food-resolution.md)): the prior-correction resolver and
re-match modules named in the sections below —
`backend/app/estimator/correction_resolution.py`
(`PriorCorrectionResolveStep`, `match_prior_correction`),
`backend/app/estimator/re_match.py`, `backend/app/routers/re_match.py`,
`backend/app/schemas/re_match.py`, and the mobile consumers
`mobile/api/corrections.ts`,
`mobile/components/correction/ChangeMatchPanel.tsx`,
`mobile/components/correction/useCorrectionSheet.ts`,
`mobile/components/ui/ProvenanceIcon.tsx`.

## Prior-Correction Resolution (FTY-406)

The **prior-correction resolution step**
(`backend/app/estimator/correction_resolution.py`,
`PriorCorrectionResolveStep`) makes the user's own corrections a **resolution
source**. The `corrections` audit trail (FTY-051) was write-only telemetry — every
hand-edit was recorded and never read back at estimate time — so a food the user
had already corrected was re-guessed from scratch on the next log. The operator case:
"black coffee" first-passed a deterministic 148.8 kcal source match every time, was
auto-`re_match`ed to 4.8, then hand-edited to 3, over and over. This step closes the
loop: a candidate whose normalized name matches a food the user has already
**hand-corrected** resolves from that corrected value, short-circuiting the wrong
first guess.

It runs as a pipeline step **after** the rank-1 current-entry tiers (`user_text`,
image-label facts) and **before** the USDA/OFF food step, claiming each candidate it
resolves from `context.food_candidates` so the source tiers only see the rest — the
same claim-and-remove shape `user_text_step` uses. A candidate carrying a **barcode**
is skipped (a scan is the current entry's own explicit evidence and resolves via OFF).

### Precedence

`prior_correction` outranks every guessed source (`usda_fdc`, `open_food_facts` by
name, `official_source`, `reference_source`, `model_prior`) and sits below the
current entry's own explicit evidence (`user_text` / `user_label` / barcode). See the
tier-order note under **Interpretation loop and evidence tools** above.

### Lookup and authority (per-user, name-normalized)

- **Keying.** The candidate name is normalized with the shared saved-food rule
  (`app.normalization.normalize_text` — NFKD + diacritic fold + casefold +
  whitespace collapse), the same normalization saved-food typeahead uses. A match is
  an **exact** normalized-name equality.
- **Per-user, no cross-user leakage.** Only the acting user's own
  `derived_food_items` are read (`DerivedFoodItem.user_id`), joined to the
  `corrections` trail. Another user's correction is never consulted.
- **What counts as a confident prior correction.** Only an item carrying a
  `user_edit` correction on `calories` — the user's deliberate value override, not a
  `re_match` or an `amount_adjust` — whose parent log event is **not voided**. A
  food auto-re-matched but never hand-edited is not replayed.
- **Authoritative only on a stable value.** When several matching priors agree on the
  corrected value (or per-gram density, for a rescale) the value is authoritative;
  when they **conflict**, the priors are ambiguous and the candidate **falls through**
  to normal resolution.
- **Quantity: direct match, rescale, or fall through.** A candidate whose portion
  signature (normalized unit + amount + normalized quantity phrase, collapsing to a
  single `unportioned` sentinel) equals the prior correction's resolves to the
  corrected total **directly** (`basis = as_logged`, never re-scaled). A **different**
  quantity is **rescaled** from a mass-bearing prior (its corrected per-gram density ×
  the grams the candidate's own quantity resolves to via `resolve_grams`), recording
  the content-free `prior_correction_rescaled` assumption. When neither a direct match
  nor a safe rescale applies (e.g. a different quantity against an as-logged prior with
  no portion mass), the candidate **falls through** — so an item with no usable prior
  correction resolves exactly as today. **Never make a prior correction produce a
  worse result than today for an item with no matching correction.**

### Persistence and provenance

A resolved prior-correction item is an ordinary `resolved` `derived_food_items` row
with a user-owned `evidence_sources` row: `source_type = prior_correction`
(`SourceType.PRIOR_CORRECTION`), `source_ref = prior_correction:<content_hash>`,
`basis = as_logged`, and **no** global `products` cache row (`product_id = NULL`) —
it is per-user curated truth, not a shared source fact. The run records
`prior_correction` in `source_refs`. The read-model source descriptor labels it
"Your correction" so the client can render its provenance. The same per-user
prior-correction trail is exposed as a **pickable re-match candidate + apply surface**
by FTY-411 (see **Prior-Correction Candidate Surface + Apply (FTY-411)** below), and
consumed by the mobile correction sheet's match list (FTY-407 — see **Mobile surfacing
(FTY-407)** under that section) and the corrected-entry quick-add default (FTY-408). No
new correction row is written and the correction-writing path (FTY-051) and `re_match`
pass are unchanged; this step only **reads** the trail.

### Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| Confident stable prior correction, portion matches (or rescalable) | _(claims candidate; completes)_ | food `resolved` (`prior_correction`, `as_logged`) + `evidence_sources` (no `products`) | `processing → completed` |
| No matching prior / ambiguous priors / un-rescalable different quantity / barcode candidate | _(falls through)_ | resolved by the normal source tiers exactly as today | per the source it falls to |

### Security / Privacy

- **Per-user reads only.** `risk: medium` — correction lookups are strictly scoped to
  the acting user's rows and name-normalized; no cross-user reads. No new PII surface;
  corrections already exist.
- **No raw text.** The evidence row stores the projected facts + a content hash over
  them (mirroring `user_text`), never the raw diary phrase or item name; nothing new
  egresses.

## Prior-Correction Candidate Surface + Apply (FTY-411)

FTY-406 made a prior correction a resolution source at **estimate time only**. FTY-411
exposes the *same* per-user trail as a queryable **re-match candidate** on the
correction sheet's "Change match" boundary and gives a picked candidate a re-derivable
**apply path** — so a user whose "black coffee" re-guessed wrong can pick "Your
correction = 3" and have the corrected value applied, rather than re-deriving the wrong
guess. It reuses FTY-406's resolver end-to-end (`match_prior_correction`,
`backend/app/estimator/correction_resolution.py`), so a candidate/apply reproduces
estimate-time resolution rather than re-implementing it. FTY-411 itself carried no
mobile change, no change to estimate-time resolution logic, and no change to the USDA
candidate provider's own behaviour; the mobile surfacing landed separately in FTY-407
(**Mobile surfacing (FTY-407)** below).

### Candidate surface (list)

`POST …/derived-items/food/{item_id}/source-candidates`
(`backend/app/routers/re_match.py`, `ReMatchCapability.list_prior_correction_candidates`)
returns two sibling lists on the existing boundary:

- `candidates` — the guessed-source (USDA today) matches, **unchanged** (same shape,
  same code path, same bound — no regression).
- `prior_corrections` — the acting user's own confident prior correction for the
  **item's** normalized name, projected against the **item's own portion** with FTY-406's
  direct-match-vs-rescale rules. Each carries `source_type = prior_correction`, a
  `source_ref = prior_correction:<content_hash>` (the re-derivable reference the apply
  path echoes back — never facts), the corrected `calories` and macros as an
  `basis = as_logged` **total** (a macro the correction never supplied is `null` —
  unknown, never a fabricated `0`), and a `rescaled` flag. **Precedence:** prior
  corrections outrank every guessed source (mirroring the FTY-406 tier order), so the
  client renders `prior_corrections` **above** `candidates`.

The `prior_corrections` list is **bounded** by a hard cap
(`MAX_PRIOR_CORRECTION_CANDIDATES = 1`): FTY-406's resolver collapses an item's matching
priors to a single authoritative value (stable value / stable per-gram density; a
conflict is ambiguous and surfaces nothing), so a well-formed surface is 0 or 1. It is
strictly **per-user and name-normalized** — only the item owner's own rows are read; a
cross-user or unknown item fails closed as `404`, exactly like the USDA listing. Reads
only: no network egress, no `products` cache write.

### Apply path (re-resolve)

`POST …/derived-items/food/{item_id}/re-resolve` recognizes a
`source_ref = prior_correction:<content_hash>` and takes a **dedicated apply branch**
(`ReMatchCapability._apply_prior_correction`) *before* the `products`-cache lookup: it
re-projects the acting user's correction for the item's own portion via FTY-406's
resolver and requires the recomputed reference to **equal** the one the client echoed —
a stale or foreign reference is rejected (`422 source_not_resolvable`) and nothing
mutates (the same trust anchor as the source-cache path — the client supplies a
reference, never facts; `ReResolveRequest` is `extra = forbid`). On success it
reproduces FTY-406's result: the corrected as-logged values (direct match or per-gram
rescale, recording the content-free `prior_correction_rescaled` assumption on a rescale)
with `source_type = prior_correction` provenance and **no** `products` row
(`product_id = NULL`), re-snapshots the `*_estimated` originals, and appends the single
immutable `re_match` correction row that **supersedes** any prior `user_edit` — so the
applied item reads `is_edited = false` (its honesty comes from the user's own curated
value; `corrections.md` → `is_edited` derivation). Issues no network egress.

### Routing

| Condition | Result | Persisted |
| --- | --- | --- |
| List, confident stable prior correction (direct or rescalable) for the item's portion | one `prior_corrections` entry (bounded), above USDA `candidates` | nothing (read only) |
| List, no matching prior / ambiguous priors / un-rescalable quantity | empty `prior_corrections`; USDA `candidates` unchanged | nothing |
| List/apply, cross-user or unknown item | `404` (fail closed, no oracle) | nothing |
| Apply a `prior_correction:<content_hash>` the server re-derives (equal reference) | `200` — food `resolved` (`prior_correction`, `as_logged`) + `evidence_sources` (no `products`) + one `re_match` audit row; `is_edited = false` | as above |
| Apply a stale/foreign/un-re-derivable `prior_correction:` reference | `422 source_not_resolvable`, nothing mutated | nothing |

### Security / Privacy

- **Per-user reads and apply only.** `risk: medium` — both the candidate list and the
  apply re-derive strictly from the **acting user's** own rows, name-normalized; no
  cross-user read or apply. A foreign reference echoed at another user's item re-derives
  from the *target owner's* (empty) trail and fails closed, so no cross-user value is
  ever surfaced or applied.
- **No new PII surface, no raw text.** The apply's evidence row stores the projected
  facts + content hash (mirroring FTY-406/`user_text`), never the raw diary phrase or
  item name; the reference is a content hash, not diary text; nothing new egresses.

### Mobile surfacing (FTY-407)

The correction sheet's **Change match** panel is the client consumer of the surface
above. It invents no DTO or endpoint of its own: `listSourceCandidates`
(`mobile/api/corrections.ts`) reads **both** sibling lists from the one
`source-candidates` response — no second request — and returns them as
`{ candidates, priorCorrections }`; picking either kind applies through the same
`reResolveItem` call, since a prior correction's `source_ref`
(`prior_correction:<content_hash>`) is the re-derivable handle the apply branch
recognizes.

Rendering follows the tier order rather than flattening the two lists together, because
their facts are not comparable: a guessed candidate previews a **per-100g density**,
while a prior correction is an **`as_logged` total** for the item's own portion.

| Response | Panel renders |
| --- | --- |
| `prior_corrections` non-empty | a **"Your corrections"** group **above** the guessed matches — each row with the pencil provenance icon and `<kcal> · Your correction` (`…, adjusted for this amount` when `rescaled`) — then **"Other matches"** over the unchanged `candidates` |
| `prior_corrections` empty (no matching history) | the guessed `candidates` exactly as before FTY-407: no section headers, no added rows |
| both empty | the existing empty state ("No matches found…" / "No alternatives available.") |

A macro the correction never supplied arrives as `null` and stays unknown through the
client — rendered as `—`, never a fabricated `0`. An applied item comes back with
`source_type = prior_correction` and `is_edited = false`, which the client's provenance
map (`mobile/components/ui/ProvenanceIcon.tsx`) renders as the pencil icon with the
read-model's "Your correction" label rather than the unknown-source fallback.

Running-app evidence (light + dark candidate list, and the applied result) is in
`docs/verification/FTY-407/`.
