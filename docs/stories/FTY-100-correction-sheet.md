---
id: FTY-100
state: ready
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - mobile
  - correction
  - sheet
  - provenance
  - clarify
  - trust
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/corrections.md
  - docs/contracts/evidence-retrieval.md
  - docs/contracts/saved-foods.md
review_focus:
  - accessibility
  - provenance-honesty
  - recompute-correctness
  - detent-state-management
  - light-dark-parity
autonomous: true
---

# FTY-100: Correction / Detail Sheet (Mobile)

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-097 (design system: tokens, type ramp, accent, light/dark surfaces) — the
  sheet is built against these tokens.
- FTY-092 (provenance read-model + provenance-preserving amount adjust) — supplies
  the per-unit/provenance read-model and the amount-adjust endpoint the primary
  lever consumes; recompute stays provenance-intact server-side.
- FTY-093 (item re-match / alternative sources) — supplies the alternative-source
  matches + search and the re-aim endpoint the "Change match" lever consumes.
- FTY-051 (existing derived-item edit endpoint, `corrections.md`) — the advanced
  direct value override lever.
- FTY-052 / FTY-053 (existing save-as-food, `saved-foods.md`) — the manual
  "Save as food" action reuses this surface.
- Consumes the existing parse `needs_clarification` state for clarify-mode.

Note: FTY-098 (the Today timeline that launches the sheet) is a separate mobile
story; this sheet is built and tested as a standalone presentable component so it
does not block on the timeline.

## Outcome

The universal slide-up **detail / correction sheet** (UX design §4a) — the heart of
Fatty's trust-and-correct wedge — exists on mobile. From any timeline item the user
can open one native iOS sheet that shows where the number came from and lets them
fix it without a page change or a delete-and-retype, in four levers ordered by how
people actually mis-log:

1. **Primary — portion / quantity-first.** An amount stepper ("1 cup" → "1.5 cups");
   kcal + macros recompute live from the source's per-unit data via FTY-092, so
   provenance stays intact (fixing the amount is **not** a manual override).
2. **Wrong-match — "Change match".** A distinct affordance that reveals alternative
   source matches inline plus a search fallback (FTY-093); picking a new food re-aims
   the entry and recomputes from the new source, with provenance updated honestly.
3. **Advanced — direct value override.** Editing kcal or a macro directly via the
   FTY-051 edit endpoint, which marks the item user-edited ("✎ edited").
4. **Clarify-mode (for "needs a detail")** — Fatty's specific question with
   quick-pick chips + free-text fallback; one tap resolves and the entry starts
   counting.

An **evidence / provenance block** (source line + the user's own words, with a
"≈ Rough estimate · › Make it exact" nudge into Change-match for low-trust items)
and a manual **"Save as food"** action complete the sheet. Detents: medium by
default, large on demand. Calm, native, never fabricates a number.

## Scope

- **Native iOS slide-up sheet** built against FTY-097 tokens (frosted material,
  content dims behind, amber accent for actions/progress), presentable from any
  timeline item with the item's id/type.
- **Amount stepper (primary lever).** Render the current amount + unit; stepping
  calls FTY-092's amount-adjust endpoint and renders the recomputed kcal + macros
  returned by the server **in place** (skeleton/shimmer → value, no layout shift,
  no client-side nutrition math). Provenance icon/label is unchanged by an
  amount adjust.
- **"Change match" lever.** A distinct affordance (separate from the stepper) that
  reveals FTY-093's alternative source matches inline plus a search fallback;
  selecting a candidate re-aims the entry via FTY-093 and renders the new
  provenance + recomputed values returned. Grows the sheet to the large detent.
- **Advanced direct value override.** Editing kcal / a single macro via the
  existing FTY-051 `PATCH` edit endpoint (canonical units), surfacing the
  contract's validation/error shapes; the item then carries the "✎ edited"
  provenance. Grows to the large detent.
