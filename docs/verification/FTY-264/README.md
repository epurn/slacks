# FTY-264 — Visual-review seam: Trends adherence-retry sub-state

Captured on the iOS simulator (iPhone, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the committed
`mobile/.maestro/visual-review-smoke.yaml` — extended in this story with a step
that opens `trends.adherence_retry` by deep link and waits for its
`visual-review-settled:trends.adherence_retry` marker before capturing. Same
running binary + Metro as the rest of the flow, no rebuild between presets.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `trends-adherence-retry-light.png` | `trends.adherence_retry` | `fatty://__visual-review?preset=trends.adherence_retry&theme=light` | The adherence card's retry state — "Could not load your summary (status 500)." + a "Try again" button — reached via a range-read error fixture, with the weight card alongside it still rendering its normal populated series (75.7 kg, ↓0.5), in the forced **light** theme |

## How the state is reached

No Trends-code behaviour seam: `TrendsScreen` already renders the adherence
card's error/retry UI whenever the `/daily-summary/range` read rejects. The
preset (`mobile/components/trends/visualReviewPresets.ts`) registers itself
through FTY-247's `registerVisualReviewPreset` API and overrides only the
`/daily-summary/range` response with an HTTP 500 — the `/weight-entries` read is
left on the default populated fixture, so only the adherence card fails, not the
whole screen. Registration lives in Trends-owned code; the shared registry
(`e2e/visualReview/registry.ts`) and manifest (`e2e/visualReview/presets.ts`)
are untouched.

## Verification

```sh
cd mobile
maestro test .maestro/visual-review-smoke.yaml
```

Full flow output (this run): every step through `trends.adherence_retry`'s
settled marker, the `trends-screen` assertion, and the "Try again" text
assertion completed, in the same run as the pre-existing FTY-247 presets.
