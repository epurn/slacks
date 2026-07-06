# FTY-247 — Visual-review mode presets: running-app evidence

Captured on the iOS simulator (iPhone, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the committed
`mobile/.maestro/visual-review-smoke.yaml` entry point — each preset opened by
deep link and captured only after its `visual-review-settled:<preset>` marker
appeared. No rebuild between presets: all states are one running binary + Metro,
switched purely at runtime by the deep link.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `today-populated-light.png` | `today.populated` | `fatty://__visual-review?preset=today.populated&theme=light` | Populated day (245/2,000 kcal · 12%, Greek yogurt + Banana timeline with provenance icons) in the forced **light** theme |
| `trends-populated-dark.png` | `trends.populated` | `fatty://__visual-review?preset=trends.populated&theme=dark` | Trends weight-trend chart (75.7 kg, ↓0.5) + intake-adherence card in the forced **dark** theme |
| `today-empty-light.png` | `today.empty` | `fatty://__visual-review?preset=today.empty&theme=light` | Empty-state preset: 0/2,000 kcal, "Log your first thing" — the same binary switched back from populated to empty at runtime |
| `settings-list-light.png` | `settings.list` | `fatty://__visual-review?preset=settings.list&theme=light` | The settings route's top-level list reached via public navigation |
| `today-signed-out-light.png` | `today.signed_out` | `fatty://__visual-review?preset=today.signed_out&theme=light` | The signed-out sign-in surface, reached by clearing the synthetic session |

The three Acceptance-Criteria smoke presets are the first three rows
(`today.populated` light, `trends.populated` dark, `today.empty`). The last two
demonstrate the route-navigation and session-clear mechanisms for the rest of
the in-scope manifest.
