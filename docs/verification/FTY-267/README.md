# FTY-267 — Visual-review seam: Settings edit sub-states — running-app evidence

Captured on the iOS simulator (iPhone, iOS 26.5) against a debug build of this
worktree (`EXPO_PUBLIC_FATTY_E2E=true`), driving the extended
`mobile/.maestro/visual-review-smoke.yaml` entry point — each sub-state preset
opened by deep link and captured only after its
`visual-review-settled:<preset>` marker appeared, with no simulated tap or
scroll gesture involved in reaching the sub-state itself.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `settings-goal-edit-light.png` | `settings.goal_edit` | `fatty://__visual-review?preset=settings.goal_edit&theme=light` | The E2E-only initial-state seam opens Settings with the goal editor (`goal-edit-card`) already active, seeded from the loaded goal (Lose · Steady) — not the `loss`/`steady` defaults, and not reached via a tap on the Goal row |
| `settings-body-edit-light.png` | `settings.body_edit` | `fatty://__visual-review?preset=settings.body_edit&theme=light` | The same seam opens the weight editor (`body-metric-edit-card`, "NEW WEIGHT (KG)") already active |
| `settings-appearance-light.png` | `settings.appearance` | `fatty://__visual-review?preset=settings.appearance&theme=light` | The seam scrolls the settings screen straight to the PREFERENCES section (large title collapsed to the small title, confirming a real scroll occurred) so the Appearance control is on screen with no manual scroll gesture |

All three presets are registered from settings-owned code
(`mobile/components/settings/visualReviewPresets.ts`) through FTY-247's
`registerVisualReviewPreset` API — no edits to the shared registry
(`e2e/visualReview/registry.ts`), the in-scope manifest (`presets.ts`), or any
other screen. The full extended smoke flow (all `today.*` / `trends.*` presets
plus these three settings sub-states) ran green in the same Maestro invocation:

```
maestro --udid <leased-sim-udid> test .maestro/visual-review-smoke.yaml
```

Every step — including the three settings sub-state presets — reported
`COMPLETED`, and each settings screenshot above was captured only after its
`visual-review-settled:settings.<sub-state>` marker appeared.

## Release-build inertness

The seam is proven inert outside E2E mode by unit tests (not just asserted by
comment):

- `mobile/components/settings/visualReviewPresets.test.ts` — `useSettingsVisualReviewSubState`
  resolves to `null` when `isE2EMode()` is false, even with a matching preset
  active.
- `mobile/components/SettingsScreen.test.tsx` (`Visual-review seam — Settings
  edit sub-states (FTY-267)` describe block) — with no active preset, or with
  `isE2EMode()` false, no edit card opens and the Preferences layout event never
  triggers a scroll.
