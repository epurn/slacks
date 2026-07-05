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

## Clarify-mode preserved on the fixed iOS sheet (opens populated + resolves)

Clarify-mode reuses the very same `CorrectionSheet` → `NativeSheet` iOS path as
the correction sheet (see `TodaySheetHost.tsx`: a `needs_clarification` entry
mounts the same sheet with `needsClarification`), so the FTY-227 content host is
what keeps its body from collapsing to blank too. The story requires clarify-mode
to still open **and** resolve end-to-end on the fixed iOS path — verified below
item-independently, both against the real backend and via the seeded clarify
regression fixture.

### Opens populated — real RC backend

| File | What it shows |
|------|---------------|
| `clarify-01-ios-populated-realbackend.png` | Tapping the **"a glass of milk" → Add a detail** row on the iOS 26.5 sim opens the clarify sheet against the real backend with its body **fully rendered** (not blank): title "a glass of milk", **LOGGED PHRASE** "a glass of milk", the question ("We need a detail to count this entry." — the generic prompt the sheet shows when the clarification read carries no persisted question), the "Type your answer:" label, and the free-text input + **Done** submit. |
| `clarify-02-ios-answer-interactive-realbackend.png` | The clarify body is **interactive**: typing `200 ml whole milk` into the answer field populates it and activates the (orange) **Done** submit — the content region is live, not a chrome-only strip. |

> **Real-backend note on the resolve round-trip.** The submit could not be driven
> to a *counted* item against this RC instance: the RC backend's clarification
> **read** (`GET …/log-events/{id}/clarification`) returns **HTTP 500** for every
> `needs_clarification` event (reproduced directly against the API for two
> distinct entries), so the free-text path — which re-reads the question id at
> submit time — honestly surfaces *"Could not load the question (status 500)"* and
> leaves the row tappable (correct, non-blocking mobile behaviour; the fix does
> not touch this logic). This is an RC-environment/read-model fault independent of
> the mobile sheet fix; the app degrades gracefully and the sheet still renders
> its full content. The **successful resolve** is therefore shown below on the
> same fixed iOS sheet against the seeded clarify fixture.

### Opens populated **and resolves** end-to-end — seeded clarify fixture (EXPO_PUBLIC_FATTY_E2E)

Driving the repo's clarify regression fixture (the same seeded payload
`.maestro/clarify.yaml` asserts on CI/Android) on the **iOS** dev build proves the
fixed iOS native sheet renders the full clarify payload and completes the
first-class answer round-trip:

| File | Step | What it shows |
|------|------|---------------|
| `clarify-03-ios-populated-question-chips.png` | Submit "coffee" → tap the **Add a detail** row | The iOS clarify sheet renders the **full** payload: LOGGED PHRASE "coffee", Fatty's real question *"What size was the coffee — small, medium, or large?"*, the **Small / Medium / Large** quick-pick chips, and the free-text fallback. This is exactly `clarify.yaml`'s load-bearing "data-starved sheet" assertion — shown rendering on the fixed iOS sheet. |
| `clarify-04-ios-resolved-counts.png` | Tap the **Large** chip → the answer round-trip resolves the **same** event → pull-to-refresh | The "needs a detail" treatment drops and the entry resolves **in place** (no duplicate row): "coffee" now shows ✓ **Logged**, and the day counts — hero **120 / 2,000 kcal · 6%** (`1,880 to go`), macros P `1/150g` · C `20/200g` · F `3/65g`. Clarify-mode opened **and** resolved end-to-end on the fixed iOS sheet. |

Both the generic-prompt (real-backend) and full-payload (seeded) clarify sheets
render their content on the actual iOS native sheet, and the chip-answer resolve
counts — the blank body reported in FTY-227 does not recur in clarify-mode, and
the clarify open→resolve path is preserved on iOS.

> **iOS a11y-tree note (same as the correction captures):** XCUITest does not
> surface the react-native-screens `formSheet`'s RN children in its queryable
> accessibility tree even when they render, so the sheet body (question, chips,
> input) is asserted **visually** (the screenshots above) while the Today-screen
> anchors that *are* queryable (the `needs a detail` row leaving, the counted
> hero label) are asserted with Maestro.

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
