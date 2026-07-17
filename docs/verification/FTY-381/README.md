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

## Live-backend reproduction (`live-backend-repro.txt`)

Against the shared local backend (`slacks` stack, API `:8000`), the same wire
call the fixed client makes (raw image bytes → `POST .../log-events/label`) now
**reaches the backend and creates the event (HTTP 201)** — the on-device break's
downstream is reachable again. See `sample-label.png` (a non-sensitive synthetic
Nutrition Facts panel) for the input.

## Blocker — real proposal cannot be produced on this box

Extraction of the uploaded label resolves to terminal **`failed`
(`provider_error`)**, because the environment's only authenticated LLM provider
is **`claude_code`**, which **hard-rejects image input**
(`backend/app/llm/providers/claude_code.py:272`:
`provider 'claude_code' does not support image input`) — even though the stack
sets `SLACKS_LLM_SUPPORTS_VISION=true`. There is no vision-capable provider
available here; a real label → real proposal needs `anthropic`/`openai` with a
paid API key.

That makes the story's **"a real label produces a real proposal"** running-app
evidence (and the confirm → counted-on-Today happy path that depends on it)
**unsatisfiable in this environment** within the story's Non-Goals (no
backend/pipeline changes; `requires_secret_access: false`). The on-device fix is
complete and unit/static-verified; the end-to-end runtime proof is blocked on a
vision provider. Tracked as a `story_defect` for the planner.
