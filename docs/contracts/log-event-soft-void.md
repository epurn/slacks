# Contract: Log-Event Soft-Void (Delete)

## Purpose

Define the **soft-void (delete) operation** for a log event —
`DELETE /api/users/{user_id}/log-events/{event_id}` — extracted from
`log-events.md`, which owns the event lifecycle (create, reads, the status
state machine, validation, authorization, privacy, errors, and examples). A
void removes a mislogged entry from the user's day by setting a terminal
`voided_at` marker: the event and every row hanging off it are **retained**
(nothing hard-deleted, no cascade) but excluded from every read model and the
daily totals. This page specifies that exclusion in full — the read-model
filtering, the fail-closed single-item surfaces, any-status voiding, the
database-enforced write-once idempotency, void-does-not-cancel-estimation, and
owner-scoped no-oracle `404`s.

The `voided_at` persistence column, the `DELETE` endpoint listing in the
resource's HTTP surface, the event DTO, and the state-machine note that void
adds no `LogEventStatus` value stay in [log-events.md](log-events.md); this page
owns the void **semantics** those entries point to.

## Owner

backend-core / contracts lane (`backend/app/models/log_events.py`,
`backend/app/services/log_events.py`, `backend/app/routers/log_events.py`,
`backend/alembic/`; the fail-closed single-item prechecks also touch
`backend/app/services/clarification.py` and the corrections / label-proposal
services).

## Version

1 (FTY-384, contract only): **structural relocation** of the soft-void (delete)
semantics out of `log-events.md` (where they landed as v8, FTY-321) into this
dedicated page. **No normative change** — the marker-not-deletion, read-model
exclusion, fail-closed single-item-surface enumeration, any-status voiding,
database-enforced first-write-wins idempotency, void-does-not-cancel-estimation,
and owner-scoped no-oracle `404` rules are preserved verbatim from FTY-321.
`log-events.md` keeps the `voided_at` column, the `DELETE` endpoint listing, the
`204` response, and the state-machine note, and links here for the semantics.

## Soft-void (delete) (FTY-321)

`DELETE /api/users/{user_id}/log-events/{event_id}` lets a user remove a
mistaken or unwanted logged entry. It is a **soft void**, not a hard delete:

- **Marker, not deletion.** The event's `voided_at` is set once (a terminal
  status; there is no un-void). The event row, its derived food/exercise items,
  its corrections, its evidence rows, and any saved label-image attachment
  (`log-attachments.md`) are all **retained** — nothing is hard-deleted, and no
  `ON DELETE CASCADE` fires (a void deletes no row) — so the append-only
  audit/provenance stance holds (`corrections.md`,
  `docs/security/data-retention.md`).
- **Full read-model exclusion.** A voided event disappears from the day: it is
  omitted from list-today, the day-listing (`by-date`) read, and the single
  get-by-id (which returns `404`); its derived items are omitted from the
  day-listing item rows; and its kcal/macros/burn no longer count toward the
  daily summary `intake` / `exercise`, nor does it count toward
  `uncounted_entries` (`daily-summary.md`). The clarification read and answer
  fail closed (`404`) for a voided event.
- **Single-item surfaces fail closed (`404`).** The endpoints that return or
  mutate a specific stored row **directly** — and so never pass through the
  read-time exclusion join above — each refuse a voided target with `404`,
  making the exclusion exhaustive across the surface:
  - the **keyed create-replay** (`POST .../log-events` with an
    `idempotency_key` whose stored event is voided) — see
    [Idempotent create](log-events.md#idempotent-create-201-vs-200); the key
    stays consumed and no replacement row is created;
  - the **clarification read and answer** (`clarification.md`), as above;
  - the **correction edit**
    (`PATCH .../derived-items/{item_type}/{item_id}`, `corrections.md`) on an
    item whose parent event is voided;
  - the **re-match candidate-list and re-resolve**
    (`POST .../derived-items/food/{item_id}/source-candidates` and
    `.../re-resolve`, `corrections.md`) on an item whose parent event is voided;
  - the **label-proposal read and confirm**
    (`GET`/`POST .../log-events/{event_id}/label-proposal[/confirm]`,
    `label-upload.md`) on a voided event — the refused confirm mutates nothing,
    so the retained `proposed` row stays uncounted.

  These are backend-core route/service boundary prechecks (each loads the
  target's parent event and rejects when `voided_at` is set); the estimator
  re-match capability and the worker stay void-agnostic. The `404` matches the
  unknown-item/unknown-event shape, so there is no void oracle.
- **Any status.** Voiding works whatever the event's estimation status
  (`pending`, `processing`, `completed`, `failed`, `needs_clarification`) —
  `voided_at` is orthogonal to `status`, and the event keeps its pre-void status
  for audit.
- **Idempotent.** Repeating the delete on an already-voided event returns `204`
  identically and does **not** move `voided_at`; the marker is write-once,
  **first-write-wins** — enforced database-side (the void is a conditional
  `UPDATE … WHERE voided_at IS NULL`), so even concurrent deletes cannot
  re-stamp an already-set marker.
- **Void does not cancel estimation.** A void is a read-model concern, not a
  pipeline stop: it does **not** cancel an in-flight or queued estimation job,
  and the estimator is void-agnostic (`estimation-jobs.md` is unchanged). A
  late estimation that completes after the void is expected and is not an
  error: any derived rows it writes onto the voided event are
  **retained-and-excluded** — persisted like any other derived rows, but never
  surfaced or counted, because every derived-item and daily-summary read joins
  each row to its parent event and drops rows whose parent has `voided_at`
  set. Exclusion happens at read time, so it holds regardless of when the rows
  were written.
- **Ownership fails closed.** The event is loaded scoped to the authenticated
  owner. A cross-user or unknown `event_id` is indistinguishable as `404` (no
  existence oracle) and mutates nothing — the same convention as get-by-id.

The delete adds no un-void/undo endpoint, no bulk delete, and no retention/purge
job (those are out of scope). Because a voided event is excluded from get-by-id,
a client that voids an entry treats a subsequent `404` on that id as expected.
