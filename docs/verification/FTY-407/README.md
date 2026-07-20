# FTY-407 — Prior corrected/logged foods surface as correction-sheet match candidates

Running-app evidence that a food the user has already hand-corrected is offered
as a top-ranked match candidate in the correction sheet's **Change match** panel,
and that picking it applies the corrected values.

## How these were captured

- Device: `Slacks-Slot-1`, iPhone 17 Pro, iOS 26.5 simulator (leased slot; Metro
  on the leased port, never the shared `booted` device or port 8081).
- Preset: the existing FTY-263 visual-review seam
  `slacks://__visual-review?preset=correction.typeahead&theme=light|dark`, which
  opens the correction sheet directly into change-match mode over the synthetic
  "Oatmeal" entry (140 kcal, 1 cup) with its candidate list already loaded.
- Data: the shared E2E `source-candidates` fixture, which now returns the
  FTY-411 `prior_corrections` sibling list alongside the unchanged USDA
  `candidates` — the same two-list response the real backend returns.

## What each capture proves

### `correction-typeahead-prior-correction-light.png` / `-dark.png`

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
- Both themes are legible: section headers, row titles, and meta lines all hold
  contrast against the sheet's material in light and dark.

### `correction-prior-correction-applied.png`

The result of tapping that row (the apply half, through FTY-411's re-resolve
path with the opaque `prior_correction:<hash>` reference):

- The sheet returns **in place** to its normal detail mode — no navigation, no
  jump (Calm by default).
- Provenance now reads **"Your correction"** with the pencil icon.
- The value is the corrected **105 kcal** (P 4 g, C 20 g), replacing the 140 kcal
  guess, and the timeline row behind the sheet has re-rendered to 105 kcal on the
  **same** row — no duplicate.
- Fat renders as **"F —g"**: a macro the correction never supplied stays honestly
  unknown rather than being fabricated as `0`.

Because this preset opens the sheet at its large, **dimmed** detent — where iOS
exposes no in-modal content to the accessibility tree (FTY-272, see
`docs/verification/FTY-263/README.md`) — the apply capture drives the row with a
coordinate tap rather than a text/id selector. The screenshots, not an a11y
assertion, are the proof on iOS.

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
