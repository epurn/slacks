# FTY-343 — Segmented control unselected label legible in dark mode

Running-app visual evidence that the shared native `SegmentedControl`
(`mobile/components/ui/SegmentedControl.tsx`) now renders in the app's **resolved**
theme, so the **unselected** segment label is legible (WCAG AA) against the dark
app surface — the reported SignInScreen "Create account" defect from PR #294.

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

## Verdict

In dark mode the native control renders in the system's dark segmented-control
style: unselected titles are the platform's near-white label colour on the dark
segment fill (contrast well above the 4.5:1 AA normal-text bar), where before the
light-appearance control put a dark label on the dark surface. Both segments were
checked as the unselected one. Light mode and the Settings / Trends / onboarding
call sites are visually unchanged.
