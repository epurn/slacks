---
id: FTY-064
state: merged
primary_lane: mobile-core
touched_lanes:
  - security-privacy
review_focus:
  - image-upload-handling
  - permission-rationale
  - save-attachment-opt-in
  - client-side-size-type-guard
risk: medium
tags:
  - mobile
  - label-capture
  - camera
  - image-upload
  - attachments
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
  - docs/contracts/log-events.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
autonomous: true
---

# FTY-064: Mobile Nutrition-Label Capture + Upload

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-061 (backend label extraction: the upload contract, vision-extended
  provider extraction, and `log_attachments` persistence this story consumes)
- FTY-063 (camera scaffold: the `expo-camera` dependency, permission flow, and
  capture entry point this story reuses — not re-added here)
- FTY-031 (Today timeline the resolved item appears on)
- FTY-032 (polling that drives the entry from pending to its terminal status)

## Outcome

From the Today screen the user can capture a nutrition-label photo with the
device camera and upload it. The backend (FTY-061) extracts structured facts via
the vision-extended provider, and the resolved, source-backed item appears on the
timeline via the existing polling mechanism (FTY-032). By default the captured
image is discarded after extraction per data-retention; the user may explicitly
opt in to save the photo as a `log_attachment`.

## Scope

- From the Today screen, let the user enter the label-capture flow using the
  FTY-063 camera scaffold (its `expo-camera` dependency, permission flow, and
  capture entry point). Do not re-add the camera dependency or re-implement the
  permission flow.
- After capture, upload the image to FTY-061's backend label path using exactly
  FTY-061's defined upload contract (its multipart/attachment shape). Do not
  invent a new upload contract.
- Surface an explicit "save this photo" affordance. Default is do-not-save: the
  backend discards the image after extraction unless the user opts in, in which
  case it is persisted as a `log_attachment` (FTY-061). The opt-in is sent as
  whatever flag/parameter FTY-061's upload contract defines.
- Once uploaded, the created event appears as `pending` on the timeline and is
  driven to its terminal status by the existing FTY-032 polling; the resolved
  source-backed item renders through the existing timeline rendering. No new
  polling or rendering mechanism is introduced.
- Enforce a client-side size and content-type guard before upload, rejecting
  oversize or non-image payloads with a clear, nonjudgmental message before any
  network call.
- Handle camera-permission-denied gracefully with a clear rationale and a path
  back, reusing the FTY-063 permission flow rather than duplicating it.
- Handle upload loading, success, and failure states; failures must not echo
  image bytes or sensitive content into errors or logs.

## Non-Goals

- Barcode scanning (FTY-063 owns the camera scaffold and barcode work).
- Manual entry of label facts (a typed/deferred fallback is out of scope here).
- In-app image editing or cropping beyond what the capture flow already
  provides.
- Any backend extraction, upload-endpoint, provider, or `log_attachments` logic
  — that is FTY-061. This slice is the mobile consumer only.
- New polling or timeline-rendering mechanisms — reuse FTY-032 and FTY-031.

## Contracts

- Introduces no new contract. Consumes FTY-061's upload/attachment contract
  (its multipart/attachment shape and save-attachment flag) and the existing
  FTY-030 log-event DTOs and event status enum (`docs/contracts/log-events.md`)
  that FTY-031/FTY-032 already render and poll.

## Security / Privacy

- The captured label image is sensitive user content. It is uploaded over TLS to
  our own backend only — never to a provider or third party from the client, and
  no LLM/vision/nutrition provider keys live on the client (security-baseline).
- The image is not persisted on-device beyond what the capture flow needs to
  hand it to the upload; it is not retained server-side unless the user opts in
  (data-retention: nutrition label images are retained only while needed for
  extraction unless explicitly saved). Default is do-not-save.
- Camera permission is reused from FTY-063 with a clear rationale shown before or
  at first capture; permission-denied is handled gracefully.
- A client-side size/type guard rejects oversize or wrong-type payloads before
  upload as a first-line defense; the authoritative trust boundary (validation,
  sanitization, untrusted-content handling) lives in FTY-061's backend.
- Errors and logs carry only HTTP status and the attempted action — never image
  bytes, file paths, or extracted content.
- Medium risk: mobile UI uploading untrusted user image content; the server-side
  trust boundary is owned by FTY-061.

## Acceptance Criteria

- From the Today screen, capturing a nutrition-label photo uploads it to
  FTY-061's backend label path using FTY-061's upload contract, and the
  backend-resolved, source-backed item appears on the timeline (via FTY-032
  polling) without manual refresh.
- The "save this photo" opt-in, when selected, persists the image as a
  `log_attachment` (FTY-061); the default (not selected) results in the image
  being discarded after extraction.
- Camera-permission-denied is handled gracefully with a clear rationale and a
  path back, reusing the FTY-063 permission flow.
- An oversize or wrong-content-type image is rejected client-side before upload
  with a clear, nonjudgmental message.
- Upload loading/success/failure states render sensibly; failures expose no
  image content or sensitive data.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile):
  - Component/integration tests for the capture-to-upload flow against a mocked
    FTY-061 upload endpoint: successful upload creates a pending event that
    resolves on poll; the save-photo opt-in sends the attachment-save flag and
    the default omits it.
  - Tests for the client-side size/type guard rejecting oversize and non-image
    payloads before any network call.
  - Test for permission-denied handling (graceful rationale + path back) over
    the reused FTY-063 permission flow.
  - Tests asserting errors/logs never contain image bytes or sensitive content.
- Run the mobile package's typecheck, lint, and test (the same commands FTY-013
  and FTY-053 use: `npm run typecheck`, `npm run lint`, `npm run test` in
  `mobile/`, via `make verify` where wired).
- On an iOS simulator, capture a label photo, confirm the resolved item appears
  on the timeline, and confirm the save-photo opt-in persists an attachment
  while the default discards it.

## Planning Notes

- This story builds on the FTY-063 camera scaffold specifically to avoid a
  `package.json` / iOS-permission merge conflict: the `expo-camera` dependency
  and `NSCameraUsageDescription`-style permission plumbing are added once by
  FTY-063 and reused here.
- The exact upload field names, multipart shape, and save-attachment flag are
  owned by FTY-061; this slice consumes whatever FTY-061 publishes and must not
  invent its own.

## Readiness Sanity Pass

- Product decision gaps: none — capture-from-Today, upload via FTY-061's
  contract, resolved item via FTY-032 polling, and a do-not-save-by-default
  photo opt-in are all resolved; non-goals exclude barcode, manual label entry,
  and in-app editing.
- Cross-lane impact: mobile-core plus security-privacy (uploading untrusted user
  image content, retention-aware save opt-in); consumes FTY-061's contract and
  existing log-event DTOs, defines no new contract.
- Security/privacy risk: medium — TLS-only upload to our backend, no client
  provider keys, image not persisted on-device beyond capture, server-side
  retention only on explicit opt-in (data-retention), client-side size/type
  guard, and the authoritative trust boundary in FTY-061.
- Verification path: mobile component/integration tests against a mocked FTY-061
  endpoint (upload, save opt-in vs. default, guard rejection, permission-denied,
  no-content-in-logs), plus typecheck/lint/test and a simulator capture check.
- Assumptions safe for autonomy: yes. Dependency note: FTY-061 (upload contract
  + attachments) and FTY-063 (camera scaffold) are upstream — this slice builds
  against their published surfaces; FTY-031/FTY-032 are the existing
  timeline/polling it reuses.
