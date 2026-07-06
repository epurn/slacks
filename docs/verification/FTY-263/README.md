# FTY-263 — Visual-review seam: correction sheet sub-states — running-app evidence

The presets registered by `mobile/components/correction/visualReviewSeam.ts` are
driven through FTY-247's deep-link entry point against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`). Each preset opens the correction sheet **directly
in the named mode** via the E2E-only initial-state seam — no tap on any rendered
row — over the synthetic resolved "Oatmeal" entry (140 kcal, the same fixture
`correction.yaml`/`correction-beat.yaml` already use).

The screenshots below were captured on the iOS simulator (`Fatty-Slot-0`,
iOS 26.5) to show each rendered sub-state. The **load-bearing regression
assertion** — waiting on each in-modal `visual-review-settled:<preset>` marker —
runs in CI on Android (see "Where the marker is asserted" below).

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `correction-detail-light.png` | `correction.detail` | `fatty://__visual-review?preset=correction.detail&theme=light` | The quick-fix ("normal") mode: Portion stepper (`1 cup`, `140 kcal · P5 C27 F3`), the "Change match" lever, and the Advanced override rows, all populated from the synthetic entry — reached via the seam, not a tap on a timeline row. |
| `correction-typeahead-light.png` | `correction.typeahead` | `fatty://__visual-review?preset=correction.typeahead&theme=light` | The Change-match panel opens directly at the sheet's large detent, with its candidate list **already loaded** ("Chicken, grilled, USDA · 165 kcal / 100g") from the shared `source-candidates` fixture — not the blank "no alternatives" state a naive initial-mode-only seam would leave it in. |
| `correction-confirm-apply-light.png` | `correction.confirm_apply` | `fatty://__visual-review?preset=correction.confirm_apply&theme=light` | The advanced override panel opens directly with the item's current value **pre-filled** (`140` kcal, focused, ready to edit) rather than a blank input — "confirm/apply" is a real, in-progress action, not an empty form. |

## The in-modal settled marker

Each preset renders its `visual-review-settled:<preset>` marker **inside the
correction sheet's own modal subtree** (`CorrectionSheet`'s `settledMarkerTestID`,
see `mobile/components/CorrectionSheet.tsx`), gated on that mode's async state
settling:

- `correction.detail` — the sheet + synthetic item have rendered;
- `correction.typeahead` — `candidatesLoading === false` **and** the candidate
  list is painted (the expanded, dimmed-detent case that failed on PR #230);
- `correction.confirm_apply` — the override panel is up with its pre-seeded draft.

A marker rendered at the navigator level (FTY-247's shared
`VisualReviewSettleOverlay`) cannot serve these sub-states: the presented sheet
sets `accessibilityViewIsModal` on the tested platform, so anything **behind** it
is (correctly) unreachable to assistive tech and to Maestro/XCUITest. That is the
gap PR #230 hit — it fell back to `waitForAnimationToEnd` because the navigator
marker was occluded. Moving the marker inside the sheet closes it, mirroring the
already-merged FTY-262 (`today.confirm_parsed`) and FTY-265 (`weight.sheet`)
in-modal markers. **No animation-wait fallback remains** in either committed flow.

## Where the marker is asserted (the tested platform is Android)

`NativeSheet` (which `CorrectionSheet` presents through) is a real UIKit detent
sheet on iOS and a `Modal`-based bottom sheet off iOS. Its own docstring records
that the iOS native presentation does **not** expose its content to the
accessibility tree the way the Android `Modal` fallback does — "CI stayed green
while iOS was broken" — which is exactly why `correction.yaml` and every other
sheet-content flow are verified on the **Android emulator** in CI
(`.github/workflows/mobile-e2e.yml` runs `PLATFORM=android ./verify-e2e.sh`), not
on the iOS simulator.

So the marker assertions live in the Android-run flows:

- `mobile/.maestro/visual-review-smoke.yaml` opens `correction.detail` and
  `correction.typeahead` and waits on their in-modal markers
  (`visual-review-settled:correction.detail` / `…typeahead`).
- `mobile/.maestro/correction-visual-review-seam.yaml` opens all three sub-states
  and waits on each in-modal marker — including `correction.confirm_apply`.

On this Mac's iOS simulator the sheet renders correctly (the screenshots above are
that render) but the native detent presentation collapses the sheet's content
subtree out of the accessibility hierarchy — a live `maestro hierarchy` dump while
the typeahead sheet is up exposes only the sheet's outer `"Oatmeal details"`
label, no inner content (Portion / Change match / the candidate / the marker).
That is a platform property of the iOS presentation, identical for plain sheet
text and the marker alike; the iOS screenshots are therefore visual evidence of
the rendered sub-states, and the Android CI flows are the automated marker
regression guard.

The dedicated flow also relaunches the app between each preset rather than
switching straight from one seam-opened sheet to the next: a native sheet is a
real presented controller, so activating a new preset while one is still on-screen
races its dismissal against the next preset's presentation. That race only exists
between two consecutive seam-opened presets in one running session — unreachable
in real usage, where nothing ever activates a second preset while the first's
sheet is still open — so the flow sidesteps it by relaunching rather than adding
product code to chase a harness-only interaction.

## Registration

All three presets are registered through FTY-247's `registerVisualReviewPreset`
API from `mobile/components/correction/visualReviewSeam.ts` — correction-owned
code, no edits to the shared registry (`mobile/e2e/visualReview/registry.ts`) or
manifest (`mobile/e2e/visualReview/presets.ts`).
