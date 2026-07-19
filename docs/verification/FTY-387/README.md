# FTY-387 — Switcher capsule glide survives the cold Trends mount

Running-app evidence that the raised capsule now transits on the **native
driver** (`translateX` + `scaleX` transforms), so it visibly glides on **every**
Today↔Trends switch — including the very first one after a fresh launch, when the
heavy Trends mount stalls the JS thread. Before this fix the selection spring
animated the layout-driven `left`/`width` on the JS thread, so the first (cold)
Trends mount starved the spring and the beat degraded to a jump cut (see the
FTY-379 baseline, `docs/verification/FTY-379/switcher-glide/`).

## How this was captured

- Slot-leased headless simulator (iPhone 17 Pro, iOS 26.5), app in E2E mode
  (`EXPO_PUBLIC_SLACKS_E2E=true`), hermetic mock fetch — synthetic data only.
- The switches were driven with Maestro (`tapOn floating-switcher-<key>`) while
  `xcrun simctl io recordVideo` recorded the screen. Frames were extracted at
  60 fps with `AVAssetImageGenerator` (exact-frame, no tolerance), so the spacing
  between adjacent frames is real elapsed time. The switcher band was diffed to
  isolate the capsule transit from the surrounding screen change.
- Resting captures use `xcrun simctl ui <udid> appearance light|dark` (the
  ThemeProvider follows the system trait) + Maestro-driven navigation.

## Evidence → acceptance criteria

| File | Criterion it proves |
| --- | --- |
| `01-cold-switch-glide.png` | **Cold-switch evidence.** Switcher-band crops of the *first* Today→Trends switch from a fresh cold launch (Trends never mounted before). The capsule is under **Today** at t=95.591 s, in clearly **intermediate** positions at t=95.741 s and t=95.770 s (sitting *between* the two segments, not on either), then resting under **Trends** at t=95.805 s. At least one intermediate capsule position between the two resting frames — a glide, not the FTY-379 jump cut. |
| `04-cold-mid-transit-full-frame.png` | The full-screen frame at t=95.770 s (cold switch) — the capsule mid-transit between segments, whole screen for context. |
| `02-warm-switch-glide.png` | **Warm switch still glides.** Today→Trends with both screens mounted: capsule under Today (t=54.068 s), mid-transit / centred (t=54.225 s), resting under Trends (t=54.253 s). |
| `03-resting-light-dark.png` | **Resting state, both segments, light and dark.** Capsule sits exactly under the active segment in each of the four combinations; per-segment width matches the measured layout (the Trends capsule is slightly wider than Today's), corners cleanly rounded. Matches the current build. |

## Corner integrity (no smear)

The segments are near-equal width (Today ≈ 92 pt, Trends ≈ 98 pt), so the
`scaleX` factor across a switch is ~1.06. Across every mid-transit frame above
the capsule's rounded ends read as clean pill corners — no visible smear or
elliptical distortion. The resting geometry is driven from the measured layout,
so at rest the capsule is pixel-identical to the pre-change build.

## Other checks (not pictured)

- `mobile/.maestro/trends.yaml` re-run against this build: **green** end-to-end
  (launch → `tapOn floating-switcher-trends` → Trends → weight log/save → "74.7 kg"
  headline), confirming the switcher navigation path is unaffected.
- The Reduce Motion instant-swap, first-measurement snap, and same-segment
  re-layout snap are covered by
  `mobile/components/ui/FloatingSwitcher.test.tsx`. `reduce-motion.yaml`
  exercises the resolve/hero beats (`theme/motion.ts`), which this change does
  not touch, so it is structurally unaffected; CI runs it as the merge gate.