- **Evidence / provenance block.** Show the source label + icon and matched entry
  name (e.g. "🔍 USDA · Turkey breast, roasted", "📷 Label scan", "✎ You edited")
  from the FTY-092 read-model, plus the user's original phrase quoted. A
  model-prior / low-confidence result renders distinctly ("≈ Rough estimate") with
  an explicit "› Make it exact" nudge that opens Change-match.
- **Clarify-mode.** When the item is in the parse `needs_clarification` state,
  render Fatty's question with the likely answers as tappable chips plus a "type
  your own" free-text field; one selection resolves the clarification, the entry
  recomputes and begins counting. Never auto-fill the missing detail.
- **Save as food.** A manual action that saves the current (corrected) item with
  its per-unit definition via FTY-052/053 so it surfaces in the Log typeahead
  later. No auto-prompt, no nagging.
- **Detents.** Open at a medium detent (header + amount + evidence + primary
  actions); grow to large only when Change-match search or the override fields
  open, keeping the timeline partly visible for the quick fix. Honour Reduce
  Motion (signature beats degrade to simple fades).
- **States.** Loading (skeleton in place), recompute-in-flight, endpoint
  success/failure for each lever (gentle, retryable, never a fabricated number),
  and the "edited"/"rough estimate" provenance variants — in both light and dark.

## Non-Goals

- The backend amount-adjust / provenance read-model (FTY-092) and the re-match /
  alternative-source endpoints (FTY-093) themselves — this slice consumes them.
- The Today timeline / item cluster that launches the sheet (FTY-098).
- The design tokens / type ramp / accent definition (FTY-097).
- Any new server contract, endpoint, schema, or estimator change — this is a
  mobile UI slice over already-specified surfaces.
- Smart "save this for next time?" suggestions (v2, per design doc).
- Exercise-item correction beyond what the shared edit surface already provides;
  the sheet's primary lever targets food portion/quantity.

## Contracts

- **None new.** Consumes:
  - `corrections.md` — the FTY-051 derived-item edit endpoint (advanced override)
    and the FTY-092 provenance-preserving amount-adjust extension.
  - `evidence-retrieval.md` — the provenance read-model (`source_type`,
    `source_ref`, matched name, status/`assumptions`) and the FTY-093
    alternative-source matches + re-aim.
  - `saved-foods.md` — the FTY-052/053 save-as-food surface.
- Introduces no DTO, field, or endpoint of its own.

## Security / Privacy

- The sheet only reads and edits **the authenticated user's own items**, over the
  authenticated API (TLS); object-level ownership and fail-closed `404` are
  enforced server-side by the consumed endpoints (`corrections.md` Authorization).
- No new trust boundary: Change-match search queries and provenance display flow
  through the existing FTY-093 / evidence-retrieval boundaries, which already
  enforce data minimization (item identity only, no profile/history egress) and
  treat fetched/source content as untrusted. The mobile sheet adds no provider
  egress of its own.
- **Sensitive values never logged.** Food/macro values, the user's quoted phrase,
  and clarification answers are not written to logs, analytics, or error output;
  errors carry HTTP status + a stable code only (mirroring the existing clients).
- No additional sensitive on-device persistence beyond normal app state needed to
  render and edit the open sheet.
- Medium risk: edits user data through several endpoints and must display
  provenance honestly (never fabricate, never silently re-label), but adds no new
  server logic and no new trust boundary.

## Acceptance Criteria

- Opening the sheet on an item renders its provenance block (source icon + label +
  matched name) and the user's quoted original phrase from the FTY-092 read-model.
- Stepping the amount calls FTY-092's amount-adjust endpoint and renders the
  **server-recomputed** kcal + macros in place; the provenance icon/label is
  unchanged (the item is not marked user-edited). No nutrition math runs on the
  client.
- "Change match" reveals FTY-093 alternative matches + search; selecting one
  re-aims the entry, the displayed provenance and values update to the new source,
  and the sheet grows to the large detent.
- A direct value override edits via the FTY-051 endpoint, the item then shows the
  "✎ edited" provenance, and the contract's validation/error shapes
  (`unknown_field`, `out_of_range`, etc.) surface as gentle retryable UI.
