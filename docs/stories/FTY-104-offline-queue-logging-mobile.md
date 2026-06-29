---
id: FTY-104
state: merged
primary_lane: mobile-core
touched_lanes: []
risk: high
tags:
  - offline
  - logging
  - outbox
  - sync
  - mobile
  - pending
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/log-events.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
review_focus:
  - dedup-on-reconnect-idempotency
  - offline-capture-never-blocked
  - pending-unparsed-render-offline-indicator
  - connection-banner-calm
  - on-device-queue-cleared-on-signout
autonomous: true
---

# FTY-104: Offline-Queue Logging (Mobile Client)

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-097 (design system / tokens this UI consumes)
- FTY-096 (offline idempotent submit + pending-unparsed contract this consumes —
  the idempotency-keyed create endpoint and the pending-unparsed state)
- FTY-099 (Log page / composer this extends)

## Outcome

When the device is offline or the Fatty server is unreachable, the user can still
capture a log entry by describing it in plain language on the Log page. The raw
text is enqueued in a local, persistent on-device outbox and rendered immediately
in the feed as a **pending entry** — uncounted, carrying an explicit offline
indicator — reusing the existing pending-unparsed pattern. A calm, gentle
connection-status banner communicates that capture is queued, never alarming. The
moment the server becomes reachable, the client automatically submits each queued
entry via FTY-096's idempotent create endpoint; the entry then parses and counts
through the normal pending → resolved flow. Because each queued entry carries a
client-generated idempotency key, a reconnect that retries an in-flight or
already-accepted submit never creates a duplicate. Capture is never blocked, and
no number is ever fabricated for a queued entry while it is offline.

## Scope

- **Local persistent outbox.** Add an on-device queue that durably stores raw log
  entries captured while offline/unreachable. Each queued item holds: the raw
  text, a stable client-generated idempotency key (UUID created at capture time,
  never regenerated on retry), the owning user id, a capture timestamp, and a
  local sync state (`queued` → `submitting` → `accepted`/`failed`). The store
  survives app restart (persistent storage, not in-memory only).
- **Optimistic pending-unparsed render with an offline indicator.** A queued entry
  appears in the Log feed immediately as a pending-unparsed entry (the same visual
  pattern as a normal in-flight entry), additionally marked with an explicit
  offline indicator so the user can see it is captured-but-not-yet-sent. It is
  visibly **uncounted** until the server resolves it. No fabricated kcal/macro
  value is shown.
- **Calm connection-status banner.** A gentle, non-blocking banner reflects
  connection/reachability state (e.g. offline / reconnecting / queued-N), using
  FTY-097 design tokens and the calm tone from the design doc. It informs; it
  never blocks capture and never reads as an error/alarm.
- **Sync-on-reconnect.** When reachability is regained, drain the outbox: submit
  each `queued` entry to FTY-096's idempotent create endpoint, passing the entry's
  client idempotency key. On success, mark `accepted` and let the entry follow the
  normal server-driven pending → resolved (or needs-clarification) flow so it
  parses and counts. Reconnect retries (including a retry after an ambiguous
  network failure where the server may already have accepted the submit) reuse the
  same idempotency key and therefore never duplicate. Submission is serial/bounded
  and resilient to transient failures (the entry stays queued and is retried, not
  dropped).
- **Reachability detection.** Detect online/offline/server-unreachable transitions
  (network state plus server reachability) to drive both the banner and sync
  trigger. A capture attempt that fails to reach the server falls back to enqueuing
  rather than surfacing a dead-end error.
- **Sign-out clears the queue.** On sign-out, the outbox for that user is cleared
  from on-device storage (see Security / Privacy).
- Keep it accessible: the offline indicator and banner carry accessible labels and
  never rely on color alone (per the design doc's cross-cutting accessibility
  stance).

## Non-Goals

- **The backend idempotent-submit endpoint and the pending-unparsed state machine
  (FTY-096).** This story consumes that contract; it does not define or modify it.
  No backend code, no schema migration.
- **Full offline-first edit/merge sync (v2).** Only raw-entry capture-and-submit is
  queued here. Editing, correcting, or deleting entries while offline, and any
  conflict/merge resolution, are out of scope.
- **Design tokens / design system (FTY-097).** This consumes tokens; it does not
  author them.
- **The Log composer itself (FTY-099).** This extends the existing Log page; it
  does not rebuild the composer, typeahead, or barcode/label affordances.
- **Barcode/label/camera offline capture.** v1 offline capture is natural-language
  text only; image/label capture offline is not in scope.
- **Any new contract or server endpoint.**

## Contracts

- **None new.** Consumes FTY-096's idempotent create endpoint (raw-text submit
  keyed by a client idempotency key) and the pending-unparsed status transitions
  layered on the log-events state machine (`docs/contracts/log-events.md`: the
  `pending` create and the pending → processing/completed/needs_clarification
  flow). The offline outbox is a purely client-side construct that feeds raw text
  into that existing create path; the server treats a drained queued entry exactly
  like any other create.

## Security / Privacy

- Queued raw entries are **sensitive personal data** (per `log-events.md` and
  `docs/security/data-retention.md`: `raw_text` is user-owned and never logged).
  They are stored locally on-device, scoped to the signed-in user only.
- **Cleared on sign-out.** The outbox is purged for that user when the session
  ends, so a queued entry never persists for or leaks to a different user of the
  device. (Aligns with the security baseline for on-device sensitive data.)
