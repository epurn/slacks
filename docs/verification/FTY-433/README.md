# FTY-433 — Label capture drops to two taps (running-app evidence)

Captured on a leased iOS 26.5 simulator (iPhone 17 Pro, 1206×2622) running this
branch's JS through the E2E dev client (`EXPO_PUBLIC_SLACKS_E2E=true`), driven by
the two Maestro flows in [`flows/`](./flows). Every flow step below passed; the
screenshots are the settled frames those runs captured, in **light and dark**.

## What the flows drive

`capture.label_auto_upload` (a new capture-lane visual-review preset,
`mobile/components/today/captureVisualReview.ts`) opens the real label-capture
surface and supplies only the two things a camera-less simulator cannot:

- the **shutter frame** — `takePictureAsync` yields nothing without a camera, so
  the seam returns a tiny synthetic "nutrition label card" PNG (so the held-frame
  backdrop is actually visible in the shots);
- the **upload** — the real client streams image bytes through native networking
  (`File.upload`, FTY-381), which the E2E fetch mock cannot answer, so the seam
  stands in and holds ~25s before resolving with the same synthetic label event
  `capture.confirm_parsed` already pins.

Everything else is shipped code: the real shutter handler, the real auto-upload
call site in `TodayScreen`, the real abort-on-retake path, and the real
`handleLabelUploaded` → label-proposal read → `ConfirmParsedValuesSheet` →
confirm POST → daily-summary refresh.

## The two-tap flow (`flows/fty433-two-tap-label.yaml`)

| Screenshot | What it proves |
| --- | --- |
| `fty433-1-capture-light.png` / `-dark.png` | The capture surface: shutter, framing guide, flash, and the sticky **save-photo control resting off**. No Upload button, no preview, no "Save this photo?" question — asserted, not just visible. |
| `fty433-2-save-on-light.png` / `-dark.png` | One tap on the save control makes the sticky opt-in unmistakable: amber-filled glyph, amber hairline, and a persistent "Saving photos" caption — and the button **stays put** while the caption mounts below it. (The flow then turns it back off, so the logging run below is the steady-state, discard-by-default one.) |
| `fty433-3-uploading-light.png` / `-dark.png` | **Tap one.** The shutter uploaded by itself: the captured frame is held as the uploading backdrop with the spinner, "Uploading…", and **Retake** as an optional undo. Still no Upload button. |
| `fty433-4-confirm-light.png` / `-dark.png` | The parse-confirm gate is unchanged: the parse lands as an uncounted proposal ("Not yet counted", `Label scan` provenance) behind "Looks right" / "Adjust". |
| `fty433-5-counted-light.png` / `-dark.png` | **Tap two.** "Looks right, add it" commits it: the hero jumps to `190 / 2,000 kcal · 10%` with the macro chips and the counted timeline row. Two taps before the confirm gate, end to end. |

## The retake flow (`flows/fty433-retake-mid-upload.yaml`)

| Screenshot | What it proves |
| --- | --- |
| `fty433-6-retake-back-to-camera-light.png` / `-dark.png` | Retake tapped while the upload is in flight returns straight to the live viewfinder — the uploading state is gone. |
| `fty433-7-superseded-dropped-light.png` / `-dark.png` | Captured *after* the superseded upload has resolved (the flow deliberately waits past the seam's hold): no confirm sheet, no parse — the discarded shot's result is dropped, and the user is still framing the next one. |

## Review round 2: the save control no longer jumps

Round 1 shipped `saveToggleContainer` as an absolutely positioned box with only
`left` set and `alignItems: "center"`. Such a box shrink-wraps its widest child,
so mounting the "Saving photos" caption widened it and re-centred the 44pt button
inside the wider box — the control moved sideways under the finger that had just
tapped it. Left-anchoring the container's children makes the fixed `left` the only
thing that determines the button's x, in both states.

Measured on the committed shots (the save glyph's bounding-box centre in
`fty433-1-capture-*` → `fty433-2-save-on-*`, at 1206px width):

| Head | Shift when switched on |
| --- | --- |
| `a3f5535` (round 1) | **+77px ≈ 25pt** — the defect the reviewer measured |
| this head | **+0.5px** — the on-state's 1px accent hairline, i.e. the button does not move |

The other round-2 fix — the shutter's in-flight guard against a double-tap — is a
non-event on screen, so it is proven at the component-test layer instead
(`LabelCaptureScreen.test.tsx`: one capture and one upload from a double tap, the
library pick sharing the guard, and the guard surviving a superseded upload's
settle). The seam's `takePhoto` resolves instantly, so these flows never linger in
the busy state the guard dims.

## Notes for the reader

- The viewfinder is black in every capture-surface shot: the simulator has no
  camera, so `CameraView` renders an empty feed. The overlay chrome is the
  subject of those shots.
- Light and dark look identical on the camera surface by design — it is chrome
  over a live camera feed, not a themed surface (see the style comments in
  `LabelCaptureScreen.tsx`). The theme difference shows in the confirm-sheet and
  counted-day shots.
- These flows live here rather than in `mobile/.maestro/` on purpose:
  `verify-e2e.sh` runs that whole directory as a suite on the scheduled Android
  job, and these are one-off, iOS-oriented evidence runs. The step-shape
  assertions that *should* run in CI were added to the committed label-capture
  flows instead (`visual-review-smoke.yaml`'s `capture.label_guidance` section and
  `exact-evidence-visual-review-seam.yaml`'s `exact_label` section).
- Re-running them:

  ```
  eval "$($SLACKS_SIM_SLOT acquire --label FTY-433)"
  # install a current Slacks.app on $SLACKS_SIM_UDID, point it at your Metro:
  #   xcrun simctl spawn "$SLACKS_SIM_UDID" defaults write com.slacks \
  #     RCT_jsLocation "localhost:$SLACKS_METRO_PORT"
  #   (cd mobile && EXPO_PUBLIC_SLACKS_E2E=true npx expo start --dev-client \
  #     --port "$SLACKS_METRO_PORT")
  maestro --udid "$SLACKS_SIM_UDID" test -e THEME=light flows/fty433-two-tap-label.yaml
  maestro --udid "$SLACKS_SIM_UDID" test -e THEME=dark  flows/fty433-two-tap-label.yaml
  maestro --udid "$SLACKS_SIM_UDID" test -e THEME=light flows/fty433-retake-mid-upload.yaml
  maestro --udid "$SLACKS_SIM_UDID" test -e THEME=dark  flows/fty433-retake-mid-upload.yaml
  "$SLACKS_SIM_SLOT" release --label FTY-433
  ```
