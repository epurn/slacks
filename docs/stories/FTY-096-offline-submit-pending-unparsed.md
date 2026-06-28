---
id: FTY-096
state: ready_with_notes
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
review_focus:
  - idempotent-dedup
  - concurrent-submit-race
  - object-level-authz
  - migration-rollback
  - input-validation
risk: high
tags:
  - log-events
  - offline
  - idempotency
  - api
  - contracts
approved_dependencies: []
requires_context:
  - docs/contracts/log-events.md
  - docs/contracts/estimation-jobs.md
  - docs/design/ux-design.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-096: Offline Idempotent Submit + Pending-Unparsed State (backend/contract)

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- None to schedule. This **extends two merged contracts**: FTY-030 (the
  `log_events` create API + status state machine, `docs/contracts/log-events.md`)
  and FTY-040 (the estimation-job worker + the `pending → processing → completed`
  drive, `docs/contracts/estimation-jobs.md`). Both are landed; this story changes
  only the create boundary and its contract doc.

## Outcome

A mobile client that captures a log entry while offline can submit it on
reconnect with a **client-generated idempotency key**, such that a retry after a
flaky reconnect (the 201 was lost in flight, the app relaunched mid-send, the
outbox flushed twice) resolves to the **same single log event** rather than a
duplicate. The submitted entry enters the existing `pending` status — the
pending-unparsed, uncounted state the design relies on — and follows the
unchanged `pending → processing → completed` chain the estimator already drives.

This is the **backend/contract half** of offline logging. It gives the mobile
offline outbox (FTY-104) a safe-to-retry submit contract: the same captured entry
can be sent any number of times and the server converges on one event. The design
basis is `docs/design/ux-design.md` §6 ("Offline / server-unreachable logging:
queue raw, resolve on reconnect … reusing the pending pattern") and §3 (the
logging loop's pending/uncounted entries that auto-parse and count once resolved).

## Scope

- **Add an optional `idempotency_key` to the log-event create request.**
  `POST /api/users/{user_id}/log-events` accepts `{ "raw_text": str,
  "idempotency_key"?: str }`. The key is **opaque** (the server never parses or
  interprets it — a client UUID/ULID is the expected shape), trimmed, non-empty
  after trimming when present, and bounds-checked (length cap, e.g. ≤ 200 chars).
  Unknown body keys stay rejected (`422`); `raw_text` validation is unchanged.
- **Persist the key and dedup on it, per user.** Add a nullable `idempotency_key`
  column to `log_events` via an **additive migration**, with a composite
  **unique index on `(user_id, idempotency_key)`** so the key namespace is
  per-user and the database is the dedup authority. (Postgres treats NULL keys as
  distinct, so the unchanged online/no-key path — and the label-upload path — keep
  inserting freely.)
- **First-write-wins idempotent semantics on create:**
  - **No key supplied** → behaviour is exactly as today: create a `pending` event
    and enqueue its estimation job. Back-compatible.
  - **Key supplied, no existing event for `(user_id, key)`** → create the
    `pending` event, store the key, enqueue the job, return `201`.
  - **Key supplied, an event already exists for `(user_id, key)`** → return that
    **existing** event's current DTO (whatever status it has since advanced to),
    **create no new row**, **enqueue no second job**, return `200`. The client
    distinguishes a replay (`200`) from a fresh create (`201`).
- **Make the create path race-safe.** Two concurrent submits with the same key
  (double outbox flush, parallel retries) must converge to one event: the unique
  index is the guard — the insert that loses the race catches the integrity
  violation, re-reads the now-committed sibling, and returns it as the `200`
  replay. No `500`, no duplicate, no orphaned second enqueue. The
  `create_event` service returns enough signal (e.g. `(event, created: bool)`) for
  the router to enqueue **only** on a fresh create.
- **Document the offline-submit / pending-unparsed semantics in
  `docs/contracts/log-events.md`** (version bump): the optional `idempotency_key`,
  the `201`-create / `200`-replay first-write-wins behaviour, the per-user key
  namespace, and an explicit "offline submit" note — an offline-queued entry is a
  **client-only** state with **no server row** until it is submitted; on submit it
  becomes a server `pending` event (the pending-unparsed, uncounted state) and runs
  the unchanged `pending → processing → completed` transitions. Cross-reference the
  estimator drive in `docs/contracts/estimation-jobs.md`.

## Non-Goals

- **No new `LogEventStatus`.** The existing `pending` status *is* the
  pending-unparsed state (a raw event exists, not yet processed, so it is uncounted
  in totals until derived items land). Introducing a server status for "queued
  offline" is explicitly rejected — that state lives only in the client outbox and
  has no server representation until submit. This keeps the FTY-030 state-machine
  map (a named contract the estimator reuses) untouched, so the slice stays in one
  boundary and does not churn the estimator lane.
- The mobile offline outbox: local persistence of captured entries, the
  reconnect-flush, the connection banner, and the offline indicator on a pending
  entry (FTY-104, mobile-core). This story produces no client code.
- Any full offline-first sync/merge: editing, correcting, or deleting entries
  while offline and reconciling conflicting edits is v2. Only **raw-entry submit
  dedup** is in scope.
- Changing the worker's own redelivery idempotency (the `estimation_jobs` unique
  `log_event_id` from FTY-040). That guards a duplicated *task*; this guards a
  duplicated *submit*. They are independent and both stay in force.
