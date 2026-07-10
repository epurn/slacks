# FTY-344 — Adherence strip lands on recent days: simulator evidence

Visual proof that with the FTY-344 fix, the populated Trends adherence strip
rests on its **recent (newest) end**, so the meaningful on-target / off-target
cells are visible at rest — with no manual horizontal scroll — and the strip
visibly agrees with the "9/12 days on target" summary above it.

## How the evidence was captured

Captured on the iOS simulator (iPhone 17, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the **FTY-247 visual-review preset**
`trends.populated` by deep link — the same fixture the FTY-237 Trends audit
used. That preset serves the default E2E `daily-summary/range` fixture
(`mobile/e2e/fixtures.ts` → `e2eDailySummaryRange`), which is exactly the
FTY-344 reproduction: a 1-month window where only the **most recent 12 days**
are logged (mostly on-target, every fifth day off-target) and all earlier days
are `no-data` — i.e. a realistic recent-logging window longer than the logged
history.

Each state was opened with
`fatty://__visual-review?preset=trends.populated&theme=<light|dark>` via a
throwaway Maestro flow (not committed — evidence only) that reused the
committed launcher recipe: `openLink` → `common/accept-open-in-fatty.yaml` →
`extendedWaitUntil` on `visual-review-settled:trends.populated` →
`assertVisible: trends-screen` → `assertVisible: "On target: .* days"` →
`takeScreenshot`. All assertions passed (`maestro test` exit 0). The
screenshots capture the strip **at rest** — no scroll gesture was performed at
any point in the flow.

Reproduce:

```
fatty://__visual-review?preset=trends.populated&theme=light|dark
```

## Screenshots

| Screenshot | Preset | Theme |
|------------|--------|-------|
| `trends-populated-at-rest-light.png` | `trends.populated` | light |
| `trends-populated-at-rest-dark.png` | `trends.populated` | dark |

## What the captures show (vs. the pre-fix FTY-237 evidence)

Both themes show the Intake Adherence card with the `Avg 1860 kcal/day` /
`9/12 days on target` headline and, directly beneath it, the strip resting on
its recent end: **amber filled on-target cells and coral ring-bordered
off-target cells** — the meaningful tail of the fixture window.

Contrast with the pre-fix `docs/verification/FTY-237/trends-populated-*.png`
(captured from the same preset on the same fixture): there the strip rested on
its **old** end and showed only faint neutral `no-data` cells, visibly
disagreeing with the "9/12 days on target" summary. The FTY-344 change
(`AdherenceStrip` requesting `scrollToEnd({ animated: false })` on mount,
range-key change, and content-size change) is the only difference.

Cell semantics are unchanged (oldest→newest order, states, colors, shapes,
labels, testIDs, tap targets — asserted by
`mobile/components/AdherenceStrip.test.tsx`), and older days remain reachable
by scrolling left; only the resting position changed.
