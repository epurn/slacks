---
id: FTY-063
state: merged
primary_lane: mobile-core
touched_lanes:
  - security-privacy
review_focus:
  - camera-permission-flow
  - scaffold-reusability
  - ephemeral-frames
  - accessibility
  - verify-command
risk: medium
tags:
  - mobile
  - barcode
  - camera
  - scanning
  - logging
approved_dependencies:
  - expo-camera
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
  - docs/contracts/log-events.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
autonomous: true
---

# FTY-063: Mobile Barcode Scanner

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-060 (the backend Open Food Facts barcode resolution this UI relies on to
  turn a scanned barcode into a source-backed item)
- FTY-031 (the Today timeline this entry point lives on and where the resolved
  item appears)
- FTY-032 (the polling mechanism that drives the scanned event from `pending` to
  its terminal status without manual refresh)

## Outcome

From the Today screen the user can scan a product barcode with the device
camera. The app submits the scanned barcode through the existing log-event create
path so the backend FTY-060 pipeline resolves it against Open Food Facts, and the
resolved source-backed item appears on the timeline via the existing polling
(FTY-032) — no manual refresh, no new backend endpoint.

This story also **introduces the mobile camera scaffold**: it adds the
`expo-camera` (barcode-scanning) dependency, a camera permission request/denied
flow with a clear rationale, and a reusable capture entry point. The scaffold is
deliberately not barcode-specific in its permission/capture plumbing so FTY-064
(label-photo capture) can build directly on it.

## Scope

- Add the `expo-camera` dependency (barcode scanning) to the mobile package and
  wire it into the Expo config/permissions as required for iOS.
- Build a **reusable camera capture surface**: a permission gate (request on
  first use with a clear, nonjudgmental rationale; graceful denied/blocked state
  with a path to settings) and a camera capture screen/component that FTY-064 can
  reuse for label photos. Keep the permission + capture plumbing generic; the
  barcode read is the first consumer of it, not the only intended one.
- Add a "Scan barcode" entry point on the Today screen (alongside the existing
  natural-language composer) that opens the camera capture surface.
- On a successful barcode read, dismiss the camera and submit the barcode string
  through the **existing** `createLogEvent` path (POST log-events `raw_text`), so
  the backend FTY-060 pipeline detects and resolves the barcode. Show the new
  event immediately as `pending` (reusing the existing optimistic-create +
  reconcile flow), then let FTY-032 polling carry it to its terminal status.
- Surface success, in-progress, and failure states for the scan + submit using
  the existing nonjudgmental copy and error mapping; a submit failure rolls back
  cleanly like the text composer does.
- Keep the camera stream ephemeral: read the barcode value and discard frames;
  store no images or frames on device.
- Keep the surface iOS-first, compact, and accessible (accessible labels on the
  scan entry point, the camera controls, the permission rationale, and the
  cancel/close action).

## Non-Goals

- Nutrition-label image capture / OCR (FTY-064) — this story only stands up the
  shared camera scaffold that FTY-064 will reuse; it captures no images.
- Any new backend endpoint or contract: barcode detection and resolution are
  backend FTY-060's job. This slice only submits the barcode string through the
  existing log-event create path.
- Manual barcode entry fallback (a keyboard-typed barcode) — may be a later
  follow-up; explicitly out of scope here.
- Offline scanning / on-device barcode databases.
- Android-specific work or platform parity.

## Contracts

- No new contract. This slice consumes the **existing** FTY-030 log-events
  create (`POST /api/users/{user_id}/log-events`, `raw_text`) and get-by-id /
  list-today DTOs (`docs/contracts/log-events.md`). The scanned barcode is
  submitted as the event's `raw_text`; how the backend recognizes a barcode
  within that input and resolves it is FTY-060's responsibility, not this
  story's. No contract is touched or introduced.

## Security / Privacy

- The camera permission is requested **only when needed** (on first use of the
  scan entry point), with a clear rationale, and denial is handled gracefully
  with no dead end and no repeated nagging.
- The camera stream is treated as ephemeral: the app reads the barcode value and
  discards frames. No images, frames, or video are written to device storage or
  sent anywhere — no new stored field or attachment, so no retention change
  (`docs/security/data-retention.md`).
- A barcode is not sensitive personal data, but data minimization still applies:
  only the scanned barcode string is submitted, over the authenticated API, to
  the user's own log-events path. The barcode is submitted as `raw_text`, which
  the client never logs (consistent with the existing log-events client).
- No provider keys or external nutrition-source calls on the client; all
  resolution and any Open Food Facts egress stay server-side in FTY-060.
