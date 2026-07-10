# FTY-305 — Settings Done button press visual stability

Running-app evidence that the Profile / Settings header **Done** action is calm
native text chrome: no white rectangle, no scale-up, no hit-target expansion, no
header layout jump — and that it still dismisses back to Today.

Captured on an iOS 26.5 simulator against the E2E synthetic fixtures
(`EXPO_PUBLIC_FATTY_E2E=true`, `mobile/e2e/fixtures.ts`), from a debug binary built
from this branch. Navigation and the press/dismiss were driven by Maestro
(`profile-done` test id + `mobile/.maestro/profile.yaml`).

## The defect and the fix

The white rectangle was **iOS 26's shared "glass" bar-button background** — the
platter UIKit draws behind a navigation-bar button. The classic `headerRight`
element has no way to opt out of it, so Done now goes through
`unstable_headerRightItems` (a typed expo-router native-stack surface) as a custom
item with `hidesSharedBackground: true` (maps to
`UIBarButtonItem.hidesSharedBackground`). Only the amber label draws; the element
is still the same inert `Pressable`, so the `profile-done` test id, the Done
role/label, the `accentText` colour, and the stable ≥44pt target are preserved.

## Screenshots

| File | What it shows |
|------|----------------|
| `01-before-fix-white-capsule.png` | **Before the fix** — Done sits on an opaque white capsule (the iOS 26 shared bar-button background); the "Profile" large title is also suppressed by it. |
| `02-after-fix-rest.png` | **After the fix, at rest** — Done is plain amber text with no capsule; the "Profile" large title renders. |
| `03-after-fix-during-press.png` | **After the fix, Done held pressed** (screenshot burst during a Maestro long-press) — identical to rest: no white flash, no scale-up, no hit-target expansion, no header layout shift. |
| `04-after-fix-dismissed-to-today.png` | **After releasing Done** — the route pops back to Today, proving the dismissal target is unchanged. |

`mobile/.maestro/profile.yaml` was also run end-to-end on this build: it opens
Profile, drives the FTY-190 goal edit → target-reveal path, taps `profile-done`,
and returns to Today — all green, so the header change regresses nothing.
