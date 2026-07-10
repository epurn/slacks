# FTY-237 — End-of-Sweep Visual Audit: Trends (mobile)

In-depth, eyes-on visual verification of the **Trends** screen after the
accent-as-text (FTY-207..212 / FTY-209) and type-scale (FTY-213..217) mechanical
sweeps. This is the single in-depth Trends pass that replaces the per-story sim
evidence those sweeps used to carry.

Evidence-only: **no product code changed.** Any defect observed is filed as a
planner note (see below), not fixed here.

## How the evidence was captured

Captured on the iOS simulator (iPhone 17, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the **FTY-247 visual-review presets** by
deep link — each state opened with `fatty://__visual-review?preset=<name>&theme=<light|dark>`
and captured only after its `visual-review-settled:<preset>` marker appeared.
No live-backend state walking; all data is FTY-247/FTY-264 synthetic fixtures.
No rebuild between states — one running binary + Metro, switched at runtime.

The capture flow was a throwaway Maestro flow (not committed — this story ships
evidence only) that reused the committed launcher's recipe: for each preset in
both themes, `openLink` → `common/accept-open-in-fatty.yaml` →
`extendedWaitUntil` on `visual-review-settled:<preset>` → `assertVisible: trends-screen`
→ `takeScreenshot`. The `trends.adherence_retry` steps also asserted the
"Try again" text before capture. All markers and assertions passed
(`maestro test` exit 0).

Reproduce:

```
fatty://__visual-review?preset=trends.populated&theme=light|dark
fatty://__visual-review?preset=trends.empty&theme=light|dark
fatty://__visual-review?preset=trends.adherence_retry&theme=light|dark
```

## Screenshots

| Screenshot | Preset | Theme |
|------------|--------|-------|
| `trends-populated-light.png` | `trends.populated` | light |
| `trends-populated-dark.png` | `trends.populated` | dark |
| `trends-empty-light.png` | `trends.empty` | light |
| `trends-empty-dark.png` | `trends.empty` | dark |
| `trends-adherence-retry-light.png` | `trends.adherence_retry` | light |
| `trends-adherence-retry-dark.png` | `trends.adherence_retry` | dark |

## State-by-state verdict

| State | Theme | Rendered content | Accent-text sites present | Verdict |
|-------|-------|------------------|---------------------------|---------|
| `trends.populated` | light | Headline `75.7 kg · ↓0.5 this month`, range selector, weight-trend chart (EWMA line over daily points), adherence summary (`Avg 1860 kcal/day`, `9/12 days on target`) + strip | headline delta, `+ Log weight` | **PASS** |
| `trends.populated` | dark | Same content on elevated charcoal (`surface #1C1C1E`, cards `#2C2C2E`) | headline delta, `+ Log weight` | **PASS** |
| `trends.empty` | light | `Log your first weigh-in` weight-card invite; `No meals logged in this range yet. / Your logged meals will show up here.` adherence invite | `+ Log weight` | **PASS** |
| `trends.empty` | dark | Same, elevated charcoal | `+ Log weight` | **PASS** |
| `trends.adherence_retry` | light | Weight card still populated; adherence card in error/retry: `Could not load your summary (status 500).` + `Try again` | headline delta, `+ Log weight`, `Try again` | **PASS** |
| `trends.adherence_retry` | dark | Same, elevated charcoal | headline delta, `+ Log weight`, `Try again` | **PASS** |

## Sweep-outcome verification

### Accent-as-text (FTY-209): every accent-text site renders `accentText`, AA-legible

Trends has three accent-as-text sites (`components/TrendsScreen.tsx`), all
confirmed rendering `colors.accentText` (not `accent`) and legible against their
surface in the captures:

| Site | Code | Light (`accentText #92400E`) | Dark (`accentText #F5A623`) |
|------|------|------------------------------|------------------------------|
| Headline delta (`↓0.5 this month`, goal-aware "toward") | `TrendsScreen.tsx:443` | deep-amber on canvas — legible | bright-amber on canvas — legible |
| `+ Log weight` | `TrendsScreen.tsx:491` | deep-amber on white card — legible | bright-amber on `#2C2C2E` card — legible |
| `Try again` (retry) | `TrendsScreen.tsx:537` | deep-amber on white card — legible | bright-amber on `#2C2C2E` card — legible |

The amber **chart line** and on-target strip cells correctly keep the decorative
`accent` (they are graphics, not text). In light mode the sites render the
dark-brown `#92400E` variant — the point of the FTY-209 sweep — not the bright
`#F5A623` amber that fails AA on a light surface.

**AA basis:** `accentText`-on-`surface` contrast is gated at ≥4.5:1 by
`mobile/theme/theme.test.ts:170` (light `#92400E` on `#F2F2F7`) and `:190`
(dark `#F5A623` on `#1C1C1E`). The headline delta sits directly on the page
canvas (`surface`), so it is covered directly. The two card sites sit on
`surfaceRaised` (`#FFFFFF` light — a lighter background than `surface`, so
contrast only increases; `#2C2C2E` dark — the amber stays clearly separated),
and both read as clearly legible in the captures.

**Verdict: PASS** — no accent-text site renders the AA-unsafe `accent` token;
all are legible in light and dark.

### Type-scale (FTY-217): rendering is regression-free

All Trends text renders on the `typeScale` tokens
(`TrendsScreen.tsx:726,731,750,764,778,781,782,785,788,794`) with no clipped,
wrapped, truncated, or visibly mis-sized text in any capture:

- `Trends` large title and the `75.7 kg` display headline (`ThemedNumber`,
  `title1`) render at full size with no clipping.
- Section labels (`WEIGHT TREND`, `INTAKE ADHERENCE`), `Avg 1860 kcal/day`,
  `9/12 days on target`, chart axis labels (`76.2 kg`, `74.8 kg`, `June 12`,
  `Today`), the empty invites, and the `status 500` error copy all render fully
  on a single line each, no overflow.
- The range selector segments (`1 month` / `3 months` / `6 months`) fit without
  truncation in both themes.

**Verdict: PASS** — no type-scale regression observed.

## Defects observed (filed, not fixed)

1. **Adherence strip reads as empty at rest, contradicting the "9/12 days on
   target" summary** (`trends.populated`, both themes). In the populated capture
   the per-day adherence strip below `Avg 1860 kcal/day · 9/12 days on target`
   shows only faint neutral (`no-data`) cells — no amber on-target or coral
   off-target cells are visible without horizontally scrolling. Root cause is
   ordering + fixture shape, not the accent/type sweeps: the strip
   (`components/AdherenceStrip.tsx`) renders days oldest-first, and the
   visual-review range fixture (`mobile/e2e/fixtures.ts:386` `e2eDailySummaryRange`)
   only marks the most-recent 12 days as logged (`has_intake:true`) while all
   earlier days in the ~1-month window are `has_intake:false` → classified
   `no-data`. So the meaningful cells sit off the right edge at rest and the
   strip looks inert next to a headline that says 9 days were on target. Filed as
   `out_of_scope_bug` (see PR planner notes); screenshot:
   `trends-populated-light.png` / `trends-populated-dark.png`.

No other visual defects were observed. Accent-text and type-scale outcomes are
clean across all six states.
