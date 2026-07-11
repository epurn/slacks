# FTY-322 — Delete a logged item from the Today timeline: running-app evidence

Captured on a leased iOS simulator (iPhone 17, iOS 26.5) against the E2E debug
build (`EXPO_PUBLIC_FATTY_E2E=true`) serving this branch's JS, driving the
committed `mobile/.maestro/delete.yaml` flow (parameterised with `takeScreenshot`
steps for capture). Theme forced with `xcrun simctl ui <udid> appearance
light|dark`; the app follows system appearance. Recaptured in full on the fix
round so every image reflects the current head.

The flow logs "yogurt to delete", pulls to refresh so it resolves to a counted
`Greek yogurt, 140 kcal` row (hero 140 / 2,000 kcal), swipes the row left to
reveal the destructive **Delete** action, taps it, and asserts the row leaves the
timeline and the hero returns to 0. It then logs the forever-pending "mystery
smoothie" fixture (the mock never resolves it), swipes its still-estimating
skeleton row to reveal Delete, deletes it, and proves a refresh keeps both rows
gone — every step reported `COMPLETED` on-device in both themes.

## Acceptance criteria proven here

- **Swipe-left reveals a destructive Delete; tapping removes the row and updates
  the day totals.** `02-revealed` shows the row slid aside revealing the red
  Delete button; `03-after` shows the row gone and the hero back to
  `0 / 2,000 kcal` with macros zeroed. The Maestro `notVisible` assertion after
  the tap passed. (The totals recompute is optimistic — applied the same beat
  the row is hidden, before the DELETE round-trip; `TodayScreenDelete.test.tsx`
  pins that timing, which a screenshot cannot.)
- **Every server-backed row is deletable, including pending/processing.**
  `04-pending-revealed` shows a genuinely still-estimating skeleton row
  (shimmer placeholders, uncounted — hero at 0) swiped aside with the same
  destructive Delete revealed; `05-pending-after` shows the timeline empty
  after tapping it and refreshing — the pending row deleted end-to-end.
- **No layout shift on rows not being swiped / calm in place.** The hero,
  composer, and macro tiles are unchanged between `01-before` and `02-revealed`;
  only the swiped row translates.
- **Native, on-brand rendering in light and dark.** Both themes render the
  standard iOS swipe action with the warm destructive accent (`colors.coral`)
  and legible white label.

## Screenshots

### Before — resolved row counting toward the hero

| Light | Dark |
| --- | --- |
| ![before light](delete-01-before-light.png) | ![before dark](delete-01-before-dark.png) |

### Swipe-revealed destructive Delete action

| Light | Dark |
| --- | --- |
| ![revealed light](delete-02-revealed-light.png) | ![revealed dark](delete-02-revealed-dark.png) |

### After delete — row gone, hero back to zero

| Light | Dark |
| --- | --- |
| ![after light](delete-03-after-light.png) | ![after dark](delete-03-after-dark.png) |

### Pending (still-estimating) skeleton row — Delete revealed (fix round)

| Light | Dark |
| --- | --- |
| ![pending revealed light](delete-04-pending-revealed-light.png) | ![pending revealed dark](delete-04-pending-revealed-dark.png) |

### After deleting the pending row — gone across a refresh (fix round)

| Light | Dark |
| --- | --- |
| ![pending after light](delete-05-pending-after-light.png) | ![pending after dark](delete-05-pending-after-dark.png) |
