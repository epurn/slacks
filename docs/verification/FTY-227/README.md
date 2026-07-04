# FTY-227 — iOS native sheet renders blank content

Running-app evidence captured on the **iPhone iOS 26.5 simulator dev build**
(`Fatty-Slot-0`), Expo dev-client + Metro serving this branch's JS in E2E mock
mode. The only variable changed between the "before" and "after" captures is
`mobile/components/ui/NativeSheet.tsx` (the fix was `git stash`ed to capture the
blank state, then restored) — same simulator, same session, same seeded item.

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

## Screenshots

| File | State | What it shows |
|------|-------|---------------|
| `before-01-ios-sheet-blank.png` | **Before** (fix reverted) | Sheet chrome present — grabber + "Done" — but the entire body is blank: no title, no provenance, no Portion stepper. This is the FTY-227 bug. |
| `after-01-ios-sheet-populated.png` | **After** (fix applied) | Same item, same session: title "Chicken burrito bowl", provenance block ("Unknown source" + quoted phrase), **PORTION** stepper (− / "1 bowl" / +), `640 kcal · P42g C56g F22g`, "Change match" lever, and the Advanced edit rows all render. |
| `after-02-ios-sheet-lever-responds.png` | **After** — interactivity | Tapping the Portion "+" fires the amount-step handler and surfaces an in-place response ("We couldn't find that item." — the E2E mock does not stub the amount-edit endpoint for this synthetic saved-food item). Proves the content is not just visible but live/interactive. |
| `after-03-ios-sheet-repopulated.png` | **After** — toggle confirmation | With the fix restored (after the "before" capture), the sheet repopulates — confirming `NativeSheet.tsx` is the sole variable. |

## Item-independence & platforms

- The fix lives in the shared `NativeSheet` primitive, so it is item-independent
  by construction; the component guard `mobile/components/ui/NativeSheet.test.tsx`
  asserts the bounded-height host generically (any child).
- **Android `Modal` fallback:** untouched. Covered by the `NativeSheet` test's
  Android branch and by the existing Android-only E2E job that runs
  `.maestro/correction.yaml` to completion (the platform where content always
  rendered).
- **Maestro note:** on this iOS simulator, XCUITest does not surface the
  react-native-screens `formSheet`'s RN children in its queryable accessibility
  tree even when they render (the same limitation that made the `correction.yaml`
  "Portion" step flaky on iOS). The fix is a *visual/layout* correction; the
  screenshots above are the proof, and the regression guard is a component test —
  not an iOS Maestro assertion.
</content>
