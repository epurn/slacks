# FTY-410 — Trends page honors the imperial/metric unit preference

Running-app evidence that the Trends screen renders weight in the user's selected
unit system, converting the canonical-kg weight series display-only.

## Capture setup

- Device: **iPhone SE (3rd generation)** — 375 pt, the **smallest supported
  width** (`docs/design/ux-design.md` §7: "iPhone, all sizes (SE → Pro Max)").
  Native screenshots are 750×1334.
- Build: the E2E debug binary (`EXPO_PUBLIC_SLACKS_E2E=true`), JS served from this
  branch's Metro.
- Driver: `mobile/.maestro/trends-units-fty410.yaml` via the FTY-247 visual-review
  deep link `slacks://__visual-review?preset=<name>&theme=light|dark`.
- Fixtures: the **same** canonical-kg weight series (`e2eWeightEntries`) for every
  shot. Only the profile's `units_preference` differs:
  - `trends.imperial` overrides `GET /profile` to `units_preference: 'imperial'`.
  - `trends.populated` is the metric default.
  This proves the conversion is **display-only** — storage/series are unchanged.

## What each shot shows

Same underlying series across all four (current EWMA 75.7 kg = 166.8 lb):

| Shot | Headline | Chart Y-axis | Theme |
| --- | --- | --- | --- |
| `trends-imperial-light.png` | 166.8 lb | 168 lb / 164.9 lb | light |
| `trends-imperial-dark.png`  | 166.8 lb | 168 lb / 164.9 lb | dark  |
| `trends-metric-light.png`   | 75.7 kg  | 76.2 kg / 74.8 kg  | light |
| `trends-metric-dark.png`    | 75.7 kg  | 76.2 kg / 74.8 kg  | dark  |

The headline weight metric, the chart Y-axis labels, and the per-point trend all
render in the selected unit. `75.7 kg / 0.45359237 ≈ 166.8 lb` — the conversion is
exact (NIST factor), via the shared `kgToDisplay` / `weightUnitLabel` helpers
(`mobile/state/weightEntries.ts`), not an inline factor.

Each Maestro step asserts the unit string is visible (`.*lb.*` for imperial,
`.*kg.*` for metric) before the screenshot is taken, so a leaked-kg imperial
render (the bug this story fixes) fails the flow rather than passing silently.
