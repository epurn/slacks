# FTY-381 — Nutrition-label capture verification

## Root cause (on-device break)

The capture chain died **on-device before any network call** in
`uploadLabelImage` (`mobile/api/labelCapture.ts`). It read the captured file with
`fetch(imageUri).blob()` over a local `file://` URI — a fragile React Native /
Expo Go pattern that throws or hangs on `.blob()` **before** the upload POST ever
fires, which matches the zero `log_attachments` rows and zero label-upload
requests in the dogfood window. The same primitive was duplicated in
`uploadLabelExactEvidenceProposal` (`mobile/api/exactEvidence.ts`).

## Fix

- Read + upload now go through `expo-file-system`'s native `File` API (the
  repo-standard on-device file API, already used by the on-device stores):
  `File.upload(url, { uploadType: BINARY_CONTENT, ... })` streams the raw bytes
  from disk through native networking, bypassing the JS blob machinery. The
  client size/type guard runs first off `File.size` / `File.type`; an unreadable
  file is rejected content-free before any POST. Shared helper `uploadImageBinary`
  is reused by both the normal and exact-upgrade label paths.
- Photo-library fallback (`expo-image-picker`, approved dependency): a "Choose
  from Library" affordance in the camera phase — the honest degrade when the live
  camera can't produce a frame (e.g. the camera-less iOS simulator) and a genuine
  path for a label photo already in the library. Feeds the same `onSubmit` +
  `save` semantics; the picked asset is ephemeral and never persisted/logged.

## Running-app evidence

Captured on a leased iOS 26.5 simulator (`Slacks-Slot-0`) running this branch's
JS in the E2E debug build (`EXPO_PUBLIC_SLACKS_E2E=true`), driven through the
FTY-247 visual-review deep-link harness (`slacks://__visual-review?preset=…`).
Every step below is a real rendered frame of this branch's code; each is
committed in light and dark where the surface is themed.

| Step | Light | Dark |
| --- | --- | --- |
| Capture surface + "Choose from Library" honest-degrade affordance (`capture.label_guidance`) | `fty381-capture-surface-light.png` | `fty381-capture-surface-dark.png` |
| Confirm-parsed-values sheet — real parsed values, "Not yet counted" (`capture.confirm_parsed`) | `fty381-confirm-parsed-light.png` | `fty381-confirm-parsed-dark.png` |
| After "Looks right" → the item **counts on Today** (hero 190 / 2,000 kcal, row counted) | `fty381-counted-on-today-light.png` | `fty381-counted-on-today-dark.png` |
| Honest terminal-failure outcome on Today — Retry / Edit as text, never a dead end (`today.failed`) | `fty381-failed-light.png` | `fty381-failed-dark.png` |

The capture surface is the live-camera overlay chrome (fixed white over the feed,
not a themed surface), so its light/dark frames are intentionally identical; the
camera feed is black because the iOS simulator has no hardware camera — exactly
the case the "Choose from Library" fallback exists for.

## Live-backend reproduction (`live-backend-repro.txt`)

Against the shared local backend (`slacks` stack, API `:8000`), the same wire
call the fixed client makes (raw image bytes → `POST .../log-events/label`) now
**reaches the backend and creates the event (HTTP 201)** — the on-device break's
downstream is reachable again. See `sample-label.png` (a non-sensitive synthetic
Nutrition Facts panel) for the input.

## Extraction outcome — provider gap is an operator concern, not a story blocker

Extraction of the uploaded label resolves to terminal **`failed`
(`provider_error`)** on the dogfood box, because its only authenticated LLM
provider is the default **`claude_code`**, which hard-rejects image input
(`backend/app/llm/providers/claude_code.py`). Which provider the dogfood box runs
is an operator/infra concern **outside this story's Non-Goals** — the story
explicitly states it is *not* blocked on it, and forbids stubbing a fake proposal
into the running backend.

The app handles that outcome **honestly and reachably**: the terminal failure is
surfaced on Today as an actionable, non-dead-end row (Retry / Edit as text — see
`fty381-failed-*.png`), never a silent no-op or hang.

The **confirm → counted-on-Today acknowledgement** — which a real proposal would
drive when the backend is vision-capable — is proven here through the sanctioned
**injectable proposal seam** (`capture.confirm_parsed`): a synthetic uncounted
proposal is fed through the *real* `getLabelProposal` read + confirm POST path
(no live upload, no camera, no fabricated proposal in any running backend), the
confirm sheet's "Looks right" commits it, and Today's hero jumps from `0` to
`190 / 2,000 kcal` with the row now counted (`fty381-counted-on-today-*.png`).
This is the exact acknowledgement wiring `useLabelProposal` already implements;
the seam only supplies the proposal the vision-less provider cannot.
