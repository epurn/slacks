# Contract: Unified Text+Image Log Submission

## Purpose

Define how **one log submission carries free text plus 0..N images** (FTY-374)
— e.g. `"2 of these bars"` plus a photo of the bar's nutrition label — and how
the estimator uses both surfaces: text for identity/count/context, an image for
label facts. This page owns the multipart create wire shape, its fail-closed
per-image validation and limits, the async routing rationale, and the
cross-contract map; the retention, worker, and estimator halves live in the
contracts they belong to:

- [log-events.md](log-events.md) owns the create endpoint, the event DTO, the
  status state machine, and idempotent create — all **unchanged** by this page
  except that create now also accepts the multipart shape below.
- [log-attachments.md](log-attachments.md) v3 owns the **transient-then-purge**
  image retention and the `save` promotion.
- [estimation-jobs.md](estimation-jobs.md) v6 owns the ids-only payload
  reaffirmation, worker-side image load, pipeline selection, vision gating, and
  the terminal purge.
- [parse-candidates.md](parse-candidates.md) v12 /
  [interpretation-session.md](interpretation-session.md) v2 own images as parse
  evidence surfaces and per-surface provenance.
- `docs/security/data-retention.md` and `docs/security/threat-model.md` record
  the reconciled retention/egress posture.

This story ships **no product code and no migration**. The backend ingestion +
retention implementation is **FTY-375** (backend-core, including the additive
`log_attachments.transient` migration); the estimator consumption is
**FTY-376**; the mobile composer attach affordance is a **required follow-up
mobile story** (not yet scheduled).

## Owner

contracts lane; implementation owners on landing:
`backend/app/routers/log_events.py`, `backend/app/services/log_events.py`,
`backend/app/services/attachments.py` (FTY-375);
`backend/app/estimator/` (FTY-376).

## Version

1 (FTY-374, contract only).

## Inputs

`POST /api/users/{user_id}/log-events` is **content-negotiated, additive, not
breaking the JSON path**:

- `application/json` — the existing `{ raw_text, idempotency_key? }` body,
  **byte-for-byte unchanged**, so the FTY-104 offline outbox and every
  text-only client keep working with no change.
- `multipart/form-data` — the mixed submission:

| Part / parameter | Count | Notes |
| --- | --- | --- |
| `payload` part (`application/json`) | exactly 1 | `{ "raw_text"?: str, "idempotency_key"?: str }`. Field rules match the JSON body exactly: when present, `raw_text` is trimmed, non-empty after trimming, ≤ 2000 chars; `idempotency_key` is opaque, trimmed, non-empty, ≤ 200 chars. Unknown keys are rejected (`422`). A missing, duplicated, or non-JSON `payload` part is `422`. |
| `image` parts (binary) | 0..`MAX_SUBMISSION_IMAGES` | Each part carries raw image bytes with its declared image content type. Repeated part name `image`; any other unknown part name is rejected (`422`). |
| `save` query flag (`true`/`false`) | optional, default `false` | The submission-level retention choice, mirroring `label-upload.md`: `false` (default) discards every image once estimation no longer needs it; `true` saves the images as normal `log_attachments` rows. It applies to all of the submission's images (no per-image selection). With zero image parts — including the JSON path — it has no effect. |

Choosing content negotiation over a multipart-only cutover is deliberate: the
pre-v1 clean-break rule would allow breaking, but the additive shape *is* the
cleaner design here — it keeps the outbox's JSON replay path intact and
preserves offline logging without a forced client rewrite.

**At least one surface.** A submission must carry a non-empty `raw_text` and/or
at least one `image` part; an empty submission (no text, no images) is `422`
and creates nothing. A multipart submission with text and zero images is valid
and equivalent to the JSON create. When an image-bearing submission omits
`raw_text`, the stored `raw_text` is the fixed, content-free marker
`"Photo log"` (the same marker convention as the label path's
`"Nutrition label photo"`), since the column is not null and the timeline
renders it.

