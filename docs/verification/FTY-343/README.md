# FTY-343 — Segmented control unselected label legible in dark mode

Running-app visual evidence that the shared native `SegmentedControl`
(`mobile/components/ui/SegmentedControl.tsx`) now renders in the app's **resolved**
theme, so the **unselected** segment label is legible (WCAG AA) against the dark
app surface — both reported reproductions: the SignInScreen "Create account"
defect from PR #294, and the onboarding goal screen's Direction/Pace controls.

## The fix

The wrapper now feeds the library's own `appearance` prop the resolved
`useTheme()` scheme (`appearance={scheme}`). Previously it passed no appearance,
so the native `UISegmentedControl` painted for the raw **device** scheme; when the
app rendered dark on a light device (or via the `ColorSchemeOverride` seam) the
control stayed in light appearance on the dark `colors.surface` and the unselected
label washed out. It stays the adaptive platform control — no hand-rolled restyle.

## How this evidence was captured

- Device: iPhone 17, iOS 26.5 simulator (leased slot), against the E2E debug
  build (`EXPO_PUBLIC_FATTY_E2E=true`) serving this branch's JS via Metro.
- Driven purely through the FTY-247 visual-review deep link
  (`fatty://__visual-review?preset=<name>&theme=<light|dark>`) — no manual state
  walking, no live personal data. The `&theme=` param forces the app's resolved
  theme via `ThemeProvider`'s override.
- **The device OS appearance was held to _light_ for every capture below**, so the
  `theme=dark` presets reproduce the exact **app-dark / device-light mismatch**
  that caused the original defect — and prove it fixed: the control now paints
  dark, tracking the app theme, not the device.

## Captures

| File | Preset / theme | What it proves |
|------|----------------|----------------|
| `signin-dark-create-account-unselected.png` | `today.signed_out` · dark (device light) | Reported case. "Sign in" selected → **"Create account" unselected** renders as legible white text on the dark control. |
| `signin-dark-sign-in-unselected.png` | `today.signed_out` · dark (device light) | The other segment unselected. "Create account" selected → **"Sign in" unselected** is legible white text. |
| `signin-light.png` | `today.signed_out` · light | Light mode unchanged — unselected "Create account" is dark text on the light control. |
| `settings-controls-dark.png` | `settings.list` · dark (device light) | No regression at the Settings call sites: Units, Appearance, and Weigh-in reminder controls all paint dark with every unselected label (Imperial / Light / Dark / Every 2 weeks / Monthly / Off) legible white. |
| `settings-controls-light.png` | `settings.list` · light | Settings call sites unchanged in light mode. |
| `goal-dark-direction-lose-pace-steady.png` | `onboarding.goal` · dark (device light) | Second reported case, default state. Direction "Lose" selected → **Maintain and Gain unselected**, legible white; Pace "Steady" selected → **Gentle and Faster unselected**, legible white. FTY-222 caption ("~0.5% of bodyweight / week — recommended") renders below the pace control. |
| `goal-dark-direction-gain.png` | `onboarding.goal` · dark (device light) | Direction "Gain" selected → **Lose and Maintain unselected**, legible; the gain pace options (Gentle/Steady) render with "Gentle" unselected. |
| `goal-dark-direction-maintain.png` | `onboarding.goal` · dark (device light) | Direction "Maintain" selected → **Lose and Gain unselected**, legible (Pace hidden by design for maintain). |
| `goal-dark-pace-gentle.png` | `onboarding.goal` · dark (device light) | Pace "Gentle" selected → **Steady unselected**, legible. |
| `goal-dark-pace-faster.png` | `onboarding.goal` · dark (device light) | Loss pace, "Faster" selected → **Gentle and Steady unselected**, legible on the 3-segment control. |
| `goal-light.png` | `onboarding.goal` · light | Onboarding GoalStep unchanged in light mode — unselected Direction/Pace labels are dark text on the light control. |
| `trends-range-dark.png` | `trends.populated` · dark (device light) | No regression at the Trends call site: the range control paints dark with "1 month" selected and **3 months / 6 months unselected**, legible white. |
| `trends-range-light.png` | `trends.populated` · light | Trends range control unchanged in light mode. |

Every segment of both GoalStep controls appears as the unselected one across the
dark captures: Direction — Lose (`…gain.png`, `…maintain.png`), Maintain
(`…lose-pace-steady.png`, `…gain.png`), Gain (`…lose-pace-steady.png`,
`…maintain.png`); Pace — Gentle (`…lose-pace-steady.png`, `…pace-faster.png`),
Steady (`…pace-gentle.png`, `…pace-faster.png`), Faster
(`…lose-pace-steady.png`).

## Verdict

In dark mode the native control renders in the system's dark segmented-control
style: unselected titles are the platform's near-white label colour on the dark
segment fill (contrast well above the 4.5:1 AA normal-text bar), where before the
light-appearance control put a dark label on the dark surface. Every segment of
the SignIn toggle and the onboarding Direction/Pace controls was checked as the
unselected one. Light mode and the Settings / Trends / onboarding call sites are
visually unchanged.
