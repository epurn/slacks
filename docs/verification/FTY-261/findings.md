# FTY-261 — Trends status-bar containment: before/after

Direct before/after against the FTY-259 audit's SE-class captures that surfaced
this defect (`docs/verification/FTY-259/iphonese-{light,dark}-trends-bottom.png`).

## How these were captured

- Built dev-client `.app` served this branch's JS via Metro
  (`EXPO_PUBLIC_FATTY_E2E=true`) with the same E2E weight/daily-summary range
  fixtures FTY-259 used, so the rendered data (`75.7 kg`, weight-trend line,
  intake adherence) matches the FTY-259 captures exactly.
- Driven on a dedicated `iPhone SE (3rd generation)` simulator (SE-class, per
  the story's device requirement), scrolled to the same near-bottom position as
  the FTY-259 captures, in both light and dark appearance.

## Before (FTY-259, pre-fix)

`docs/verification/FTY-259/iphonese-light-trends-bottom.png` and the dark
counterpart: the large weight metric (`75.7 kg`) and its delta line render
directly under/through the status bar — "Carrier" is partly obscured by the "7"
of "75.7", and the status-bar strip is not opaque screen chrome.

## After (this story)

- `iphonese-light-trends-bottom-after.png`
- `iphonese-dark-trends-bottom-after.png`

Same scroll position, same fixture data, both appearances: the status-bar strip
(time / carrier / battery) is fully legible and opaque in both palettes. The
weight-metric text is clipped below the status-bar region by the new backdrop
(`TrendsScreen.tsx`'s `trends-status-bar-backdrop`, sized to
`useSafeAreaInsets().top` and colored from `colors.surface`) instead of
rendering into it.