## Outputs

Exactly what the JSON create returns (`log-events.md`): `201` with the event
DTO at `status: "pending"` on a fresh create, `200` with the existing event on
a keyed replay, `404` on a replay of a voided stored event. Both content types
create **one** `pending` event and enqueue **exactly one** estimation job.

## Async routing — the estimate-first / never-reject choice

A mixed submission runs the **normal async estimation pipeline** (create →
enqueue → worker), **not** the synchronous label path. The synchronous
`POST .../log-events/label` boundary resolves a **single** transient provider
error to terminal `failed` (`label-upload.md` — its in-request seam has no
scheduler to honor a retry), which directly violates the design-philosophy
*estimate first / never reject* clause for a typed food entry. The async
worker, by contrast, retries a transient failure with backoff while the event
honestly reports `processing` (still working), routes ambiguity to a
clarifying question rather than failure, and degrades rather than fails on a
configuration limit (the non-vision gating, `estimation-jobs.md` v6) — so a
good-faith entry never becomes terminal `failed` on a *first* transient error.
That guarantee is bounded, not absolute: the attempt-level retry policy and
the per-run provider-call / wall-clock ceiling apply to image-bearing events
**unchanged**, and retry exhaustion, a ceiling breach, or a deterministic step
failure still drives the event to `failed` exactly as the `estimation-jobs.md`
v6 state and error tables specify — FTY-375/FTY-376 implement those tables
as written, with no image-specific exception. **That
retries-before-terminal difference — not an unconditional never-`failed`
promise — is why the mixed path is asynchronous.** The standalone synchronous
label endpoint and its FTY-196 confirmation gate are unchanged and remain for
the "photograph a label, nothing typed" flow.

To let the ids-only worker read the images, they are **transiently persisted**
at create time as `log_attachments` rows tied to the created `pending` event,
marked transient, and **hard-deleted (purged)** when the event reaches a
terminal estimation status (`completed` / `failed`) unless the submission chose
`save=true` — the full retention contract, including the awaiting-answer
window and the `save` promotion, is `log-attachments.md` v3. Discard-by-default
is preserved: with `save` absent/`false`, no image survives estimation. This
matches the already-sanctioned `threat-model.md` retention rule ("retained only
while needed for extraction"), now reached via a transient DB row rather than
an in-request buffer.

An event that has images runs the **text-parse / interpretation pipeline
augmented with the images as vision evidence surfaces**, *not* the label-only
`label_pipeline`; each derived number records the surface that backed it
(`estimation-jobs.md` v6, `parse-candidates.md` v12).

## Validation

Per-image validation and limits are **fail-closed before any persistence or
model call**. Each `image` part is validated exactly like an FTY-077 upload,
reusing `services/attachments.validate_upload` (`log-attachments.md`):

1. a submission carries at most `MAX_SUBMISSION_IMAGES` images — pinned **4**,
   a documented tunable, generous for a few label/food photos; over-count is
   `422`;
2. each image is at most `MAX_ATTACHMENT_BYTES` (10 MiB) — else `413`;
3. each declared content type is in the allowlist (`image/jpeg`, `image/png`,
   `image/webp`) and the bytes' magic-number signature matches the declared
   type — else `415`.

Any invalid or over-count image rejects the **whole** submission
(`413`/`415`/`422`): no event, no attachment row, no enqueue, and no model
call. Validation order is deterministic: content-type negotiation, then
`payload` part validation, then the idempotent-replay check, then the
at-least-one-surface check, then image count, then per-image
size/type/signature — so nothing is persisted until every check has passed.
A malformed `save` value is `422`.

## Idempotency — replay re-ingests nothing

First-write-wins on `(user_id, idempotency_key)` holds for both content types
(`log-events.md`, Idempotent create). A keyed replay returns the existing
event's DTO (`200`), creates **no duplicate attachment rows**, and enqueues
**no second job**. The existing "body mismatch is not an error" rule extends to
image parts: a replay's image parts are **ignored entirely** (not validated,
not persisted), exactly as a divergent `raw_text` is ignored. A replay whose
stored event is voided still fails closed with `404` and ingests nothing.

