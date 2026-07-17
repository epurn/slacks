# FTY-380 — Trends motion pass: running-app evidence

Calm draw-in for the weight-trend chart (`EWMATrendChart`): on a data-settle
the canvas fades in while the EWMA line strokes on left → right
(`strokeDashoffset` on an `Animated`-wrapped polyline, JS driver, ~400 ms
ease-out); under Reduce Motion the chart renders instantly, fully drawn.

All captures are from the iOS simulator (iOS 26.5, iPhone 17-Pro-class
device), E2E build (hermetic mock fetch, synthetic weight fixtures — no real
user data), this branch's JS. The dark-mode sequences are adjacent frames
extracted from `xcrun simctl io recordVideo` recordings
(AVAssetImageGenerator, zero-tolerance seeking; timestamps in filenames are
positions in the source recording). The light-mode and Reduce-Motion
sequences are timed `simctl io screenshot` bursts (~110 ms cadence; filenames
carry the relative capture time), taken while the same Maestro flow drove the
screen.

## Draw-in on Trends load — dark (`draw-in-dark/`)

Cold open: Today → tap the switcher's Trends segment. The chart card shows
the honest loading spinner, then the resolved chart reveals once.

- `01-loading-t19.05s.png` — Trends mounted, weight card still shows the
  loading spinner (no chart, no headline).
- `02-reveal-early-t19.10s.png` — data settled: dots faded in, the trend line
  stroked through the first segment only.
- `03-reveal-mid-t19.20s.png` — the line has swept ~3/4 of the way across.
- `04-reveal-late-t19.35s.png` — sweep approaching the final trend dot.
- `05-settled-t19.55s.png` — resting chart, identical to the pre-change
  static render (solid line through every point, no dash artifacts).

Axis labels (`76.2 kg` / `74.8 kg` / `June 19` / `Today`), the card, and the
adherence card below hold identical positions across frames 02–05 — the
reveal happens inside the fixed-height SVG frame, no layout shift, no
bounce/overshoot (plain ease-out; the whole reveal spans ~19.05 s → ~19.45 s,
within the ≤ ~400 ms calm bar).

## Draw-in on a range change — dark (`range-change-dark/`)

On Trends showing 1 month, tap "3 months". The refetch resolves and the plot
replays the reveal exactly once, at data-settle.

- `01-before-tap-1m-t6.45s.png` — settled 1-month chart, capsule on "1 month".
- `02-remount-fade-t6.65s.png` — after the tap: headline already reads
  "these three months", the segmented capsule is mid-glide, and the remounted
  chart canvas is at low opacity (fading in).
- `03-reveal-mid-t6.75s.png` — the line mid-sweep (~60 % across).
- `04-settled-3m-t6.90s.png` — settled 3-month chart, fully drawn.

## Draw-in on Trends load — light (`draw-in-light/`)

Same cold-open flow as the dark sequence, OS appearance light, captured as a
~110 ms screenshot burst (relative times in filenames):

- `01-today-pre-tap-t0.10s.png` — Today, pre-tap.
- `02-reveal-early-t0.21s.png` — dots at partial opacity, line stroked
  through the first segment.
- `03-reveal-mid-t0.33s.png` — mid-sweep.
- `04-reveal-late-t0.44s.png` — sweep nearly complete.
- `05-settled-t0.70s.png` — resting chart.

## Reduce Motion — instant render (`reduce-motion/`)

Reduce-motion E2E build (`EXPO_PUBLIC_SLACKS_E2E_REDUCE_MOTION=true`; the
harness overrides `AccessibilityInfo.isReduceMotionEnabled` to `true`, the
exact read the draw-in branches on). Same open-Trends flow, ~110 ms burst:

- `01-today-t0.10s.png` — Today, pre-tap.
- `02-instant-fully-drawn-t0.21s.png` — the very next captured frame: Trends
  with the chart **fully drawn** — no partial line, no faint dots, no reveal.
- `03-static-t0.60s.png` — byte-identical rendering ~0.4 s later (every
  subsequent burst frame was identical) — nothing animating.

The extended `mobile/.maestro/reduce-motion.yaml` flow (which now navigates
to Trends and asserts the data-fed chart canvas is present) passed against
this build, as did `mobile/.maestro/trends.yaml` on the default motion-on
build.