- Validating that a reused key carries an identical body (see Planning Notes:
  first-write-wins, body mismatch is not an error).

## Contracts

- **`docs/contracts/log-events.md` (version bump):** the create request gains the
  optional `idempotency_key`; the create response documents `201` (created) vs
  `200` (idempotent replay); the per-user key namespace and the offline-submit /
  pending-unparsed mapping are documented. This is the one public contract change
  in the slice.
- **Persistence:** `log_events.idempotency_key` (nullable) + the
  `(user_id, idempotency_key)` unique index, via an additive, reversible migration
  (next in sequence after `0013_weight_entries`).
- **Consumed by FTY-104** (mobile outbox): the safe-to-retry submit semantics and
  the `201`/`200` distinction.
- **Estimator interaction (unchanged, referenced):** a fresh keyed create enqueues
  exactly as the no-key path does; the dedup/replay path enqueues nothing, so the
  estimator side sees no new job. `docs/contracts/estimation-jobs.md` is not
  modified.

## Security / Privacy

- **Object-level authorization is unchanged and still primary.** Every create runs
  through the existing fail-closed `_authorize` (`{user_id}` must equal the
  authenticated user; cross-user create stays `404`, no existence oracle). The
  idempotency-key lookup is **scoped to the authenticated user**, so a key can
  only ever address that user's own events — one user's key cannot collide with or
  surface another user's event. Proven by a per-user namespacing test (the same key
  string from two users yields two distinct events) and by the unchanged cross-user
  negative tests.
- **The key is opaque, bounded, low-trust text** — it is validated as data (length
  cap, non-empty-when-present, type) at the same boundary that already guards
  `raw_text`. It is **not** a new untrusted-input trust boundary (no image, fetched
  page, OCR, or upload): it is an opaque token the server never interprets, so this
  introduces no second big rock. It is treated as potentially sensitive (a client
  may derive it from content) — never logged, never returned to a non-owner; it is
  not exposed in the DTO unless a clear consumer need exists (default: not echoed).
- **Retention** follows the owning event: the column lives on `log_events` and is
  removed by the existing `ON DELETE CASCADE` on account deletion. No new retention
  surface; note the new stored field per `docs/security/data-retention.md`.
- **Rated high:** an idempotency/dedup contract with a concurrency-correctness
  requirement (the unique-index race) on the user's primary write path. A wrong
  dedup either drops a real entry or admits a duplicate into the day's totals —
  both corrupt the count the whole app is built to keep honest.

## Acceptance Criteria

- **Back-compat:** a create with **no** `idempotency_key` behaves exactly as
  before — creates a `pending` event and enqueues one job — proven against the
  existing FTY-030/040 tests.
- **Idempotent replay:** a second create with the same `(user_id, idempotency_key)`
  returns the **same event id**, creates **no new `log_events` row**, and enqueues
  **zero** additional jobs. The first create returns `201`; the replay returns
  `200`.
- **Replay reflects current status:** when the original event has already advanced
  (e.g. to `processing` or `completed`) before the retry arrives, the replay
  returns that current status so the client reconciles rather than resetting it.
- **Race safety:** two concurrent same-key creates converge to exactly one event;
  the losing insert catches the unique-constraint violation, re-reads, and returns
  the existing event as a `200` — never a `500`, never a duplicate, never a second
  enqueue.
- **Per-user namespace + authz:** the same key string submitted by two different
  users yields two distinct events; a key lookup never crosses users; cross-user
  create still fails closed `404`. Proven by negative tests.
- **Validation:** an over-length, empty/whitespace, or wrong-type
  `idempotency_key`, or an unknown body key, is rejected `422`; `raw_text`
  validation is unchanged.
- **First-write-wins on body mismatch:** a re-submit with the same key but
  different `raw_text` returns the **originally stored** event (no new row, no
  re-enqueue); the divergent body is ignored (documented behaviour, not an error).
- **State-machine untouched:** no new `LogEventStatus`; `LEGAL_TRANSITIONS` is
  unchanged; the submitted entry enters `pending` and runs
  `pending → processing → completed` exactly as today.
