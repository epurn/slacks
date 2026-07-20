# FTY-407 — Prior corrected/logged foods surface as correction-sheet match candidates

Running-app evidence that a food the user has already hand-corrected is offered
as a top-ranked match candidate in the correction sheet's **Change match** panel,
and that picking it applies the corrected values.

## How these were captured

- Device: `Slacks-Slot-0`, iPhone 17 Pro, iOS 26.5 simulator (leased slot; Metro
  on the leased port, never the shared `booted` device or port 8081).
- Flow: **`mobile/.maestro/prior-correction-candidate-fty407.yaml`** — committed,
  rerunnable, and the sole producer of all three files below (their names are the
  flow's own `takeScreenshot` names).
- Preset: **`correction.prior_correction`**, registered by the correction seam
  (`mobile/components/correction/visualReviewSeam.ts`) through FTY-247's
  registration API. It opens the sheet straight into change-match mode over the
  synthetic "Oatmeal" entry (140 kcal, 1 cup) **and seeds its own
  `source-candidates` response** with one `prior_corrections` entry alongside the
  unchanged USDA `candidates` — the same two-list response the real backend
  returns — plus the `/re-resolve` answer the apply capture commits.

The seeding is preset-scoped on purpose. The shared E2E mock
(`mobile/e2e/mockFetch.ts`) still answers with the guessed-only list, so the
pre-existing `correction.typeahead` preset renders byte-for-byte what it rendered
before this story — it is the no-history control for these captures, and
`TodayScreenVisualReviewSeam.test.tsx` asserts the split directly (this preset
seeds a `prior_corrections` response; `correction.typeahead` seeds none).

## What each capture proves

### `fty407-prior-correction-candidate-light.png` / `-dark.png`

The Change-match panel, light and dark:

- A **"Your corrections"** group renders **above** the guessed-source matches,
  matching FTY-406's estimate-time precedence (a user's own curated value beats
  any re-guess).
- Its row carries the always-on pencil provenance icon and reads
  **"Oatmeal · 105 kcal · Your correction"** — the corrected **total** for the
  item's own 1-cup portion (`basis = as_logged`), never the guessed sources'
  "/ 100g" density copy.
- The guessed match is still offered below, under **"Other matches"**
  ("Chicken, grilled, USDA · 165 kcal / 100g") — the existing candidate list is
  additive, not replaced.
- Both groups' names and meta lines share one left edge: the guessed rows render
  a spacer the width of the prior-correction rows' pencil, so the grouped list
  stays on a single text grid (only while the grouped list is on screen — with no
  history the guessed row is unchanged).
- Both themes are legible: section headers, row titles, and meta lines all hold
  contrast against the sheet's material in light and dark.

### `fty407-prior-correction-applied.png`

The result of tapping that row (the apply half, through FTY-411's re-resolve
path with the opaque `prior_correction:<hash>` reference):

- The sheet returns **in place** to its normal detail mode — no navigation, no
  jump (Calm by default).
- Provenance now reads **"Your correction"** with the pencil icon.
- The value is the corrected **105 kcal** (P 4 g, C 20 g), replacing the 140 kcal
  guess, and the timeline row behind the sheet has re-rendered to 105 kcal on the
  **same** row — no duplicate. (The header ring still reads 140: the preset's
  seeded daily-summary is static, so the ring is not part of this proof.)
- Fat renders as **"F —g"**: a macro the correction never supplied stays honestly
  unknown rather than being fabricated as `0`.

This preset opens the sheet at its large, **dimmed** detent — where iOS exposes
no in-modal content to the accessibility tree at all (FTY-272, see
`docs/verification/FTY-263/README.md`). So the flow's copy assertions and its
label-based row tap are Android-gated, exactly as the sibling
`correction-visual-review-seam.yaml` does it, and the iOS branch waits on the
sheet then drives the row with a **point tap committed in the flow** — not a
hand-driven tap. The screenshots, not an a11y assertion, are the iOS proof.

## Automated coverage

The behaviour itself is covered by unit tests, independent of these captures:

- `mobile/api/corrections.test.ts` — the `prior_corrections` list is parsed,
  unknown macros stay `null`, and a missing/empty list degrades to "no matching
  history".
- `mobile/components/correction/ChangeMatchPanel.test.tsx` — prior corrections
  rank above guessed matches, are pickable through the same handler, carry the
  provenance icon, and suppress the empty state.
- `mobile/components/CorrectionSheet.test.tsx` — the full flow: open Change
  match → the prior correction appears → pick it → `reResolve` is called with the
  `prior_correction:` reference → the corrected item is adopted and the sheet
  returns to normal; plus the no-matching-history fall-through, which renders
  exactly as before.
- `mobile/components/today/TodayScreenVisualReviewSeam.test.tsx` — the
  `correction.prior_correction` preset seeds its own two-list response, opens
  directly in change-match mode with the prior correction ranked above the guess,
  and leaves `correction.typeahead`'s response untouched.
- `mobile/e2e/launchMode.test.ts` — the shared E2E mock offers no prior
  corrections, so every other correction preset keeps the no-history rendering.