- Medium risk: mobile camera permission handling and a new device capability,
  but no contract, no migration, and no client-side handling of untrusted
  external responses (that trust boundary lives in FTY-060).

## Acceptance Criteria

- From the Today screen, the user can open a camera scan surface and scan a
  product barcode; a successful read submits that barcode through the existing
  log-event create path and the new event appears immediately as `pending`.
- The resolved, source-backed item appears on the timeline once FTY-060 finishes
  resolving it, driven by the existing FTY-032 polling (no manual refresh
  required).
- The camera permission is requested with a clear rationale only on first use;
  the denied/blocked path is handled gracefully (clear message, a way to retry or
  open settings, no crash, no dead end).
- A reusable camera permission + capture scaffold exists that FTY-064 can build
  on for label-photo capture (the permission gate and capture surface are not
  hard-coded to barcode-only use).
- No camera frames or images are persisted on device; only the barcode string is
  submitted.
- A scan-submit failure rolls back cleanly and surfaces a plain, nonjudgmental
  error, mirroring the text-composer behavior.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Run mobile typecheck, lint, and tests via `make verify` (which delegates to the
  mobile package's `typecheck` / `lint` / `test`), the same commands the sibling
  mobile stories use (FTY-013, FTY-031, FTY-032, FTY-053).
- Per `docs/standards/testing-standards.md` (mobile):
  - Component test for the scan entry point and capture surface: a successful
    barcode read submits the barcode via a mocked `createLogEvent` and the event
    appears as `pending`; a submit failure rolls back and surfaces the error.
  - Permission-flow tests against a mocked camera permission API: not-yet-asked →
    request, granted → camera shown, denied/blocked → graceful state with a
    retry/settings path.
  - A test asserting no frame/image is persisted (only the barcode string is
    submitted).
  - Accessibility checks (iOS-first, compact): accessible labels on the scan
    entry point, camera controls, permission rationale, and cancel/close.
- On an iOS simulator/device, scan a known barcode and confirm the event is
  created `pending` and, with FTY-060 resolving and FTY-032 polling, the resolved
  source-backed item appears on the timeline.

## Planning Notes

- Splits the Milestone 6 mobile barcode work from backend FTY-060. FTY-060 owns
  the Open Food Facts client, resolution, evidence, and barcode detection; this
  story is the mobile camera + capture consumer that feeds the existing
  log-events create path and renders the result through the existing
  timeline/polling.
- `expo-camera` is listed as the one approved new dependency. Adding any further
  mobile camera/scanning library beyond `expo-camera` (and its required
  config/permissions plumbing) needs a planning PR updating this story's metadata
  first, per the FTY-013 dependency convention.
- The scaffold should keep the permission gate and capture surface generic so
  FTY-064 reuses them for label photos; the barcode reader is the first consumer,
  not the only one. Resist baking barcode-only assumptions into the shared
  pieces.
- The exact `expo-camera` version and minor capture-surface layout choices may be
  finalized in the implementation PR as long as the reusable permission +
  capture scaffold, the existing-create-path submission, and the no-frame-storage
  boundary hold.
- Until the mobile sign-in flow lands, the Today screen renders a "sign in"
  state and there is no on-device session; tests inject a session, mirroring the
  existing Today/profile flows, so this story does not depend on sign-in landing.

## Readiness Sanity Pass

- Product decision gaps: none — resolved with the product owner. Scan submits the
  barcode through the existing log-events create path (no new endpoint); the
  camera scaffold is reusable for FTY-064; permission is requested only when
  needed with graceful denial; manual entry, label-photo capture, and offline
  scanning are explicit non-goals.
- Cross-lane impact: mobile-core plus a security-privacy touch for the camera
  permission and ephemeral frames; consumes the existing FTY-030 log-events DTOs
  and the FTY-031/FTY-032 timeline+polling; introduces no contract and no
  migration. Adds one approved dependency (`expo-camera`).
- Security/privacy risk: medium — new camera capability and permission handling,
  mitigated by least-privilege permission timing, graceful denial, ephemeral
  frames (no image storage, no retention change), barcode-only submission over
  the authenticated API, and no provider keys/external egress on the client.
- Verification path: mobile typecheck/lint/tests via `make verify` (component +
  permission-flow + no-frame-persistence + accessibility tests) plus a device/
  simulator end-to-end scan → resolved-item check.
- Assumptions safe for autonomy: yes. Dependency note: FTY-060 (backend barcode
  resolution) may not be merged yet — that is a dependency note, not a blocker;
  the mobile slice builds against the existing log-events create/get DTOs and the
  established timeline/polling, and the `expo-camera` version is the only soft
  detail, with a safe default.
