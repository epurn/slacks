# FTY-313 — Visual audit: `Make it exact` barcode/label flow — running-app evidence

End-to-end visual verification of the FTY-311/312 exact-evidence sub-flow on the
**running iOS app** (iOS 26.5 simulator, `Slacks.app` built with
`EXPO_PUBLIC_SLACKS_E2E=true`). Every state is opened **directly** over a
synthetic low-trust "Peanut butter toast" entry through the correction-owned
visual-review seam (`mobile/components/correction/visualReviewSeam.ts`) — the
FTY-247 deep-link entry point, never a scripted tap on a rendered row — and
screenshotted by `mobile/.maestro/exact-evidence-visual-review-seam.yaml`.

No backend, camera, or live barcode/label is involved: the eligible/applied
items, the exact/fallback proposals, the no-proposal copy, and the label
`takePhoto` fixture are all synthetic (`mobile/e2e/exactEvidenceFixtures.ts`),
served through the E2E mock-fetch path. All seams are gated behind `isE2EMode()`
and inert in release builds.

## Screenshots

| File | Preset | Proves (acceptance criterion) |
|------|--------|-------------------------------|
| `exact-eligible-light.png` / `exact-eligible-dark.png` | `correction.exact_eligible` | `Make it exact` is **visible** on a low-trust (`≈ Rough estimate`, `model_prior`) item — light **and** dark. |
| `exact-applied-light.png` / `exact-applied-dark.png` | `correction.exact_applied` | The applied end state: same item updated **in place** — source now `Open Food Facts` (barcode provenance icon), `Make it exact` **hidden**, a single timeline row (no duplicate), hero recomputed to 210 kcal — light **and** dark. Together with `exact_eligible`, shows the nudge appears **only** on eligible items. |
| `exact-choose-light.png` / `exact-choose-dark.png` | `correction.exact_choose` | The exact-evidence choice surface: **Scan barcode**, **Type barcode**, **Capture nutrition label**, and **Cancel** — no overlap, no clipped text. |
| `exact-barcode-exact-light.png` / `exact-barcode-exact-dark.png` | `correction.exact_barcode_exact` | The typed-barcode **exact** proposal preview: `Exact match · Open Food Facts`, `Now → After` nutrition, amount stepper, `Apply`. |
| `exact-barcode-fallback-light.png` / `exact-barcode-fallback-dark.png` | `correction.exact_barcode_fallback` | The **fallback** proposal preview: a boxed notice `No exact match from that barcode. This is the best rough fallback.` + `≈ Rough fallback · Rough estimate` — visually distinct from the exact preview and never labelled exact. |
| `exact-no-proposal-light.png` / `exact-no-proposal-dark.png` | `correction.exact_no_proposal` | The no-proposal error: calm, actionable (`Try again` / `Change match` / `Manual edit`), and the item behind is **unchanged** (still `≈ Rough estimate`, `Make it exact` still offered). |
| `exact-label-framing-light.png` | `correction.exact_label` | The nutrition-label capture surface **presented from the correction flow** (`Fit the nutrition label inside the frame`, framing guide, flash, shutter). |
| `exact-label-save-photo-off-light.png` | `correction.exact_label` (after shutter) | The post-capture preview with the **`Save this photo` toggle OFF by default** (discard-by-default), plus `Retake` / `Upload`. |

## Notes on selectors & detents (why the flow waits the way it does)

- The `make-exact` states open at the correction sheet's **large, dimmed detent**,
  where iOS collapses the in-modal accessibility subtree (ratified FTY-272). So on
  iOS the flow waits on the sheet's own outer label (`Peanut butter toast details`,
  reachable on both platforms) before screenshotting; the in-modal
  `visual-review-settled:<preset>` marker wait is Android-only. The two
  normal-detent presets (`exact_eligible` / `exact_applied`) sit at the undimmed
  medium detent, where the marker is reachable on both platforms.
- The `Make it exact` nudge and the applied `Open Food Facts` source **render**
  (see the screenshots) but their `Text`/`Pressable` a11y labels fold into their
  parents on iOS (FTY-346), so the flow does not text-assert them — the screenshot
  is the evidence and the settled marker is the load-bearing gate. The
  render-level jest coverage (`mobile/components/today/TodayScreenExactSeam.test.tsx`)
  asserts the same labels are present in the tree.
- The label-capture surface is a **separate full-screen modal** on top of the
  sheet, so its framing hint and shutter are reachable on iOS; the flow taps the
  shutter (backed by the synthetic `takePhoto` fixture, since the simulator has no
  camera) to reach the save-photo preview.

## How to reproduce

```
cd mobile
# lease a simulator slot, then build + install Slacks.app (EXPO_PUBLIC_SLACKS_E2E=true),
# repoint it at your Metro, and:
maestro --udid "$SLACKS_SIM_UDID" test .maestro/exact-evidence-visual-review-seam.yaml
```

The deep links are `slacks://__visual-review?preset=correction.exact_*&theme=light|dark`.
