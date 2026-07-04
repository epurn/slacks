# FTY-214 manual verification — Correction sheet, no size regression

Story-required visual verification for the correction-sheet `fontSize` →
`typeScale` migration, run 2026-07-04 on an iOS 26.5 simulator against the
**E2E fixture harness** (`EXPO_PUBLIC_FATTY_E2E=true`, `mobile/e2e/fixtures.ts`)
— synthetic session, no live backend, no real account or nutrition data. This
mirrors the precedent set by `docs/verification/FTY-192/README.md` (fixture
harness preferred over a real-backend session so no committed screenshot can
carry real user data).

## What this story changed

Four numeric `fontSize` literals in the mobile-correction lane were routed
through `typeScale`, with no change in numeric value (so no rendered-size
change is possible regardless of platform):

- `CorrectionSheet.tsx` `styles.leverChevron`: `20` → `typeScale.title3` (`20`)
- `correction/AdvancedLeverRow.tsx` `styles.leverChevron`: `20` → `typeScale.title3` (`20`)
- `correction/ChangeMatchPanel.tsx` `styles.candidateChevron`: `20` → `typeScale.title3` (`20`)
- `correction/AmountStepper.tsx` `styles.stepperButtonLabel`: `22` → `typeScale.title2` (`22`)

No correction-owned header or numeral reaches display-face scale (the
largest, `stepperButtonLabel`/chevrons, tops out at `title2`/`title3`,
21–22pt) — nothing in this sheet is a "hero" moment per the *Native skeleton,
bespoke soul* principle, so no site was routed through `DisplayText`.

## Method and an infra finding

Drove `Today → log a saved food → tap the resolved row → correction sheet
opens` via `.maestro/correction.yaml` (adapted locally to work around the
known iOS composer-selector quirk — wrap `"Log food or exercise"` in `.*`,
see project memory). The flow reaches the sheet open at the medium detent
(`grabber` + `"Done"` visible, sheet accessibility label present), confirmed
via `maestro hierarchy`.

**The sheet's RN content renders empty on this Mac's iOS 26.5 simulator +
dev-client** — the accessibility tree shows no `Portion` / amount / chevron
nodes inside the sheet, before or after this story's change. This is a known,
pre-existing, environment-specific limitation of `NativeSheet`'s iOS path
(`react-native-screens` `ScreenStackItem` detents render the presentation
chrome but not always the RN subtree on this simulator/OS combination) —
already observed independently on `main` in prior stories (barcode and
saved-food items alike). It is not something this diff can cause: the change
here only swaps numeric literals for token references of the *same* value.

To make the "no visible regression" claim concrete despite that gap, the
screenshots below are a controlled before/after on the **exact same running
session**: with the sheet already open, the story's 4 changed files were
`git stash`-reverted to their pre-story content (raw numeric literals), the
sheet was re-captured, then the story's changes were restored (`git stash
pop`) and re-captured again from the same live Metro connection (no app
relaunch, no fixture reset).

## Screenshot index

| Screenshot | State | Evidence |
|---|---|---|
| `correction-sheet-before-fty214-crop.png` | Pre-story code (raw `fontSize: 20`/`22` literals) | Timeline row + sheet grabber/Done, sheet interior empty (infra gap, see above) |
| `correction-sheet-after-fty214-crop.png` | Post-story code (`typeScale.title2`/`title3`) | Identical crop region |
| `correction-sheet-full-frame.png` | Post-story code, full frame | Today timeline with the resolved "Chicken burrito bowl, 640 kcal" row and the sheet presented at the medium detent |

`correction-sheet-before-fty214-crop.png` and `correction-sheet-after-fty214-crop.png`
are **byte-identical** (`cmp` reports no difference): the same session, same
scroll position, same detent, same timeline row, with only the sheet's
internal `fontSize` source swapped out from under it. Since the two literal
values this story touches map to identically-valued `typeScale` tokens
(`20`→`20`, `22`→`22`), byte-identical frames are the expected (and strongest
available) proof of no visible size regression.

## Other verification

- `node scripts/check-font-size-literal.js` — guard passes with the 4
  mobile-correction sites removed from `font-size-baseline.json` and enforced
  strictly.
- `scripts/check-font-size-literal.test.js` — new `FTY-214` describe block
  asserts zero remaining numeric `fontSize` literals across every
  correction-owned file (the sheet host, `ClarifyMode`, and all
  `components/correction/*` panels), plus updated baseline-enumeration
  assertions.
- `components/CorrectionSheet.test.tsx` / `CorrectionSheet.accessibility.test.tsx`
  (64 tests) pass unchanged — correction behaviour is unaffected.
- `make mobile` (typecheck, lint, accent-text guard, fontSize guard, full
  Jest suite — 92 suites / 1224 tests) passes.
