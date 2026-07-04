# FTY-216 manual verification — Type-scale migration, Capture

Story-required visual verification for routing the capture-owned numeric
`fontSize` literals (`BarcodeScannerScreen`, `CameraCapture`,
`LabelCaptureScreen`) through `typeScale`, run 2026-07-04 on an iOS 26.5
simulator (`Fatty-Slot-1`).

## Fixture use (sim has no camera)

The simulator has no camera hardware, so `useCameraPermissions` never leaves
`undetermined` under a real backend connection and the scanner's granted
chrome never mounts. Per the story's own verification note, this run used the
**E2E fixture harness** (`EXPO_PUBLIC_FATTY_E2E=true`, `mobile/e2e/launchMode.ts`)
so `CameraCapture` defaults to `e2eCameraPermissionsHook`, an already-granted
stub — the hermetic equivalent of the OS grant. This mounts the real
`BarcodeScannerScreen` / `LabelCaptureScreen` granted-chrome overlays (guidance
text, framing hint, torch, close button) with no live backend or network I/O.

Two overlay states were reachable this way and are the evidence below:

- **Barcode scanner**, camera phase: reticle + "Point at a barcode" guidance
  (`styles.guidance`) + "Type it instead" fallback (`styles.manualLabel`).
- **Label capture**, camera phase: framing guide + "Fit the nutrition label
  inside the frame" hint (`framingHintText`).

Not reachable on this simulator (documented, not silently dropped): the label
preview/uploading phases (`saveLabel`, `secondaryButtonLabel`,
`primaryButtonLabel`, `uploadingText`, `errorText`) require a real photo from
`CameraView.takePictureAsync`, which the simulator's camera stub does not
produce — tapping the shutter left the screen in the camera phase with no
preview or error transition. The `CameraCapture` permission-gate text
(`rationaleText`, `primaryButtonLabel`) only renders in the *ungranted*
permission state, which the E2E stub bypasses by design (always-granted). The
`closeButtonLabel` (✕, `typeScale.iconGlyph`) IS visible in both captured
screenshots (top-right) since `CloseButton` renders in every permission state.
These untested sites are float-identical pixel values before/after (e.g. 16 →
`typeScale.callout` is still 16) verified by the `check-font-size-literal.js`
guard's site-based value match, not by an eyeball on this Mac.

## Method

- Started this worktree's Metro in E2E fixture mode
  (`EXPO_PUBLIC_FATTY_E2E=true npx expo start --dev-client --port 8091`),
  pointed the leased simulator's dev-client at it (`simctl launch` +
  `simctl openurl` deep link).
- Captured the **after** frames with the story's changes in place (Maestro:
  tap "Capture label" / "Scan barcode" from Today, wait for the guidance
  text, screenshot).
- `git stash`'d the three changed component files (reverting to the pre-story
  `origin/main` code — raw `fontSize: N` literals), relaunched the app so
  Metro served the reverted JS, and recaptured the **before** frames with the
  identical flow.
- Restored the stashed changes before continuing.

## Screenshot index

| Screenshot | State | Evidence |
|---|---|---|
| `barcode-scanner-before.png` | Pre-story `BarcodeScannerScreen` (raw `fontSize: 16`) | Reticle + "Point at a barcode" + "Type it instead" |
| `barcode-scanner-after.png` | Post-story (`typeScale.callout`) | Same copy, same layout, same size |
| `label-capture-before.png` | Pre-story `LabelCaptureScreen` (raw `fontSize: 15`) | Framing guide + "Fit the nutrition label inside the frame" |
| `label-capture-after.png` | Post-story (`typeScale.subhead`) | Same copy, same layout, same size |

Each before/after pair is **byte-identical** (`cmp` reports no difference):
routing `fontSize: 16` → `typeScale.callout` (16) and `fontSize: 15` →
`typeScale.subhead` (15) does not change any rendered pixel — the guard's
site-based value match (baseline `sizes` unchanged) is exactly this claim
generalized to every drained site.
