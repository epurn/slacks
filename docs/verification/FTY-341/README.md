# FTY-341 — Today quick-add suggestion chips: running-app evidence

Captured on the iOS simulator (iPhone-class, iOS 26.5) from the hermetic
`today.suggestions` visual-review preset (FTY-247), which seeds a populated
`/food-suggestions` ranking on an otherwise-empty day through the E2E mock fetch
— no live backend. Driven by `mobile/.maestro/today-quick-add.yaml`; every
assertion in that flow passed.

The preset's seeded ranking (server order, canonical):
1. **Chicken burrito bowl** — a saved food (`saved_food_id` set → estimator-skip
   apply path on submit),
2. **Greek yogurt** — history-only,
3. **Black coffee** — history-only.

## `today-quick-add-light.png` — chip row renders above the composer (light)

The quiet, horizontally-scrollable chip row sits between the Today hero and the
composer, in canonical server order (Chicken burrito bowl · Greek yogurt · Black
coff… — the third scrolls off, showing the row is scrollable). Calm
design-system chips (control-background fill, no glass, no emoji). The empty day
keeps the shot focused on the chips.

## `today-quick-add-prefilled-light.png` — tap prefills the composer, no log

Tapping the **Chicken burrito bowl** chip drops its `submit_phrase`
("my usual burrito bowl") into the composer and focuses it (keyboard up, caret
present); the **Add** button turns amber (ready to submit). Nothing was logged —
the timeline still shows "Log your first thing". This is the deliberate
one-more-tap-to-submit behaviour (no accidental one-tap log from a mis-tap on a
scrolling row).

## `today-quick-add-dark.png` — chip row renders in dark mode

The same calm row in dark mode: chips read legibly against the dark surface,
consistent with the composer beneath.

## Notes

- The zero-suggestion and failed-fetch "no row at all" states, the saved-food
  estimator-skip apply path, the history-only estimator submit, focus-gating, and
  refresh-after-submit are covered by
  `mobile/components/TodayScreenQuickAdd.test.tsx` (flow-completion) and
  `mobile/components/today/QuickAddChips.test.tsx`.
- iOS folds each chip's visible label into its parent `Pressable`'s
  `accessibilityLabel` ("Suggestion: <label>"), so the Maestro flow asserts the
  folded label with a full-string regex rather than the bare glyph string.
