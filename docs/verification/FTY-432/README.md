# FTY-432 — The Today composer input gets the room the app's core action deserves

Running-app evidence that the free-text composer now reads as Today's generous
primary surface — a full-width field at a roomy resting height — with all four
actions (attach photo · scan barcode · capture label · Add) on a secondary row
directly beneath it.

## Capture setup

- Devices:
  - **iPhone 17 Pro** (leased simulator slot) — light + dark, native 1206×2622.
  - **iPhone SE (3rd generation)** — 375 pt, the **smallest supported width**
    (`docs/design/ux-design.md` §7: "iPhone, all sizes (SE → Pro Max)"), native
    750×1334.
- Build: the E2E debug binary from this branch (`EXPO_PUBLIC_SLACKS_E2E=true`),
  JS served from this branch's Metro.
- Driver: Maestro against the FTY-247 visual-review deep link
  `slacks://__visual-review?preset=today.populated&theme=light|dark`, plus one
  default-E2E-mode flow for the submit proof.
- The `before-*` / `se-before-*` shots are the SAME device, fixtures, and flow
  with only `mobile/components/today/TodayComposer.tsx` reverted to its
  pre-FTY-432 state, so the pair isolates this diff.

## What each shot shows

| Shot | State | Device | Theme |
| --- | --- | --- | --- |
| `before-rest-light.png` / `before-rest-dark.png` | **Before:** the field shares one row with four ~44 pt buttons — the placeholder "Add food or exercise…" wraps onto two lines inside a ~38 %-width slot | 17 Pro | light / dark |
| `composer-rest-light.png` / `composer-rest-dark.png` | **After:** full-width field, 68 pt resting height, placeholder on one line; capture actions grouped left, Add anchored right on the row beneath | 17 Pro | light / dark |
| `composer-focused-light.png` / `composer-focused-dark.png` | Focused, software keyboard up — field and all four actions remain visible above the keyboard | 17 Pro | light / dark |
| `composer-multiline-light.png` / `composer-multiline-dark.png` | A realistic two-line log ("two scrambled eggs with sourdough toast, a flat white and a handful of blueberries") sits inside the resting height with breathing room; Add turns amber/enabled | 17 Pro | light / dark |
| `se-before-rest-light.png` | **Before, smallest width:** the placeholder wraps onto two lines in an even narrower slot | SE | light |
| `se-composer-rest-light.png` | **After, smallest width:** full-width field, one-line placeholder | SE | light |
| `se-composer-focused-light.png` | Focused with the keyboard up — the whole composer clears the keyboard | SE | light |
| `se-composer-multiline-light.png` | Worst case: the field has grown to **three** lines with the keyboard up. The action row stays on screen; only the bottom few points of the buttons meet the keyboard's top edge, and Today's scroll view now adjusts its insets for the keyboard so the row can be scrolled fully clear | SE | light |
| `se-multiline-keyboard-up.png` → `se-submitted-with-keyboard-up.png` | The same worst case, driven to completion: **Add tapped with the keyboard still up** → the entry lands in the timeline and the field clears | SE | light |

## Maestro flows run against this build

Composer-touching flows, green on this branch (iPhone 17 Pro slot sim):

- `.maestro/smoke.yaml` — tap composer → type → **Add entry** → timeline + totals
- `.maestro/image-submit.yaml` — type → **Attach photo** → thumbnail → **Add entry** → resolved
- `.maestro/quick-add-default-fty408.yaml` — `today-composer-input` testID tap + type
- `.maestro/failed-parse.yaml`, `.maestro/target.yaml` — composer submit paths

`.maestro/resolve.yaml` and `.maestro/clarify.yaml` fail on this local iOS
simulator **identically with and without this diff** (verified by re-running both
with `TodayComposer.tsx` reverted): every composer step completes, and each stops
later on the known iOS-local timeline-row / clarify-sheet accessibility
limitations. Android CI is the tested platform for those two.
