# FTY-239 — End-of-Sweep Visual Audit: Onboarding (mobile)

In-depth, eyes-on visual verification of the Onboarding wizard after the
accent-as-text (FTY-207..212) and type-scale (FTY-213..217) mechanical sweeps.
This story ships **evidence only** — no product code changes.

## How the evidence was captured

- Captured on the **iOS simulator** (iPhone 17 Pro, iOS 26.5) against this
  story's E2E debug build (`EXPO_PUBLIC_FATTY_E2E=true`, `expo prebuild` +
  `pod install` + `xcodebuild`, installed on a dedicated leased simulator with
  its own Metro).
- Driven through the **FTY-247 / FTY-266 visual-review presets** by deep link —
  `fatty://__visual-review?preset=<name>&theme=light|dark` — never by walking a
  live RC backend or mutating live state. All fixture data is synthetic (the
  FTY-266 onboarding seeds: 175 cm / 70 kg / 1990, `mifflin_st_jeor_plus5`,
  2,000 kcal target).
- Each screenshot was taken **only after** the preset's
  `visual-review-settled:<preset>` marker appeared (the load-bearing wait), and
  the theme was forced through the preset's `theme` query param, so light and
  dark are the app's real rendered output, not an OS-appearance toggle.
- Ad-hoc Maestro capture flow (not committed): opened each of the three
  onboarding presets in light + dark, plus a toggle on the measurements step
  (tap the *other* formula chip) so the FTY-211 accentText label is proven both
  selected and unselected on the same element.

## States captured (Scope checklist)

Every onboarding step, in order, light + dark:

| # | State | Preset | Light | Dark |
|---|-------|--------|-------|------|
| 1 | Step 1 — goal + pace | `onboarding.goal` | `onboarding-goal-light.png` | `onboarding-goal-dark.png` |
| 2 | Step 2 — measurements + formula (Higher +5 **selected**) | `onboarding.measurements_formula` | `onboarding-measurements-formula-light.png` | `onboarding-measurements-formula-dark.png` |
| 3 | Step 2 — formula toggled (Higher +5 now **unselected**, Lower −161 selected) | `onboarding.measurements_formula` + tap | `onboarding-measurements-formula-toggled-light.png` | `onboarding-measurements-formula-toggled-dark.png` |
| 4 | Step 3 — target reveal | `onboarding.target_reveal` | `onboarding-target-reveal-light.png` | `onboarding-target-reveal-dark.png` |

## Sweep-outcome verdicts

### Accent-as-text (FTY-211)

The onboarding wizard has exactly **one** accent-as-text site: the selected
metabolic-formula chip label in step 2 (`MeasurementsStep.tsx:194-201`),
`color: selected ? colors.accentText : colors.text`. It is verified in both
its selected and unselected states, in both themes:

| Site | Selected (accentText) | Unselected (colors.text) | AA against chip surface (`surfaceRaised`) | Verdict |
|------|-----------------------|--------------------------|-------------------------------------------|---------|
| Formula chip label — **light** | "Higher baseline (+5)" renders `accentText` `#92400E` (warm brown), amber `accent` border | "Lower baseline (−161)" renders `text` `#1C1C1E`; after toggle the same "Higher baseline (+5)" label renders `text` | `#92400E` on `#FFFFFF` ≈ **8.9:1** (AA ✓, normal text needs 4.5:1) | **pass** |
| Formula chip label — **dark** | selected chip renders `accentText` `#F5A623` (amber) | unselected chip renders `text` `#F2F2F7`; toggle confirms the same on the other chip | `#F5A623` on `#2C2C2E` ≈ **6.7:1** (AA ✓) | **pass** |

- The site renders `colors.accentText` (not `colors.accent`) when selected —
  confirmed by the warm-brown label in light mode (`#92400E` is visibly
  distinct from the amber `#E8960C` *border* on the same chip).
- It is comfortably AA-legible against the chip's `surfaceRaised` background in
  both themes.
- **Observation (not a defect):** in dark mode `accentText` and `accent` are the
  same token value (`#F5A623`, `theme/colors.ts:73,75`). The selected label is
  still AA-legible (≈ 6.7:1), so this satisfies the accent-as-text principle;
  it is recorded here only for transparency, not filed as a defect.

Every other amber in onboarding is non-text and correct: the selected chip
border (`accent`), the Stepper progress dots (`accent`), and the primary button
fill (label uses `accentForeground` on the amber fill — dark text on amber,
legible in both themes). None of these are accent-as-text sites.

### Type scale (FTY-213..217)

All onboarding text renders on the shared `typeScale` tokens
(`components/onboarding/styles.ts`), with **no hardcoded font sizes** in the
step components. Verified regression-free across every capture:

| Step | Elements checked | Verdict |
|------|------------------|---------|
| 1 goal | `largeTitle` header, `body` subtitle, `footnote` uppercase section labels, `footnote` pace caption, native segmented controls | no clip / wrap / truncation — **pass** |
| 2 measurements | `largeTitle` header, `body` subtitle + inputs, `footnote` field/section labels, `subhead 600` formula chip labels, `footnote` descriptions | no clip / wrap / truncation — **pass** |
| 3 target reveal | `largeTitle` header, `heroDisplay` (56) "2000" hero number, `title3` "kcal / day" unit, `footnote` provenance + reveal note | hero number crisp and un-clipped; no mis-size — **pass** |

The multi-line strings that wrap (the auto-detect note, the formula preference
note, the reveal note) wrap cleanly at their intended sizes with no clipping or
overflow — i.e. intended wrapping, not a type-scale regression.

## Defects

**None observed.** No accent/text-color, type-scale, layout, legibility, or
theme defect was found on the Onboarding screen in either light or dark mode.
Per the story's "file, do not fix" rule there is consequently nothing to file as
a planner note. (Had any defect been present, it would have been filed as an
`out_of_scope_bug` planner note with the screenshot attached, and left unfixed.)

## Acceptance criteria

| Criterion | Verdict |
|-----------|---------|
| `docs/verification/FTY-239/` has light+dark screenshots for every Scope state + this `findings.md` with a state-by-state verdict | pass |
| Every accent-as-text site on Onboarding confirmed `accentText`-rendered and AA-legible in the evidence | pass |
| Type-scale rendering confirmed regression-free in the evidence | pass |
| Every observed defect has a planner note; none fixed here | pass (no defects observed → no notes; no code changed) |
| PR body embeds the key screenshots (first revision) | pass |
