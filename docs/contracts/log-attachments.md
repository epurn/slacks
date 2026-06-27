# Contract: Log Attachments

## Purpose

Define the `log_attachments` table + DTO and the **discard-by-default** retention
of uploaded images, so a nutrition-label photo is persisted **only when the user
explicitly saves it**. This is the storage + retention prerequisite for
nutrition-label extraction (FTY-061); it ships no extraction logic of its own and
resolves the `log-events.md` "excluded: `log_attachments` (FTY-060/061)"
placeholder.

It covers:

1. the **`log_attachments` table** and its migration (user + log-event ownership,
   the saved image bytes, and the metadata needed to retrieve and delete them);
2. the **retention rule** — discard by default; an explicit save writes exactly
   one row, the default flow persists no raw image;
3. the **upload constraints** — a maximum byte size and an image content-type
   allowlist, enforced fail-closed before any bytes are stored or handed onward.

Out of scope: the provider vision contract (FTY-076) and the extraction pipeline /
schema / evidence write (FTY-061); the mobile capture/upload UI (FTY-064); and
`evidence_sources` (extracted facts, not the raw image).

## Owner

security-privacy / backend-core lane: `backend/app/models/attachments.py`,
`backend/app/schemas/attachments.py`, `backend/app/services/attachments.py`,
`backend/alembic/` (`0011`).

## Version

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
  writes no row.
- **User-owned + deletable:** the row carries the content-type, byte size, and
  content hash needed to retrieve and delete the saved image; `ON DELETE CASCADE`
  from both the user and the owning log event removes it on log-event, user, or
  account deletion.
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
