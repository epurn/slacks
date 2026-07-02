# Contract: Nutrition Label Upload

## Purpose

Define the **HTTP upload boundary** (FTY-064) that supplies a captured nutrition
-label image to the FTY-061 extraction pipeline. The mobile capture screen posts a
single label photo; the backend validates it as data, runs the label-extraction
pipeline **in-request**, and returns the resulting log event. This is the boundary
`label-extraction.md` defers ("The HTTP upload path that supplies this (mobile
capture) is FTY-064") — that contract owns the backend pipeline; this one owns the
mobile↔backend HTTP boundary it consumes.

This is deliberately **synchronous, not enqueued**: the raw image is discarded by
default (FTY-077), so it must never be persisted or published to the broker just to
reach an async worker. The estimation job payload carries only ids
(`estimation-jobs.md`), so the image could not travel that path anyway. The image
therefore only ever lives in the request that uploads it and is resolved there,
through the same idempotent `process_estimation` core the worker uses.

## Owner

mobile-core + backend-core lane:

- `mobile/api/labelCapture.ts` (`uploadLabelImage`) — the client.
- `backend/app/routers/log_events.py` (`upload_label_event`) — the route.
- `backend/app/estimator/label_upload.py` (`LabelProcessor` seam,
  `synchronous_label_processor`) — the in-request processing seam.

No new table or migration. Reuses `services/attachments.validate_upload` (FTY-077),
the FTY-061 `label_pipeline`, and the FTY-030 `LogEventDTO`.

## Version

1 (FTY-064).

## Inputs

`POST /api/users/{user_id}/log-events/label?save={bool}`

| Part | Source | Notes |
| --- | --- | --- |
| image bytes | request body | The raw image; **not** multipart, **not** base64. |
| image type | `Content-Type` header | Declared type, validated against the bytes. |
| `save` | query string (`true`/`false`) | FTY-077 retention choice; defaults to `false`. |
| auth | `Authorization: Bearer <token>` | Object-level ownership on `{user_id}`. |

There is no consumed-quantity field: an upload defaults to **one serving**
(`amount = 1`), matching the FTY-061 `LabelInput` default and the common "I logged
this product" case.

## Outputs

A `LogEventDTO` (FTY-030) at status `201 Created`. Because extraction is
synchronous, the returned event is already at its **post-extraction** status:
`completed` (legible panel), `needs_clarification` (unreadable / unresolvable), or
`failed` (not a label / invalid image, **or a transient provider error**). The
in-request seam runs a single attempt with no scheduler to honor a retry, so a
transient (retryable) vision-provider failure resolves to terminal `failed`
rather than a dead-end `processing`; the client retries by uploading again. The
event's `raw_text` is a fixed,
content-free marker (`"Nutrition label photo"`) — a label carries no
natural-language text; the food facts come from the extracted panel and are
persisted by the FTY-061 pipeline (a `derived_food_items` row + a `user_label`
`evidence_sources` row).

