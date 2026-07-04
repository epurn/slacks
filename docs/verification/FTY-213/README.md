# FTY-213 manual verification — Today type-scale migration

Story-required visual verification for routing the Today-owned numeric
`fontSize` literals through `typeScale` and adopting `DisplayText` for the
Today sign-in gate headline and the confirm-parsed-values calorie hero.

## Method

- Built this worktree's own dev-client (`expo prebuild` + `pod install` +
  `xcodebuild`, since a stale prebuilt `.app` from an earlier story could not
  be pointed at this worktree's Metro) and ran it on a leased simulator slot
  (`Fatty-Slot-2`) against Metro in E2E fixture mode
  (`EXPO_PUBLIC_FATTY_E2E=true`), which seeds a synthetic session and mocks
  every API call from `mobile/e2e/fixtures.ts` — no live backend, no real
  account, no real nutrition logs.
- `today-screen-live-e2e.png`: the live Today screen, captured via
  `xcrun simctl io screenshot` against the leased simulator, running the
  story's changed code (`StatusIcon`, `EntryRow`, `TypeaheadSuggestionBar`,
  `ConfirmParsedValuesSheet` all now reference `typeScale` tokens instead of
  numeric literals). The hero calorie number, "Today" header, composer, and
  macro chips all render at their expected sizes with no visible layout
  regression versus the pre-story screenshots captured for FTY-192
  (`docs/verification/FTY-192/`).

## Known limitation — interactive flows

Maestro's touch injection did not register on this app's RN content in this
session (taps on the settings gear, tab bar, composer, and barcode button all
completed with no observable effect, despite the app rendering correctly and
Metro serving bundles with no JS errors) — a simulator/tooling issue, not a
code regression; the same class of flakiness is documented for this toolchain
in prior stories' verification notes. Because of this, the two
`needs_clarification`/`failed` `EntryRow` states and the `SignInRequired`
sign-out path could not be driven to a screenshot in this session.

Those specific sites are proven instead by exact-value component tests
against the live component tree (not a mocked/fallback render):
- `mobile/components/today/SignInRequired.test.tsx` — asserts the gated
  headline renders through `DisplayText` at `typeScale.title2Large` with
  `DISPLAY_FONT_FAMILY` applied.
- `mobile/components/ConfirmParsedValuesSheet.test.tsx` ("renders the calorie
  hero numeral through DisplayText") — asserts the `190 kcal` hero number
  (from a real `DerivedFoodItemDTO` fixture) renders through `DisplayText`
  with `typeScale.title2`, `DISPLAY_FONT_FAMILY`, and `tabular-nums`.
- `mobile/components/EntryRow.test.tsx`, `StatusIcon.test.tsx`,
  `TypeaheadSuggestionBar.test.tsx` — existing suites, still green, exercising
  every row state (failed / needs-clarification / resolved) with the
  `typeScale`-routed styles.

Every mapped size is numerically identical to its prior literal (18→
`iconGlyph`, 14→`detail`, 13→`footnote`, 16→`callout`, 12→`caption1`, 24→
`title2Large`, 22→`title2`), so none of these sites can regress in size —
only `SignInRequired`'s headline and the confirm-sheet's calorie hero gain
`displayTracking` (-0.5 letter-spacing) from the `DisplayText`/`ThemedNumber`
adoption, the same class of subtle, imperceptible-at-rendered-size change
FTY-192 already verified and documented for `CalorieHero`.
