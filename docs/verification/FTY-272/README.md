# FTY-272 — iOS smoke run must not assert native-sheet markers — running-app evidence

This story scopes the `correction.typeahead` / `correction.confirm_apply`
in-modal `visual-review-settled:<preset>` marker waits in the two committed
Maestro flows (`mobile/.maestro/visual-review-smoke.yaml`,
`mobile/.maestro/correction-visual-review-seam.yaml`) to Android only — the
platform FTY-263 ratified as the one where `NativeSheet`'s large/dimmed detent
keeps its in-modal content reachable to the accessibility tree. iOS still opens
both presets and captures their rendered sub-state; it just stops waiting on
the unreachable marker.

Both flows were run end to end on a leased iOS 26.5 simulator
(`Fatty-Slot-0`) against the E2E debug build (`EXPO_PUBLIC_FATTY_E2E=true`),
via `maestro --udid <udid> test <flow>.yaml`.

## Both committed flows complete green on iOS

```
$ maestro test .maestro/visual-review-smoke.yaml
... (19 presets) ...
$ echo $?
0
```

```
$ maestro test .maestro/correction-visual-review-seam.yaml
... (3 presets) ...
$ echo $?
0
```

Neither run has a single `FAILED` step. Previously (the bug this story fixes),
the `correction.typeahead` step in `visual-review-smoke.yaml` failed its
`Assert that id: visual-review-settled:correction.typeahead is visible` step
on iOS even though the sheet rendered correctly — reproduced twice by the
author note that opened this story. That assertion no longer runs on iOS.

## The platform split actually executes (not a silent no-op)

The relevant excerpt from the `visual-review-smoke.yaml` run
(`correction.typeahead`, the case that used to fail on iOS):

```
Open fatty://__visual-review?preset=correction.typeahead&theme=light... COMPLETED
Run common/accept-open-in-fatty.yaml... COMPLETED
Run flow when Platform is ANDROID...
Run flow when Platform is ANDROID... SKIPPED
Run flow when Platform is IOS...
  Assert that ".*Oatmeal.*" is visible... COMPLETED
Run flow when Platform is IOS... COMPLETED
Take screenshot correction-typeahead-light... COMPLETED
```

`Run flow when Platform is ANDROID... SKIPPED` proves the Android-only marker
wait (`extendedWaitUntil` + `assertVisible` on
`visual-review-settled:correction.typeahead`) does not even attempt to run on
this iOS device — it is not silently passing, it is correctly not entered.
The iOS branch runs instead, confirms the sheet itself rendered (its own
outer `"<item name> details"` label — the same "Oatmeal" fixture item every
correction preset uses), and the screenshot is taken. The identical pattern
appears for `correction.confirm_apply` in `correction-visual-review-seam.yaml`.

`correction.detail` (the medium, undimmed-detent preset, unaffected by this
story) keeps waiting on its in-modal marker on **both** platforms —
`Assert that id: visual-review-settled:correction.detail is visible...
COMPLETED` ran unconditionally, proving the marker wait was not touched for
that preset.

## iOS still captures both scoped presets' rendered settled sub-state

| Screenshot | Preset | Proves |
|------------|--------|--------|
| `correction-typeahead-light.png` | `correction.typeahead` | The Change-match panel at the large, dimmed detent with its candidate list **already loaded** ("Chicken, grilled, USDA · 165 kcal / 100g") — the same loaded sub-state FTY-263 documented, now captured without waiting on the unreachable marker. |
| `correction-confirm-apply-light.png` | `correction.confirm_apply` | The override panel with the item's current value **pre-filled** (`140` kcal, focused) — ready to edit, not a blank input. |
| `correction-detail-light.png` | `correction.detail` | Unaffected control: the medium, undimmed-detent preset still waits on (and reaches) its in-modal marker on iOS, exactly as before this story. |

## Android path (unchanged, retained CI gate)

This story does not change `.github/workflows/mobile-e2e.yml` (still
`PLATFORM=android ./verify-e2e.sh`) or the Android branch of either flow: the
`extendedWaitUntil` + `assertVisible` on
`visual-review-settled:correction.typeahead` /
`visual-review-settled:correction.confirm_apply` still run unconditionally
inside each flow's `when: platform: Android` block, unedited from FTY-263's
shipped version except for being wrapped in that conditional. No Android
emulator was available in this authoring environment to run the flow
directly (same constraint recorded in `docs/verification/FTY-269/README.md`);
the retained `mobile-e2e` CI workflow is the actual verification gate for the
Android path, per `mobile/.maestro/README.md`'s "CI coverage" section.

## Registration / scope

No screen-owned component, shared registry, preset, marker, or contract code
changed. The diff is confined to `mobile/.maestro/visual-review-smoke.yaml`,
`mobile/.maestro/correction-visual-review-seam.yaml`, and the public docs
(`mobile/.maestro/README.md`, `mobile/e2e/visualReview/README.md`,
`docs/verification/FTY-263/README.md`) that describe the marker-assertion
scope.