## Authorization

Unchanged from the create endpoint (`log-events.md`): bearer auth, and a caller
may create only under their own `{user_id}` — a mismatch fails closed as `404`
and neither an event nor an attachment row is written. Every attachment row
carries `user_id` at the persistence boundary (`log-attachments.md`).

## Privacy and Retention

- Images are **untrusted input sent to the LLM/vision provider only**
  (`llm-provider.md` — data, never instructions). They are never sent to
  search, fetch, OCR-web, or any other egress; never logged; never placed on
  the queue; never copied into `estimation_runs` `trace`/`error`. Errors are
  content-free. Prompt-injection printed on an image is data, never
  instructions — vision output is trusted only after schema validation, exactly
  as for text.
- Transient persistence is bounded to the estimation window and purged at
  terminal unless explicitly saved; rows cascade on user/event deletion
  (`log-attachments.md` v3, `docs/security/data-retention.md`).
- **No new event status, no counting change.** Mixed events use the existing
  `pending → processing → completed | needs_clarification | partially_resolved
  | failed` machine unchanged; `daily-summary.md` counting is unchanged.
  Soft-void (FTY-321) applies unchanged: a voided mixed event's transient
  images are still purged when its (void-agnostic) estimation reaches terminal,
  and its saved images follow the existing retained-and-excluded rule.

## Errors

| Status | When |
| --- | --- |
| `413` | An `image` part exceeds `MAX_ATTACHMENT_BYTES` (10 MiB); whole submission rejected — no event, no attachment, no enqueue, no model call. |
| `415` | An `image` part has a disallowed content type, or its bytes' magic-number signature does not match the declared type; whole submission rejected as for `413`. |
| `422` | A missing/duplicate/non-JSON `payload` part, an unknown part name, more than `MAX_SUBMISSION_IMAGES` (4) images, a malformed `save` flag, an invalid `raw_text`/`idempotency_key` field, or an empty submission (no non-empty `raw_text` and no image). |

`401`/`404` follow the create endpoint's rules unchanged (`log-events.md`).

## Examples

```sh
# Mixed text+images submission: one multipart create, one pending event, one
# estimation job; images transiently persisted, purged at terminal because
# save defaults to false
curl -sX POST ':8000/api/users/<uid>/log-events' \
  -H 'authorization: Bearer <t>' \
  -F 'payload={"raw_text":"2 of these bars","idempotency_key":"01J...ULID"};type=application/json' \
  -F 'image=@label.jpg;type=image/jpeg'
# → 201 { "id": "...", "status": "pending", "raw_text": "2 of these bars", ... }
# A keyed retry of the same multipart submission replays: 200, same event,
# no duplicate attachment rows, no second job (image parts ignored).
```

The worked estimation case — `"2 of these bars"` + a label photo → `amount = 2`
(text-stated) scaling `user_label` label facts (image) deterministically — is
`parse-candidates.md` v12 (**Images as parse evidence surfaces**).

## Migration / Compatibility

- **FTY-374 (contract only; no code, no migration in this story).** Additive
  for the JSON path — nothing about the JSON create shape changes, so no
  back-compat shim exists or is needed; the multipart shape is new.
- Downstream implementation split: **FTY-375** (backend ingestion + retention,
  backend-core — including the additive `log_attachments.transient` migration,
  `log-attachments.md` v3), **FTY-376** (estimator consumption —
  `estimation-jobs.md` v6, `parse-candidates.md` v12), and a required follow-up
  **mobile composer** story for the attach affordance.
- Any shape defect found downstream returns as a planner note, not an inline
  contract edit by FTY-375/FTY-376.
