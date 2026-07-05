# FTY-227 — iOS native sheet renders blank content

Running-app evidence captured on the **iPhone iOS 26.5 simulator dev build**
(`Fatty-Slot-0`), Expo dev-client + Metro serving this branch's JS. The
before/after blank captures (`before-01`, `after-01`) were taken in the same
session with `mobile/components/ui/NativeSheet.tsx` as the only changed variable
(the fix was `git stash`ed to capture the blank state, then restored).

The **item-independence** and **successful-save** captures (`after-rb-*`) were
taken **against the real RC backend** (`localhost:18000`) signed in as a real
account with a real profile (1,643 kcal target), so every sheet below is fed by
a genuine server item with a real id — not an E2E fixture.

## Root cause

`react-native-screens@4.25` positions a `formSheet`'s content wrapper as
`position: absolute; top/left/right` with **no `bottom`** on its default
(non-`synchronousScreenUpdatesEnabled`) code path for React Native ≥ 0.82 — see
`ScreenStackItem.getPositioningStyle` → `absoluteWithNoBottom`. The wrapper is
therefore sized to its content's *intrinsic* height, so the correction sheet's
`flex: 1` body (and the `flex: 1` `ScrollView` inside it) has no bounded height
to grow into and collapses to zero. The native chrome (grabber + the fixed,
`minHeight: 44` "Done" control) still lays out, so the sheet *looks* present
while its scrolling body — title, provenance, Portion stepper — renders blank.

Jest never caught it because it does no native layout (children always mount into
the tree), and the Android `Modal` fallback already gives its body an explicit
height — which is why the Android-only E2E CI job stayed green while iOS was
broken.

## Fix

On iOS, wrap the sheet children in a content host with an explicit height derived
from the **largest** allowed detent, so the flex chain resolves. `fitToContents`
sheets keep sizing to their own content. See `NativeSheet.tsx`.

## Screenshots — the blank-vs-populated fix

| File | State | What it shows |
|------|-------|---------------|
| `before-01-ios-sheet-blank.png` | **Before** (fix reverted) | Sheet chrome present — grabber + "Done" — but the entire body is blank: no title, no provenance, no Portion stepper. This is the FTY-227 bug. |
| `after-01-ios-sheet-populated.png` | **After** (fix applied) | Same session, fix restored: title, provenance block, **PORTION** stepper and macros all render. The blank body is gone. |

## Item-independence — real RC backend, two required item paths

The story requires the fix be verified on **both** a resolved barcode/estimated
item **and** a saved-food item. Each was opened on the iOS 26.5 sim against the
real backend and its correction sheet rendered fully populated (title +
provenance block + Portion stepper + macros + Change match + Advanced rows):

| File | Item path | What renders |
|------|-----------|--------------|
| `after-rb-01-resolved-usda-rice.png` | **Resolved / estimated** — "cooked white rice", USDA-backed (`trusted_nutrition_database`) | Title "cooked white rice", 🔍 **USDA** provenance + `"200 g cooked white rice"`, PORTION `200 g`, `194 kcal · P4 C42.2 F0.4`, Change match, Advanced edit rows. |
| `after-rb-02-resolved-usda-chicken.png` | **Resolved / estimated** — "grilled chicken breast", USDA-backed (a *different* resolved item, proving independence) | Title "grilled chicken breast", 🔍 **USDA** + `"150 g grilled chicken breast"`, PORTION `150 g`, `227 kcal · P45.8 C0 F4.8`, Change match, Advanced rows. |
| `after-rb-03-savedfood-oatbar.png` | **Saved food** — "Protein oat bar" logged from the saved-food typeahead (client-synthesised item, no evidence source) | Title "Protein oat bar", **Unknown source** + `"Protein oat bar"`, PORTION `1 bar`, `210 kcal · P12 C24 F7`, Change match, Advanced rows. |

Both required paths — a resolved barcode/estimated item and a saved-food item —
show populated content on the actual iOS native sheet. The blank body reported in
FTY-227 does not recur on either.

## Successful correction save + re-fetch (real backend)

The earlier round only showed a Portion tap ending in an error (the E2E mock did
not stub the amount-edit endpoint). Against the real backend the full save path
completes and counts:

| File | Step | What it shows |
|------|------|---------------|
| `after-rb-04-portion-interactive.png` | Adjust the Portion stepper on "cooked white rice" | The stepper is live: `200 g → 215.5 g`, macros recompute in place to `206 kcal · P4 C48.4 F0.4`. No error — the content is visible **and** interactive. |
| `after-rb-05-save-counted.png` | Tap **Done** → the correction commits and the day re-fetches | The timeline row now reads **"cooked white rice · 206 kcal"** and the header total moved **421 → 433 kcal** (`1,210 to go`, C `48/131g`). The correction saved, persisted server-side, and counts. |

Server confirmation for the save: the item's `amount` went `200 → 215.5` and
`calories` `194 → 206.4`, and the day's `daily-summary` intake went
`420.5 → 432.9 kcal` — i.e. the sheet's edit is a real persisted correction, not
an optimistic-only UI change.

## Platforms & regression guard

- **Android `Modal` fallback:** untouched by this fix (the non-iOS branch in
  `NativeSheet.tsx` is unchanged). It is covered by the `NativeSheet` test's
  Android branch and by the existing Android-only E2E job that drives
  `.maestro/correction.yaml` to completion — the platform where sheet content
  always rendered. No regression.
- **Regression guard:** `mobile/components/ui/NativeSheet.test.tsx` asserts the
  iOS sheet path mounts its children inside a **bounded, non-zero-height** content
  host and that a chrome-only render fails. Because CI runs the Android project,
  this component test is the guard that actually protects the **iOS** layout the
  screenshots above prove — the file header documents exactly that.
- **Maestro note:** on this iOS simulator XCUITest does not surface the
  react-native-screens `formSheet`'s RN children in its queryable accessibility
  tree even when they render, so the sheet body is asserted **visually** (the
  screenshots) and **structurally** (the component guard), not by an iOS Maestro
  text assertion.
