# FTY-263 — Visual-review seam: correction sheet sub-states — running-app evidence

Captured on the iOS simulator (`Fatty-Slot-1`, iOS 26.5) against the E2E debug
build (`EXPO_PUBLIC_FATTY_E2E=true`), driving the presets registered by
`mobile/components/correction/visualReviewSeam.ts` through FTY-247's deep-link
entry point. Each preset opens the correction sheet **directly in the named
mode** via the E2E-only initial-state seam — no tap on any rendered row — over
the synthetic resolved "Oatmeal" entry (140 kcal, the same fixture
`correction.yaml`/`correction-beat.yaml` already use).

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `correction-detail-light.png` | `correction.detail` | `fatty://__visual-review?preset=correction.detail&theme=light` | The quick-fix ("normal") mode: Portion stepper (`1 cup`, `140 kcal · P5 C27 F3`), the "Change match" lever, and the Advanced override rows, all populated from the synthetic entry — reached via the seam, not a tap on a timeline row. |
| `correction-typeahead-light.png` | `correction.typeahead` | `fatty://__visual-review?preset=correction.typeahead&theme=light` | The Change-match panel opens directly at the sheet's large detent, with its candidate list **already loaded** ("Chicken, grilled, USDA · 165 kcal / 100g") from the shared `source-candidates` fixture — not the blank "no alternatives" state a naive initial-mode-only seam would leave it in. |
| `correction-confirm-apply-light.png` | `correction.confirm_apply` | `fatty://__visual-review?preset=correction.confirm_apply&theme=light` | The advanced override panel opens directly with the item's current value **pre-filled** (`140` kcal, focused, ready to edit) rather than a blank input — "confirm/apply" is a real, in-progress action, not an empty form. |

## How these were captured

The committed smoke flow (`mobile/.maestro/visual-review-smoke.yaml`) opens
`correction.detail` and waits for its `visual-review-settled:correction.detail`
marker — the automated regression guard for the AC. `correction-detail-light.png`
above is that flow's own screenshot.

`correction.typeahead` and `correction.confirm_apply` open the sheet at its
large, **dimmed** detent (`change-match`/`override` narrow the sheet to
large-only, see `useCorrectionSheet`'s `expanded`). On this simulator, that
dimmed native presentation makes every accessibility-tree query against the
base layer or the sheet's own content — the settled marker, plain text —
report not-found, even though the content renders correctly (compare the
screenshots above, captured from the exact same run). This is a query
limitation of that specific presentation style on this device, not a rendering
gap: `correction.detail`'s undimmed presentation is what the shared smoke flow
already proves the marker and content against with a real assertion. The
dedicated flow `mobile/.maestro/correction-visual-review-seam.yaml` captures
all three states, waiting on `waitForAnimationToEnd` for the two dimmed
presets instead of an accessibility assertion.

That flow also relaunches the app between each preset rather than switching
straight from one seam-opened sheet to the next: a native sheet is a real
presented `UIViewController` (react-native-screens' `formSheet`), so activating
a new preset while one is still on-screen races its native dismissal against
the next preset's presentation, and UIKit can silently drop the second
`present` call while a dismissal is in flight. That race only exists between
two consecutive seam-opened presets in one running session — unreachable in
real usage, where nothing ever activates a second preset while the first's
sheet is still open — so the flow sidesteps it by relaunching rather than
adding product code to chase a harness-only interaction.

## Registration

All three presets are registered through FTY-247's `registerVisualReviewPreset`
API from `mobile/components/correction/visualReviewSeam.ts` — correction-owned
code, no edits to the shared registry (`mobile/e2e/visualReview/registry.ts`)
or manifest (`mobile/e2e/visualReview/presets.ts`).
