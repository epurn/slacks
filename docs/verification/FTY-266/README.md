# FTY-266 — Visual-review seam: onboarding steps — running-app evidence

Captured on the iOS simulator (iPhone, iOS 26.5) against this story's E2E debug
build (`EXPO_PUBLIC_FATTY_E2E=true`), driving the committed
`mobile/.maestro/visual-review-smoke.yaml` — the same flow FTY-247 ships,
extended here with the three onboarding-owned presets. Each screenshot was
taken only after its `visual-review-settled:<preset>` marker appeared. The full
smoke flow ran end to end in one pass (all `today.*` / `trends.*` presets plus
the three below), proving the new onboarding seam introduces no regression to
the presets FTY-247 already shipped.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `onboarding-goal-light.png` | `onboarding.goal` | `fatty://__visual-review?preset=onboarding.goal&theme=light` | The visual-review launch skips the E2E harness's boot-time onboarding-complete seed and opens the wizard directly on step 1 ("What's your goal?") — not the Today screen the seed would otherwise route to |
| `onboarding-measurements-formula-light.png` | `onboarding.measurements_formula` | `fatty://__visual-review?preset=onboarding.measurements_formula&theme=light` | The E2E-only initial-step seam opens the wizard directly on step 2 with a prefilled, synthetic form (175 cm / 70 kg / 1990) and the "Higher baseline (+5)" metabolic-formula chip already selected — reached via initial state, not simulated taps |
| `onboarding-target-reveal-light.png` | `onboarding.target_reveal` | `fatty://__visual-review?preset=onboarding.target_reveal&theme=light` | The wizard opens directly on step 3 with a synthetic, already-settled target reveal (2,000 kcal/day, provenance line "└ from your goal + your metrics") — no goal/profile API round trip, no reveal-fade wait |

## What this proves

- **Onboarding-complete-seed skip**: by default the E2E harness marks
  onboarding complete for the synthetic user at boot
  (`setupE2EMode()` → `markOnboardingComplete()`), so the wizard never
  renders — confirmed by every other flow in this same smoke run landing on
  Today, not onboarding. Activating an `onboarding.*` preset overrides the
  auth gate's onboarding status to `incomplete`
  (`onboardingStatusOverrideForVisualReview`, `components/onboarding/
  visualReviewOnboardingSteps.ts`), so these three screenshots show the wizard
  reached with no live backend state walk.
- **Step reached via initial-state seam, not scripted taps**: each preset seeds
  `useOnboardingWizard`'s `step` (and, for steps 2/3, the measurements/reveal
  state) via a lazy `useState` initializer keyed on the active visual-review
  preset — the Maestro flow only opens a deep link and waits for the settled
  marker; it never taps "Continue".
- **Settled marker per step**: each screenshot was gated on
  `visual-review-settled:<preset>` (the shared FTY-247 overlay, reachable here
  because the onboarding wizard renders no `Modal`/`accessibilityViewIsModal`
  subtree, unlike Today's confirm-parsed sheet).
- **No regression to FTY-247's presets**: the full committed smoke flow
  (`today.populated`, `trends.populated`, `today.empty`, `today.signed_out`,
  `today.populated` again post-reseed, then the three onboarding presets) ran
  in one Maestro invocation end to end with every step passing.