- Raw queued text is never written to logs or analytics, on-device or otherwise.
- No new server trust boundary is introduced: queued entries submit over the same
  authenticated, TLS-protected FTY-096 endpoint as a normal create; the
  idempotency key is the only added field and carries no secret.
- High risk is driven by correctness of the dedup-on-reconnect path (a bug here
  double-counts a user's intake) and by persisting sensitive raw text on-device.

## Acceptance Criteria

- While offline/unreachable, submitting on the Log page enqueues the raw entry and
  renders it immediately as a pending-unparsed entry with an explicit offline
  indicator; it is visibly uncounted and shows no fabricated number. Capture is
  never blocked.
- The queued entry persists across an app restart while still offline (durable
  outbox).
- A calm connection-status banner reflects offline/reconnecting/queued state using
  FTY-097 tokens; it never blocks capture and does not read as an alarm/error.
- On regained reachability, queued entries are automatically submitted to FTY-096's
  idempotent endpoint with their client idempotency key, then follow the normal
  pending → resolved flow and begin counting.
- **Dedup:** a reconnect retry of an entry the server already accepted (simulated
  ambiguous-failure / double-drain) reuses the same idempotency key and produces
  **no duplicate** entry; the outbox converges to one accepted item.
- A submit that fails transiently leaves the entry queued for retry rather than
  dropping or duplicating it.
- On sign-out, the outbox is cleared from on-device storage for that user.
- Offline indicator and banner carry accessible labels and do not rely on color
  alone.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile):
  - **Offline capture → local queue:** submitting while reachability is mocked
    offline enqueues a durable outbox entry with a stable idempotency key and
    renders a pending-unparsed entry with the offline indicator; totals are
    unchanged (uncounted).
  - **Persistence:** an entry enqueued offline survives a simulated app
    restart/store reload and is still present and `queued`.
  - **Reconnect sync:** when reachability flips online, the outbox drains by
    calling the mocked FTY-096 idempotent endpoint with the entry's idempotency
    key; the entry transitions to accepted and follows the pending → resolved flow.
  - **Dedup (no duplicate on retry):** a drain where the first submit's response is
    lost but the server already accepted it (retry with the same idempotency key)
    yields exactly one entry — assert no duplicate is created and the outbox
    converges to a single accepted item.
  - **Transient-failure resilience:** a failed submit keeps the entry queued and
    retries without duplicating.
  - **Connection banner + render:** banner reflects offline/reconnecting/queued
    states with calm copy; offline indicator + banner carry accessible labels and
    are not color-only.
  - **Sign-out clears queue:** after sign-out the user's outbox is empty in
    on-device storage.
- Run mobile typecheck, lint, and tests via `make verify` (delegates to the mobile
  package: `tsc --noEmit`, `eslint .`, `jest`).
- On an iOS simulator: with the device in airplane mode (or server stopped),
  capture an entry, confirm it queues with the offline indicator and a calm banner
  and stays uncounted; restore connectivity and confirm it auto-submits, parses,
  counts, and is not duplicated.

## Planning Notes

- This is the **mobile half** of offline logging; the backend idempotent-submit
  and pending-unparsed contract is FTY-096 (separate boundary). This slice is
  purely client-side and reuses the existing pending pattern rather than inventing
  new feed UI.
- The idempotency key is generated **once at capture time** and never regenerated
  on retry — that property is what makes reconnect retries safe and is the heart of
  the dedup acceptance criterion.
- Extends FTY-099's Log page and consumes FTY-097's tokens; it does not rebuild the
  composer or author tokens.

## Readiness Sanity Pass

- **Product decision gaps:** none — the design doc settles the behavior (§6
  offline: queue raw, pending+offline-indicator, uncounted, calm banner, resolve on
  reconnect, never block, never fabricate; §3 logging loop: the pending pattern and
  in-place resolve this reuses). No health/nutrition/behavioral question to ground
  in research — the cadence/evidence decisions live elsewhere; this is a
  client-sync slice.
- **Cross-lane impact / sizing:** single boundary — **mobile-core only**. No
  backend code, no schema migration, no new public contract (consumes FTY-096), and
  no new untrusted-input trust boundary (the outbox holds the signed-in user's own
  raw text on-device, not external/untrusted input). `review_focus` = 5 (at the
  ceiling) and `requires_context` = 6 (under 8) — only one field sits at a limit,
  so no split is warranted; the work is one author run in one serializing lane.
- **Security/privacy risk:** the main risk surface. Sensitive raw text persisted
  on-device, scoped to the signed-in user and cleared on sign-out; never logged;
  submitted over the same authenticated/TLS FTY-096 endpoint with only a
  non-secret idempotency key added. Captured in Security / Privacy with explicit
  acceptance + tests (sign-out clears queue).
- **Verification path:** mobile jest/tsc/eslint via `make verify` plus targeted
  tests for capture→queue, persistence, reconnect sync, dedup-on-retry, transient
  resilience, banner/indicator accessibility, and sign-out clear; simulator
  airplane-mode walkthrough.
- **Assumptions safe for autonomy:** yes, with a dependency note. **This depends on
  the FTY-096 backend contract** (idempotent create + pending-unparsed state) and
  on FTY-097/FTY-099 — these may not yet be merged; that is a dependency note, not a
  blocker. The slice builds against FTY-096's published idempotent-submit surface
  and reuses the existing pending pattern. Risk: **high** (dedup correctness +
  on-device sensitive persistence).
