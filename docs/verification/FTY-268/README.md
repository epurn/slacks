# FTY-268 — Visual-review seam: Capture sub-states

Captured on the iOS simulator (iPhone, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the committed
`mobile/.maestro/visual-review-smoke.yaml` — extended in this story with three
steps that open `capture.barcode_granted`, `capture.label_guidance`, and
`capture.confirm_parsed` by deep link and wait for each one's
`visual-review-settled:<preset>` marker before capturing. Same running binary +
Metro as the rest of the flow, no rebuild between presets.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `capture-barcode-granted-light.png` | `capture.barcode_granted` | `fatty://__visual-review?preset=capture.barcode_granted&theme=light` | The barcode scanner is already open — reticle, "Point at a barcode" guidance, torch, "Type it instead" — with no "Scan barcode" tap, and the camera permission already granted (the existing E2E harness default, FTY-194) |
| `capture-label-guidance-light.png` | `capture.label_guidance` | `fatty://__visual-review?preset=capture.label_guidance&theme=light` | The label-capture camera is already open on its framing guidance ("Fit the nutrition label inside the frame") with no "Capture label" tap |
| `capture-confirm-parsed-light.png` | `capture.confirm_parsed` | `fatty://__visual-review?preset=capture.confirm_parsed&theme=light` | The confirm-parsed-values sheet is already open over Today, showing the synthetic parsed values ("Granola bar", 190 kcal, P 4g / C 29g / F 7g), the "Label scan" provenance icon, and the "Not yet counted" badge — with no capture taps at all |

## How each state is reached

All three presets are registered through FTY-247's registration API
(`registerVisualReviewPreset`) from a new capture-owned module,
`mobile/components/today/captureVisualReview.ts` — the shared registry
(`e2e/visualReview/registry.ts`) and manifest (`e2e/visualReview/presets.ts`)
are untouched.

- **Initial-state seam**: `useTodayData.ts` reads the active capture preset
  (`useActiveCaptureVisualReviewPreset`, gated on `isE2EMode()`) once at mount
  and uses it as the initial value for `scannerOpen` / `labelCaptureOpen` —
  instead of only ever becoming `true` from the composer's press callbacks. The
  seam is a no-op (`null`) outside `isE2EMode()`, so a release build's initial
  state is unconditionally `false`, unchanged from before this story.
- **Camera permission**: no new mock was needed. `state/cameraPermission.ts`
  already swaps in the granted-permission stub (`e2eCameraPermissionsHook`,
  FTY-194) for every E2E build, because the simulator has no camera — this
  applies to both the barcode scanner and label capture automatically.
- **`capture.confirm_parsed`**: has no camera step at all. `useTodayData.ts`
  drives the existing label-upload proposal flow
  (`useLabelProposal.handleLabelUploaded`) with a synthetic already-uploaded
  event (`CAPTURE_CONFIRM_PARSED_EVENT`) the moment the preset is active, so the
  real `getLabelProposal` client call fires — answered by the fixture the
  preset registers (`CAPTURE_CONFIRM_PARSED_PROPOSAL`), the same session/mock-
  fetch path a real label upload takes, minus the camera and the live backend.
- **Settled marker**: each of the three sub-states is presented in a native
  `Modal` (the barcode/label capture screens) or a full-screen sheet
  (`ConfirmParsedValuesSheet`), which on iOS is a separate presented context
  from the screen behind it — the shared root-level marker
  (`app/_layout.tsx`) is not reliably reachable from inside it. This story
  mounts the existing, unmodified `VisualReviewSettleOverlay` a second time
  inside each of the three presented surfaces (`TodayScreen.tsx` for the two
  Modals, `ConfirmParsedValuesSheet.tsx` for the sheet) so the marker is exposed
  in whichever context is actually on top. It self-gates on `isE2EMode()` and
  renders nothing in every other build/state — confirmed by the Maestro run
  below, which waited on and found each marker.

## Verification

```sh
cd mobile
maestro test .maestro/visual-review-smoke.yaml
```

Full flow output (this run): every step through the pre-existing FTY-247/
FTY-264 presets, then `capture.barcode_granted`, `capture.label_guidance`, and
`capture.confirm_parsed` — each preset's settled marker, its content assertion,
and its screenshot all completed in the same run, on the same installed binary.