- A `needs_clarification` item opens in clarify-mode: Fatty's question + quick-pick
  chips + free-text fallback; resolving it recomputes the entry and it begins
  counting. No missing detail is ever auto-filled.
- A low-confidence / model-prior item renders "≈ Rough estimate" with a
  "› Make it exact" nudge that opens Change-match.
- "Save as food" persists the current corrected item via FTY-052/053; no
  auto-prompt fires.
- Detents behave: medium on open, large when Change-match search or override
  opens; the timeline stays partly visible at medium; Reduce Motion is honoured.
- Renders correctly in both light and dark; provenance icons carry VoiceOver
  labels; tap targets ≥44pt; Dynamic Type respected. Every lever has an accessible
  label.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), against mocked endpoints:
  - **Portion recompute:** stepping the amount calls the FTY-092 endpoint and
    renders the returned kcal/macros in place; asserts no client-side recompute and
    unchanged provenance.
  - **Change-match flow:** alternatives + search render; selecting a candidate
    re-aims via FTY-093 and updates provenance + values + detent.
  - **Direct override:** FTY-051 edit applies, "✎ edited" provenance shows, and the
    contract error shapes surface as retryable UI.
  - **Clarify chips:** `needs_clarification` renders question + chips + free-text;
    resolving recomputes and counts; no auto-fill.
  - **Evidence / estimate nudge:** rough-estimate variant shows "≈ Rough estimate"
    + a "Make it exact" affordance that opens Change-match.
  - **Save-as-food:** persists via FTY-052/053 with no auto-prompt.
  - **Detent transitions:** medium on open → large on Change-match/override; medium
    keeps timeline partly visible.
  - **Light + dark** snapshot/render coverage of the sheet and its variants.
  - **Accessibility:** VoiceOver labels on provenance icons and every lever; ≥44pt
    targets; Reduce Motion degradation.
- Run mobile typecheck, lint, and tests via `make verify` where wired.
- On an iOS simulator, open the sheet from a sample item and exercise each lever
  (amount, change-match, override, clarify, save) in light and dark.

## Readiness Sanity Pass

- **Product decision gaps:** none — §4a fixes the lever order (portion-first),
  the evidence block + rough-estimate nudge, clarify chips + free-text, manual
  save-as-food, and the medium→large detent rule. All four levers map to
  already-specified surfaces; no new product decision is taken here. No
  evidence/health question turns on this slice (the design doc's evidence-backed
  calls — e.g. weigh-in cadence — live in §4b, not here), so no research needed.
- **Cross-lane impact:** none. **Single boundary — mobile-core only.** It consumes
  backend surfaces (FTY-092, FTY-093, FTY-051, FTY-052/053) but writes no backend
  code, no contract, no schema, and crosses no new trust boundary, so it is not a
  big rock and does not split. Sizing: `review_focus` = 5 (at the ceiling, not
  over) and `requires_context` = 4 (well under 8) — only one limit is reached, so
  the two-limit split rule does not trigger; kept as one mobile story.
- **Security/privacy risk:** medium — edits the user's own data through several
  endpoints and must render provenance honestly (never fabricate, never silently
  re-label). Ownership/fail-closed and data minimization are enforced by the
  consumed endpoints; no value logging; no new egress or trust boundary on mobile.
- **Verification path:** mobile component/integration tests against mocked FTY-092 /
  FTY-093 / FTY-051 / FTY-052-053 endpoints covering each lever, detent
  transitions, clarify chips, the estimate nudge, light/dark, and accessibility;
  `make verify`; an iOS simulator smoke pass.
- **Assumptions safe for autonomy:** yes, with a dependency note — **FTY-092 and
  FTY-093 must land first** (the primary and change-match levers consume their
  read-model and endpoints), and FTY-097 supplies the tokens. The sheet is built
  as a standalone presentable component so it does not block on FTY-098 (the
  launching timeline). Until FTY-092/093 are merged, those levers are built and
  tested against their published contract surfaces (mocked).
