# Contract: Log Attachments

## Purpose

Define the `log_attachments` table + DTO and the **discard-by-default** retention
of uploaded images, so a nutrition-label photo is persisted durably **only when
the user explicitly saves it**. This is the storage + retention prerequisite for
nutrition-label extraction (FTY-061); it ships no extraction logic of its own and
resolves the `log-events.md` "excluded: `log_attachments` (FTY-060/061)"
placeholder. FTY-374 adds a second, **transient** retention class for the images
of a unified text+image log submission: persisted at create so the async worker
can read them, purged at estimation-terminal unless explicitly saved.

It covers:

1. the **`log_attachments` table** and its migration (user + log-event ownership,
   the saved image bytes, and the metadata needed to retrieve and delete them);
2. the **retention rule** — discard by default; an explicit save writes exactly
   one row, the default flow persists no raw image;
3. the **upload constraints** — a maximum byte size and an image content-type
   allowlist, enforced fail-closed before any bytes are stored or handed onward;
4. the **transient retention class** (FTY-374) — a mixed text+image
   submission's images persisted for the estimation window only, marked
   `transient`, hard-deleted at estimation-terminal unless the submission chose
   `save=true`.

Out of scope: the provider vision contract (FTY-076) and the extraction pipeline /
schema / evidence write (FTY-061); the mobile capture/upload UI (FTY-064); and
`evidence_sources` (extracted facts, not the raw image).

## Owner

security-privacy / backend-core lane: `backend/app/models/attachments.py`,
`backend/app/schemas/attachments.py`, `backend/app/services/attachments.py`,
`backend/alembic/` (`0011`).

## Version

3 (FTY-374, contract only): adds **transient-then-purge retention** for the
images of a unified text+image log submission (`log-events.md` v9). A mixed
submission's images must outlive the create request so the ids-only async
worker can load them by event id (`estimation-jobs.md` v6), so they are
persisted at create time as `log_attachments` rows **marked transient** and
**hard-deleted (purged)** when the owning event's estimation reaches a terminal
status (`completed` / `failed`) — unless the submission chose `save=true`,
which writes them as ordinary saved rows instead. Discard-by-default is
preserved: with `save` absent/`false`, no image survives estimation. This pins
one additive schema decision — a `transient` marker column — whose migration is
**owned by the downstream FTY-375 implementation story**; no code or migration
lands here. See
[Transient retention — mixed submission images](#transient-retention--mixed-submission-images-fty-374).

2 (FTY-306, contract only): the **label exact-upgrade** upload
(`label-upload.md` → **Label exact-upgrade — FTY-306**) is a new consumer of this
table's retention rule, not a change to it — discard by default; an explicit
`save=true` writes exactly one user-owned row whose `log_event_id` is the
targeted food item's **owning log event** (no new event is created). No schema,
constraint, or retention change.

1 (FTY-077): introduces the `log_attachments` table, the discard-by-default
retention behaviour, and the fail-closed upload constraints. No HTTP endpoint or
extraction logic yet.

## Inputs

### Persistence

The `0011` migration creates **`log_attachments`** — a user-owned saved image.
Columns: `id` (UUID, PK); `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`,
indexed); `log_event_id` (UUID, FK → `log_events.id`, `ON DELETE CASCADE`,
indexed); `content_type` (string, not null — the validated image media type);
`byte_size` (integer, not null); `content_hash` (string, not null — SHA-256 hex of
the bytes); `data` (binary, not null — the saved image bytes); `created_at` /
`updated_at` (timestamptz, not null). Additive: no prior table is altered.