**The legible-panel food item lands `proposed`, not counted (FTY-196).** A legible
parse persists its `derived_food_items` row in the **`proposed`** state — an
**uncounted proposal** — instead of a counted `resolved` item, because "OCR is
fallible — Fatty never silently trusts a fallible parse"
(`docs/design-philosophy.md`). The event still reaches terminal `completed`
(extraction finished), but the food item is **excluded from `daily-summary` intake
by construction** (the finalized-state filter requires item `status == 'resolved'`
— it is **not** relaxed) until the user confirms it via the confirmation gate
below. This is a **pre-v1 breaking change** to the post-extraction result (no
consumers in production; the clean redesign is preferred). See
[Confirmation gate](#confirmation-gate-fty-196).

## Validation

The image is **untrusted data**, validated fail-closed *before* any event is
created or any model is called, reusing `services/attachments.validate_upload`:

1. size within `MAX_ATTACHMENT_BYTES` (10 MiB) → else `413`;
2. declared content-type in the image allowlist (`image/jpeg`, `image/png`,
   `image/webp`) → else `415`;
3. the bytes' magic-number signature matches the declared type → else `415`.

The client mirrors the size/type checks before the request as a first-line guard,
but the backend is the authoritative trust boundary. A failed validation creates
**no** event, food row, evidence, or attachment.

## Authorization

The `{user_id}` path is explicit and checked on every call: a caller may upload
only under their own id. A cross-user (or unknown) `{user_id}` is rendered `404`
(no existence oracle), mirroring the FTY-030 create path. A missing/invalid bearer
token is `401`.

## Privacy and Retention

- **Discard by default.** The raw image is retained as a `log_attachment` only on
  `save=true`, and never on a failed extraction (FTY-077). The default discards it
  after extraction.
- **Never enqueued / never logged.** The image is processed in-request and never
  published to the broker; no image bytes, URIs, or extracted content are logged on
  either side.
- **Content-free errors.** Client and server error messages carry only the HTTP
  status and a fixed action description — never image bytes, file paths, URIs, or
  extracted label text.

## Errors

| Condition | Status | Client message family |
| --- | --- | --- |
| Image exceeds the size limit | `413` | "That photo is too large to upload." |
| Body is not an allowed image type / bytes mismatch the type | `415` | generic upload-failed |
| Missing / invalid bearer token | `401` | "Your session has expired…" |
| `{user_id}` not owned by the caller (or unknown) | `404` | generic upload-failed |
| Any other non-2xx | as returned | "We couldn't upload the label (status …)." |

The client additionally fails closed **before** the network call on an oversize or
wrong-type image (`LabelUploadTooLargeError` / `LabelUploadInvalidTypeError`).

## Examples

```
POST /api/users/<uid>/log-events/label?save=false
Authorization: Bearer <token>
Content-Type: image/png
<raw PNG bytes>

→ 201 Created
  { "id": "...", "user_id": "<uid>", "raw_text": "Nutrition label photo",
    "status": "completed", "created_at": "...", "updated_at": "..." }
  (a **proposed** (uncounted) derived_food_items row + a user_label evidence_sources
   row persisted; no log_attachments row, because save=false. The proposal does not
   count toward daily-summary intake until confirmed — see the confirmation gate.)
```

## Confirmation gate (FTY-196)

A photographed label is **capture-then-confirm**: the parse lands as an uncounted
`proposed` item (above), and two owner-scoped routes let the mobile confirm sheet
(FTY-197) show the parsed values and commit them. Both fail closed — a cross-user or
nonexistent `event_id` is `404` with no existence oracle, mirroring `log-events.md` /
`daily-summary.md` — and neither logs the nutrition values.

**Read the proposed values.**

```
GET /api/users/{user_id}/log-events/{event_id}/label-proposal
Authorization: Bearer <token>

→ 200 { "proposal": { …DerivedFoodItemDTO… } }   # the parsed name/serving/calories/
                                                 # macros + user_label `source`
→ 200 { "proposal": null }                       # event has no uncounted proposal
```

The `proposal` is the shared item read shape (`daily-summary.md` → per-item
provenance): the parsed values enriched with the `user_label` `source` descriptor
(`label: "Label scan"`) and `is_edited`. It is `null` when the event has no
uncounted proposal — never had one (a `needs_clarification` / `failed` disposition,
or a non-label event) or already confirmed. There is **no status oracle**: those
cases are indistinguishable.

**Confirm the proposal (commits it → counted).**

```
POST /api/users/{user_id}/log-events/{event_id}/label-proposal/confirm
Authorization: Bearer <token>
{ "calories"?: number, "protein_g"?: number, "carbs_g"?: number,
  "fat_g"?: number, "amount"?: number }        # body optional

→ 200 { …DerivedFoodItemDTO (status: "resolved")… }
```

Confirm flips the food item `proposed → resolved` in **one transaction**, so the
daily-summary finalized-state filter then counts it. The body is optional:

- **Omitted / empty** → the parsed values commit as-is; the item keeps its
  `user_label` provenance and reads `is_edited: false` (an accepted parse is not a
  user edit).
- **`calories` / a macro** → a **value override**: commits the user's number,
  appends a `user_edit` correction, and the item reads `is_edited: true`
  (`corrections.md`). Provenance stays `user_label`.
- **`amount`** → the adjusted consumed serving count: a **provenance-preserving**
  servings rescale (`amount_adjust`, `corrections.md`) — calories/macros rescale,
  the source is untouched, and the item stays un-edited.

A **double confirm** is idempotent: a second call finds the item already `resolved`
and returns it unchanged, so a proposal is never counted twice. An out-of-range /
invalid adjusted value returns `422` with a machine-readable error shape
(`{"error": <code>, "field": <field>}`) that never echoes the value; a
negative/non-finite value is rejected at the request boundary (`422`).

Backend coverage: `backend/tests/test_label_upload_endpoint.py` (happy path,
discard-vs-save retention, `413`/`415` data-boundary rejection, `404`/`401`
ownership, and "never enqueues"). Client coverage:
`mobile/api/labelCapture.test.ts` (guard, raw-body shape, save query flag,
content-free error mapping).

## Migration / Compatibility

- **No new table or migration.** Reuses `log_attachments` (FTY-077),
  `derived_food_items` / `evidence_sources` (FTY-044), and the FTY-061 pipeline.
- **Additive route.** A new `POST .../log-events/label` alongside the FTY-030
  `POST .../log-events` (text) and `GET` routes; the text path is unchanged.
- The wire is raw-body (not multipart), so the backend needs no multipart parser
  dependency.
- **FTY-196 (no migration).** The confirmation gate adds the `proposed`
  `derived_food_items.status` value and two additive routes
  (`GET`/`POST .../log-events/{event_id}/label-proposal[/confirm]`). `status` is a
  plain `VARCHAR` (not a database `ENUM`), so the new value is an application-only
  change that round-trips on SQLite and Postgres with **no** schema migration. The
  legible-panel result changing from a counted `resolved` item to an uncounted
  `proposed` one is a **pre-v1 breaking change** (no production consumers). The
  daily-summary finalized-state filter is **unchanged** — the exclusion is by
  construction.