- **Migration:** applies (`alembic upgrade head`) and rolls back cleanly on top of
  `0013`; the column is nullable and the `(user_id, idempotency_key)` unique index
  exists; existing rows (null key) are unaffected.
- **Contract doc** reflects the optional key, `201`/`200`, per-user namespace, and
  the offline-submit / pending-unparsed mapping.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- Idempotent-resubmit dedup test: first POST → `201`; identical re-POST with the
  same key → `200`, same id, exactly one `log_events` row, and — asserted via the
  swappable enqueuer seam (`get_enqueuer`) — exactly one enqueue total.
- Concurrent / duplicate-key race test: simulate two same-key creates so the unique
  index fires; assert exactly one event, the loser returns the existing event
  (`200`, not `500`), and only one job is enqueued.
- Per-user namespacing + negative authz tests: same key for two users → two
  events; cross-user create still `404`.
- Validation tests: over-length / empty / wrong-type key and unknown body key →
  `422`; null-key path unchanged.
- Pending-unparsed transition test: a keyed (and a no-key) create lands at
  `pending` and drives `pending → processing → completed` through the existing
  service/worker path, confirming the offline entry maps onto the unchanged chain.
- Migration apply/rollback test against a throwaway database (apply `0014`, roll
  back to `0013`), asserting the column + unique index.

## Planning Notes

- **Why no new status:** the design's "pending entry, uncounted, offline
  indicator" splits cleanly — *uncounted* is the existing server `pending` (no
  derived items yet); the *offline indicator* is a client-only outbox concern
  (FTY-104). The server never needs to know an entry was once offline, so adding a
  status would leak a client concern into the shared state machine and pull in the
  estimator lane. Keeping `pending` as pending-unparsed is what holds this to one
  boundary.
- **First-write-wins (vs `409` on body mismatch):** standard idempotency-key
  semantics (the key identifies the request; the stored result is authoritative).
  The offline retry sends a byte-identical body by construction, so mismatch only
  arises from a client key-reuse bug; returning the original event is simpler and
  safe, and the client owns key generation. A `409`-on-mismatch variant is
  explicitly out of scope to keep the slice small.
- **Two idempotency layers, kept distinct:** this story's key dedups a *submit* at
  the create boundary; FTY-040's `estimation_jobs.idempotency_key` (derived from
  the event id) dedups a *task redelivery* at the worker. The dedup path here
  avoids the second enqueue entirely, so the two never have to interact — but even
  a stray re-enqueue would be absorbed by the worker's unique `log_event_id`.
- **Enqueue placement:** today the router enqueues unconditionally after
  `create_event`. The service must signal created-vs-replayed so the router
  enqueues only on a fresh create; do not move enqueue inside the dedup branch.
- Next migration is `0014` (after `0013_weight_entries`). No table is added — a
  nullable column + unique index on the existing `log_events` table.

## Readiness Sanity Pass

- **Product decision gaps:** none load-bearing. The two judgment calls —
  reuse `pending` rather than add a status, and first-write-wins rather than
  `409`-on-mismatch — are decided and justified above. `ready_with_notes` only
  because whether the `idempotency_key` is echoed in the DTO is left to the
  implementer (default: not echoed; FTY-104 does not require it), a reversible
  detail that does not block the contract. No health/nutrition/behavioural question
  is involved, so no evidence research is warranted.
- **Cross-lane impact:** primary backend-core; contracts (the log-event create
  doc) and security-privacy ride along (non-serializing). **Single boundary, one
  big rock:** one public contract change (create API gains the key). The migration
  adds a *column + index*, not a table, so it is not a second big rock; the opaque
  bounded key is not a new untrusted-input trust boundary. The deliberate no-new-
  status decision keeps the estimator state-machine contract untouched, so the
  story does not spill into the estimator lane.
- **Size:** `review_focus` = 5 (at the ceiling, not over): idempotent-dedup,
  concurrent-submit-race, object-level-authz, migration-rollback, input-validation.
  `requires_context` = 6 (under 8). At the review-focus limit but not breaching two
  limits, so it stays one story.
- **Security/privacy risk:** high — a dedup/idempotency contract on the primary
  write path with a concurrency-correctness requirement (unique-index race);
  object-level authz unchanged and the key lookup is owner-scoped; key is bounded,
  opaque, never logged, cascade-deleted.
- **Verification path:** `make verify` + dedup (201/200, one row, one enqueue) +
  race + per-user namespacing + negative authz + validation + pending-unparsed
  transition + migration apply/rollback.
- **Assumptions safe for autonomy:** yes — an additive column/index plus a bounded
  change to one existing endpoint and its contract doc, with the harder calls
  (status reuse, first-write-wins, enqueue-only-on-create, owner-scoped lookup)
  pinned here. No external provider, no LLM, no UI.