**FTY-374 pins one additive column** (migration owned by the downstream FTY-375
implementation story, reversible, no backfill semantics beyond the default):
`transient` (boolean, not null, default `false`). Existing rows — every
explicit-save row from the FTY-077/FTY-306 flows — keep `false` and are
unaffected. A `true` marks a mixed-submission image persisted only for the
estimation window (see
[Transient retention](#transient-retention--mixed-submission-images-fty-374)).

### Upload

An upload is `(data: bytes, content_type: str)` plus an explicit `save` flag. The
service `ingest_upload` validates the upload and then either discards it
(`save=False`, the default → no row) or persists exactly one row (`save=True`).

## Outputs

The attachment DTO (`LogAttachmentDTO`) is the **metadata** view returned for a
saved attachment; it omits the raw bytes (served separately):

```json
{
  "id": "UUID",
  "user_id": "UUID",
  "log_event_id": "UUID",
  "content_type": "image/jpeg | image/png | image/webp",
  "byte_size": 12345,
  "content_hash": "<sha256-hex>",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

## Transient retention — mixed submission images (FTY-374)

A unified text+image create (`log-events.md` v9) is the second writer of this
table, and the first with a **transient** retention window. The rules:

- **Write at create, tied to the event.** Each validated `image` part of the
  submission is persisted as one `log_attachments` row (same columns, same
  fail-closed `validate_upload` constraints) keyed to the created `pending`
  event and its owner, **in the same transaction as the event create** — so a
  rejected submission writes no row and a created event's images are readable
  the moment its job is claimable.
- **`save=false` (default) → `transient = true`, purged at terminal.** The rows
  exist **only while needed for extraction** (the sanctioned `threat-model.md`
  retention rule): when the owning event reaches a **terminal** estimation
  status — `completed` or `failed` — the worker **hard-deletes** the event's
  `transient` rows in the same transaction as the terminal status write
  (`estimation-jobs.md` v6). No image survives estimation by default.
- **Awaiting-answer window.** `needs_clarification` and `partially_resolved`
  are worker-terminal but not event-terminal: the answer-triggered re-estimate
  (`estimation-jobs.md` v2/v3) must be able to reload the images, so transient
  rows are **retained across the clarify loop** and purged when the event later
  reaches `completed`/`failed`. The window is user-paced (an unanswered
  question holds the rows), still bounded by the user/account/event-deletion
  cascades and by the per-run ceiling that guarantees each run terminates.
- **`save=true` → ordinary saved rows.** The submission-level `save` flag
  (default `false`, mirroring `label-upload.md`) promotes the images to normal
  saved rows: they are written with `transient = false` at create time and are
  never touched by the terminal purge — the same durable, user-owned retention
  as an FTY-077 explicit save. There is no per-image selection and no later
  promotion endpoint; the choice is made once, at submission.
- **Soft-void interaction (FTY-321).** Voiding the event does not cancel
  estimation and does not change retention class: a voided event's `transient`
  rows are still purged when the (void-agnostic) estimation reaches terminal,
  and its saved rows follow the existing retained-and-excluded rule — hard-
  removed only by the user/account-deletion cascades.
- **The purge is a hard delete.** Purging a transient row is application-level
  `DELETE` of the row (bytes included) — the one sanctioned exception to the
  append-only stance, because the row is by construction a working buffer, not
  audit history. Evidence extracted **from** an image survives independently in
  `evidence_sources` (facts + `content_hash` provenance, never the raw image),
  so provenance is preserved without retaining the bytes.
- **No new read surface.** This story adds no attachment retrieval/serving
  endpoint; transient rows are read only by the worker (scoped to the job's
  event and user).

## Validation

Upload constraints are enforced fail-closed, **before storage**, in order:

- **Size:** `byte_size` must be at most `MAX_ATTACHMENT_BYTES` (10 MiB); otherwise
  rejected.
- **Content-type:** the declared media type must be in the allowlist
  (`image/jpeg`, `image/png`, `image/webp`); otherwise rejected.
- **Signature:** the bytes' leading magic number must match the declared type, so a
  non-image (or mislabelled) payload is rejected even with an allowed content-type.

The persisted `content_type` is the canonical allowlist value, never the raw
client string.

## Authorization

- Object-level authorization: a caller may save attachments only under their own
  `user_id`. A cross-user save fails closed (`AttachmentForbidden`) and writes no
  row. Every saved row carries `user_id` at the persistence boundary.

## Privacy and Retention

- **Discard by default** (`docs/security/data-retention.md`): no raw image is
  persisted unless the user explicitly saves the attachment; the default flow
  writes no row. The FTY-374 mixed-submission path refines this without
  weakening it: its default flow writes rows **marked transient** that are
  hard-deleted at estimation-terminal (see
  [Transient retention](#transient-retention--mixed-submission-images-fty-374)),
  so no image survives estimation unless the user explicitly chose `save=true`.
- **User-owned + deletable:** the row carries the content-type, byte size, and
  content hash needed to retrieve and delete the saved image; `ON DELETE CASCADE`
  from both the user and the owning log event removes it whenever either owning
  **row** is actually deleted (user or account deletion). The user-initiated
  log-event delete (FTY-321, `log-events.md`) is a **soft void** that retains the
  event row, so it does not fire the cascade: a saved image on a voided event is
  retained-and-excluded like the event's other derived rows and is hard-removed
  only through the user/account-deletion cascades
  (`docs/security/data-retention.md`).
- The table never stores model output (that is evidence, `evidence_sources`); the
  stored bytes are untrusted input, validated as data and never logged.

## Errors

| Condition | Result |
| --- | --- |
| Upload exceeds the size limit | `AttachmentTooLarge` (no row) |
| Disallowed content-type, or bytes not matching the declared image type | `AttachmentInvalidContentType` (no row) |
| Cross-user save | `AttachmentForbidden` (no row) |

## Examples

```python
# Default flow: validated, then discarded — no row written.
ingest_upload(session, owner_id=uid, current_user=user,
              log_event_id=eid, data=img, content_type="image/png")
# → None

# Explicit save: exactly one user-owned row.
ingest_upload(session, owner_id=uid, current_user=user,
              log_event_id=eid, data=img, content_type="image/png", save=True)
# → LogAttachment(...)
```

## Migration / Compatibility

- The `0011` migration applies cleanly (`alembic upgrade head`) on top of the prior
  schema and is fully reversible (`alembic downgrade 0010`), verified by a
  migration apply/rollback test against a throwaway database.
- Additive: no prior table or column changes.
- FTY-061 (extraction) consumes the validated upload and writes extracted facts to
  `evidence_sources`; it reuses this table for the explicit-save case rather than
  redefining it.
- **FTY-306 (contract only; no migration).** The label **exact-upgrade** upload
  (`label-upload.md` → **Label exact-upgrade — FTY-306**) reuses `ingest_upload`
  and this retention rule unchanged for an image supplied against an **existing**
  food item: default discard after extraction, explicit `save=true` persisting
  exactly one user-owned row keyed to the item's owning log event, fail-closed
  size/type/signature validation, and no row on a failed extraction. It adds no
  new table, column, or retention surface. Backend implementation is
  **FTY-307–FTY-309**.
- **FTY-374 (contract only; no code, no migration in this story).** Adds the
  transient-then-purge retention class for unified text+image submissions
  (`log-events.md` v9) and pins the additive `transient` boolean column
  (not null, default `false`). The **migration is owned by FTY-375** (the
  backend ingestion/retention implementation story): additive and reversible,
  existing rows default to `false` with no behaviour change to the FTY-077 /
  FTY-306 explicit-save flows. The worker-side terminal purge and image load
  are `estimation-jobs.md` v6, implemented by FTY-375/FTY-376.
