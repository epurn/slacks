# FTY-417 — Swipe-to-delete reveal is reliable, not a scroll gamble

Running-app evidence that a single deliberate horizontal swipe on a Today row
reveals **Delete** and the reveal **stays open** (it no longer snaps shut because
the enclosing timeline `ScrollView` reclaimed the gesture).

Captured on the iOS simulator (iPhone-class slot sim, iOS 26.5) against the
synthetic E2E fixtures, driven by an ad-hoc Maestro flow that logs an entry,
pull-to-refreshes it to the counted "Greek yogurt, 140 kcal" row, then performs
**one** left swipe and asserts `swipe-delete-action` is visible before capturing —
so each shot proves the reveal is latched open, not mid-gesture.

| File | State |
| --- | --- |
| `fty417-delete-revealed-light.png` | Row swiped open, red Delete revealed and held — light |
| `fty417-delete-revealed-dark.png`  | Row swiped open, red Delete revealed and held — dark |

The arbitration fix (`SwipeableRow` refuses to yield the gesture via
`onPanResponderTerminationRequest → false`, and the Today `ScrollView` locks
`scrollEnabled` for the duration of an active swipe) is unit-covered in
`mobile/components/SwipeableRow.test.tsx` and
`mobile/components/TodayScreenDelete.test.tsx`.
