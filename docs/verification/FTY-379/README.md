# FTY-379 — Motion audit + repair: running-app evidence

Audit of every existing signature beat on the running app in **default
settings** (OS Reduce Motion OFF), plus the reduce-motion degradation
regression. All captures are from the iOS simulator (iOS 26.5, iPhone
17-Pro-class device), E2E build (hermetic mock fetch, synthetic fixtures),
this branch's JS. Each beat was driven by the real Maestro flow while the
simulator screen was recorded (`xcrun simctl io recordVideo`); the PNGs here
are adjacent frames extracted from those recordings (AVAssetImageGenerator,
zero tolerance seeking). Timestamps in filenames are positions in the source
recording, so the spacing between adjacent frames is real elapsed time.

## Verdict summary

| Beat | Driven by | Fires in default settings? |
| --- | --- | --- |
| Entry resolve fade (`useResolveFade`) | `.maestro/resolve.yaml` | **Yes** — mid-fade frame captured |
| Hero bar spring easing (`CalorieHero` fill) | `.maestro/target.yaml` | **Yes** — fill grows across adjacent frames |
| Target-reached pulse (`usePulse`) | `.maestro/target.yaml` | **Yes** — 1.04× card scale measured at peak |
| Switcher capsule glide (`FloatingSwitcher`) | ad-hoc warm-switch flow + `.maestro/trends.yaml` | **Yes on warm switches**; jump-cuts on the cold first Trends mount (see finding below) |
| Reduce-motion degradation | `.maestro/reduce-motion.yaml` (`EXPO_PUBLIC_SLACKS_E2E_REDUCE_MOTION=true`) | **Green** — beats complete on the no-motion branch |

## Beat 1 — entry resolve fade (`resolve-fade/`)

`resolve.yaml`: submit "greek yogurt and banana" → pending skeleton row →
pull-to-refresh loads the completed event.

- `01-pending-skeleton-t93.65s.png` — pending row renders the skeleton
  shimmer placeholder; hero still `0 / 2,000`.
- `02-mid-fade-t93.90s.png` — **mid-fade**: the resolved event row is visible
  at partial opacity (dimmed text, clearly between hidden and settled) while
  the hero has flipped to 245; the amber bar is mid-spring (~5% width).
- `03-settled-t94.45s.png` — settled: both item rows ("Greek yogurt · 140
  kcal", "Banana · 105 kcal") at full opacity, bar settled at 12%.

## Beats 2+3 — hero bar easing and target-reached pulse (`hero-bar-pulse/`)

`target.yaml`: empty day (hero seeds "not reached") → "holiday roast dinner"
resolves to 2,100 kcal → refresh crosses the 2,000 target.

Bar easing: the amber fill grows across adjacent frames rather than swapping
instantly — `02-bar-early-t55.15s.png` (fill ≈ 8%) →
`03-bar-mid-pulse-peak-t55.30s.png` (fill mid-flight) →
`04-bar-full-pulse-peak-t55.45s.png` (full amber + coral over-target tip).

Pulse: `usePulse` scales the whole hero card to 1.04 and back. Measured from
the frames (contiguous light-pixel run of the raised card surface on a fixed
scanline, scroll-invariant): baseline width **1109 px** at t55.05–55.15,
growing through 1123/1139/1149 px, peaking at **1153 px ≈ 1.040×** at
t55.40–55.45, and settled back to 1109 px by t55.55 — exactly the
`Animated.spring` 1 → 1.04 → 1 sequence. The card edges expand symmetrically
(left 48→26 px, right 1157→1179 px), confirming a centered scale, not layout
shift.

| video t (s) | card width (px) | scale vs baseline |
| --- | --- | --- |
| 55.05–55.15 | 1109 | 1.000 |
| 55.20 | 1123 | 1.013 |
| 55.25 | 1139 | 1.027 |
| 55.30 | 1149 | 1.036 |
| 55.40–55.45 | 1153 | 1.040 (peak) |
| 55.55–56.00 | 1109 | 1.000 (settled) |

## Beat 4 — switcher capsule glide (`switcher-glide/`)

Crops of the floating switcher (bottom-left). Two **warm** switches (both
screens already mounted) show the capsule genuinely gliding:

- Trends → Today: `01-warm-on-trends-t54.65s.png` →
  `02-warm-mid-glide-t54.78s.png` (**capsule mid-transit between segments**)
  → `03-warm-on-today-t54.82s.png`.
- Today → Trends: `04-warm2-on-today-t55.53s.png` →
  `05-warm2-mid-glide-t55.68s.png` → `06-warm2-on-trends-t55.72s.png`.

**Cold-switch finding (out of scope here, filed as a planner note):** on the
*first* switch to Trends (`trends.yaml`), the capsule jump-cuts —
`07-cold-before-t53.02s.png` → `08-cold-after-jumpcut-t53.03s.png` are
adjacent recording frames with no intermediate position, while the heavy
Trends screen mounts. The capsule springs run on the JS driver
(`useNativeDriver: false`, unavoidable for `left`/`width` layout props), so
the first-mount JS work starves the animation frames and the time-based
spring lands at its end value once the thread frees. The beat itself is
healthy (warm switches glide); fixing the cold case needs a component-level
change (e.g. transform-based capsule animation), which this story's lane
forbids.

## Reduce Motion regression (`reduce-motion/`)

`reduce-motion.yaml` run against the reduce-motion E2E bundle
(`EXPO_PUBLIC_SLACKS_E2E_REDUCE_MOTION=true`, the harness overrides
`AccessibilityInfo.isReduceMotionEnabled` to `true` — the exact read the
beats branch on): **green**. The same skeleton→value resolve path completes
on the no-motion branch — value rows appear, the hero counts 245 — with no
stuck-hidden row. `final-state.png` shows the flow's end state.

## Diagnosis of the operator's "no animation" report (2026-07-16)

The story named two code-level suspects; here is what the audit found:

1. **Does the `isReduceMotionEnabled()` read resolve promptly on a default
   build?** Yes. On this default-settings run every beat took its motion
   branch (mid-fade frame, measured 1.04× pulse, gliding capsule), which is
   only reachable after the read resolves `false` — so the null window is
   transient and does not swallow motion on a healthy device.
2. **Could the null-defaults-to-reduced gate leave content hidden or motion
   permanently suppressed?** Before this story, yes — but only if the read
   never settled: `useResolveFade` armed a row at opacity 0 and waited for a
   non-null state forever (invisible resolved entry), and every
   `useReduceMotion` consumer would stay on the no-motion branch. That is
   exactly the repair shipped here (bounded reveal deadline in
   `theme/motion.ts` + unit tests pinning the motion-on path after the read
   resolves). We could not reproduce a hung read on the simulator; it remains
   a plausible Expo Go failure mode, now hardened either way.

Since the beats demonstrably fire in default settings, the operator's
device most likely had **OS Reduce Motion ON** (Settings → Accessibility →
Motion), where every beat degrades to fades/instant sets **by design** — an
app that reads as static. Two real contributors remain even with Reduce
Motion off: the cold-switch jump cut (above), and simply how few beats exist
— the hero bar seeds to its current value on mount (no draw-in on open, by
design), the switcher's first position snaps (by design), and Today/Trends
have no entrance/chart motion (FTY-380 and the noted Today follow-up).
