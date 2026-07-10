# FTY-235 — End-of-Sweep Visual Audit, Today: running-app evidence

Eyes-on rendering verification of the **Today** surfaces after the
accent-as-text (FTY-207..212) and type-scale (FTY-213..217) sweeps. This is the
single in-depth visual pass that replaces the per-story simulator screenshots
those mechanical sweep stories used to carry.

Captured on the iOS simulator (iPhone 17, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the **FTY-247 visual-review presets** by
deep link — no manual RC backend walking, no live state mutation. Each state is
one running binary + Metro, switched purely at runtime by the deep-link `preset`
and `theme` params. See `findings.md` for the state-by-state pass/fail verdict.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `today-populated-light.png` / `today-populated-dark.png` | `today.populated` | `fatty://__visual-review?preset=today.populated&theme=light\|dark` | Populated day (245 / 2,000 kcal · 12%, amber-fill hero bar, "1,755 to go", P/C/F chips, Greek yogurt + Banana timeline with source-icon provenance) in both themes |
| `today-empty-light.png` / `today-empty-dark.png` | `today.empty` | `fatty://__visual-review?preset=today.empty&theme=light\|dark` | Calm empty state (0 / 2,000 kcal · 2,000 to go, empty track, "Log your first thing") in both themes |
| `today-signed-out-light.png` / `today-signed-out-dark.png` | `today.signed_out` | `fatty://__visual-review?preset=today.signed_out&theme=light\|dark` | Signed-out sign-in gate ("Welcome back", native Sign in / Create account segmented control, amber-fill Sign in button) in both themes |
| `today-confirm-parsed-light.png` / `today-confirm-parsed-dark.png` | `today.confirm_parsed` | `fatty://__visual-review?preset=today.confirm_parsed&theme=light\|dark` | Confirm-parsed sheet (calorie hero "190 kcal", "Label scan" provenance, "Not yet counted" badge, **"Not now"** rendered `accentText`, "Looks right" amber-fill) in both themes |

## Key results

- **Accent-as-text (FTY-207..212) confirmed.** The confirm sheet's **"Not now"**
  — the accent-as-text text site reachable across these four states — renders
  `colors.accentText` (dark amber `#92400E` on white in light,
  bright amber `#F5A623` on charcoal in dark), *not* the raw fill `accent`, and
  reads AA against its surface. See `today-confirm-parsed-light.png` /
  `today-confirm-parsed-dark.png`. Amber **fill** sites (hero bar, Sign in /
  Looks right buttons) correctly render `accent` as a background — the
  fill-vs-text distinction the sweep set up holds.
- **Type-scale (FTY-213..217) confirmed regression-free.** No clipped, wrapped,
  truncated, or mis-sized text in any of the eight captures; display hero
  numerals render tabular and full-width.
- **One visual defect observed and filed, not fixed** (DEF-1 in `findings.md`):
  in the dark signed-out capture the native segmented control renders light-mode
  chrome, leaving the unselected **Create account** label dark-on-dark and
  illegible. Filed as an `out_of_scope_bug` planner note. This story ships
  evidence only — no product code changed.
- **Coverage boundary:** the `EntryRow` failed-parse / needs-clarification
  accentText sites (Retry, Edit as text, "Add a detail ›") are not reachable
  through these four presets and are deferred to FTY-342 — see the per-preset
  coverage table in `findings.md`.

## How the states were driven

The four presets are the FTY-247 in-scope manifest
(`mobile/e2e/visualReview/presets.ts` for `today.populated` / `today.empty` /
`today.signed_out`; `mobile/components/today/visualReviewConfirmParsed.ts`
registers `today.confirm_parsed` from Today's own lane). Each was opened via
`xcrun simctl openurl "<udid>" "fatty://__visual-review?preset=<name>&theme=<theme>"`
against the running dev-client (already pointed at the worktree's Metro), which
seeds the synthetic fixture, forces the theme, and navigates/opens the sub-state
with no scripted taps — then the settled frame was captured with
`xcrun simctl io "<udid>" screenshot`. All simulator work ran on a dedicated
leased slot (never the shared `booted` device). No real personal data appears in
any capture; every value is from FTY-247's synthetic visual-review fixtures.
