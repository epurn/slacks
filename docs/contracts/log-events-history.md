# Contract: Log Events — Version & Migration History

## Purpose

The change history for [log-events.md](log-events.md): its reverse-chronological
`## Version` log and its `## Migration / Compatibility` log. It lives here so the
normative contract page stays focused on current behaviour while the full history
stays complete and un-truncated. This page is **non-normative**: it records what
changed and when; the binding rules live in `log-events.md`.

## Owner

backend-core / contracts lane (`backend/app/models/log_events.py`,
`backend/app/schemas/log_events.py`, `backend/app/services/log_events.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`).

## Version

12 (FTY-423, contract only): **structural relocation** — the `## Version` log and
the `## Migration / Compatibility` log move out of [log-events.md](log-events.md)
into this dedicated history page, leaving a forwarding pointer at each vacated
heading and re-pointing the sibling-contract version/migration citations here.
**No semantic change**: every prior version entry and migration/compatibility
bullet is preserved verbatim; nothing about the log-event data model, endpoints,
DTO, schema, migrations, state machine, validation, or read models changes.

11 (FTY-421): the event DTO gains a nullable **`name`** — a short,
human-readable **model-generated** meal label (e.g. `"Turkey sandwich"`). It is
added as a nullable `String` column on `log_events` (migration `0023`,
additive, Postgres/SQLite-parity, no backfill) and threaded through the event
DTO returned by create, get-by-id, and the by-date list read. It is **never
user-authored** in v1: the estimator (FTY-422) is the sole writer, so `name` is
`null` on every existing row and on every freshly-created event until estimation
names it. This story only creates and exposes the field; population (FTY-422)
and mobile display (FTY-420) are separate slices.

10 (FTY-384, contract only): **structural relocation** — the soft-void (delete)
semantics (the detailed `### Soft-void (delete) (FTY-321)` section) move out of
this page into [log-event-soft-void.md](log-event-soft-void.md). **No semantic
change**: the marker-not-deletion, read-model exclusion, fail-closed
single-item-surface enumeration, any-status voiding, database-enforced
first-write-wins idempotency, void-does-not-cancel-estimation, and no-oracle
`404` rules are preserved verbatim. This page keeps everything else it owns for
the void — the `voided_at` column, the `DELETE` endpoint listing and its `204`,
the voided-replay `404` on idempotent create, and the state-machine note — and
links to the new page for the full semantics.

9 (FTY-374, contract only): create gains the **unified text+image submission**
— the endpoint now also accepts `multipart/form-data` (one JSON `payload` part
plus 0..N fail-closed validated `image` parts) while the `application/json`
body stays **byte-for-byte unchanged**, preserving the FTY-104 offline outbox
and every text-only client. The wire shape, validation/limits, async
never-reject rationale, transient retention, and replay-re-ingests-nothing
rules are owned by [log-event-images.md](log-event-images.md); this page's
event DTO, status machine, idempotency, and counting semantics are unchanged.

8 (FTY-321): adds the **soft-void (delete) operation** — `DELETE
/api/users/{user_id}/log-events/{event_id}` — and a nullable `voided_at`
timestamptz on `log_events` (migration `0019`). Voiding is the user removing a
mislogged entry: it sets `voided_at` **once** (a terminal status; there is no
un-void), which excludes the event **and every derived item hanging off it**
from the list / by-date / single GET, the clarification read/answer, the
day-listing items, and the daily-summary intake/exercise/`uncounted_entries`
totals — so the entry disappears from the day. The **keyed create-replay** and
the **single-item mutation endpoints** (correction edit, re-match
candidate-list / re-resolve) **fail closed (`404`)** against a voided event via
backend-core boundary prechecks, since they return/mutate their target row
directly and bypass the read-time join. **No row is hard-deleted**: the
event, its derived items, corrections, and evidence are all retained, preserving
the append-only audit/provenance stance (`corrections.md` reconciled). The
delete is **idempotent** (repeating it returns `204` identically) and works from
any status (`completed` / `needs_clarification` / `failed` / …); a cross-user or
unknown id fails closed as `404` (no existence oracle), matching every other
log-event route. `voided_at` is an orthogonal marker, **not** a new
`LogEventStatus` value, so the event keeps its pre-void estimation status for
audit and the state-machine map is unchanged. Void does **not** cancel an
in-flight or queued estimation (the estimator is void-agnostic;
`estimation-jobs.md` unchanged): derived rows a late estimation writes onto a
voided event are retained-and-excluded by the read-time parent-`voided_at`
join.

7 (FTY-282): relocates the clarify-loop **endpoint contract** — the
clarification read and the clarification answer (resolve), and their
examples — out of this doc into a new `clarification.md` page. **Structural
relocation only, no semantic change**: the read/answer shapes, status gating,
idempotency, and privacy rules are preserved verbatim. This doc keeps
everything else it owns — persistence, create/list/get, the full event status
state machine (including `needs_clarification` and `partially_resolved`),
validation, authorization, privacy/retention, and errors — since the clarify
endpoints are still gated by the statuses defined here.

6 (FTY-278, contract only): defines the **item-scoped partial clarification**
contract for a mixed food log by adding the first-class **`partially_resolved`**
event status — a **pre-v1 additive extension** of the status vocabulary and
state machine, with no back-compat shim. A mixed entry is no longer
all-or-nothing: the costable components are committed as `resolved` items (and
counted — `daily-summary.md`) on a `partially_resolved` event while a specific
unresolved component owns the open question; `needs_clarification` keeps its
event-level, nothing-committed meaning. The two new transitions and the
sibling-preserving answer flow are specified under
[State machine](log-events.md#state-machine) and in `estimation-jobs.md` v3; the internal
question→component reference (`derived_food_item_id`, never surfaced — the
FTY-170 read/answer shape is unchanged) is `parse-candidates.md` v5; the
day-listing read's event-status gate relaxes to `completed` **or**
`partially_resolved`. The estimator/backend implementation is a required
follow-up split (see Migration / Compatibility); until it lands, FTY-301's
rough-estimate default applies and any remaining allowed clarification is still
event-level `needs_clarification` with nothing committed.

5 (FTY-198): adds the **day-listing read** —
`GET /api/users/{user_id}/log-events/by-date?day=YYYY-MM-DD` — which returns an
oldest-first list of entries for one profile-timezone calendar day. Each entry
carries the log event envelope plus the same derived item DTOs the Today timeline
renders, including per-item `source` provenance and `is_edited` from the shared
item read-model (`daily-summary.md` / `corrections.md`). Existing create,
list-events, get-by-id, clarification, and label endpoints are unchanged.

4 (FTY-170): a **pre-v1 breaking change** to the clarify loop (no back-compat
shim). The clarification read's per-question shape grows from `{ text }` to
`{ id, text, options }` — each question now carries a stable id and candidate
quick-pick options — and a first-class **clarification answer (resolve)**
endpoint is added:
`POST /api/users/{user_id}/log-events/{event_id}/clarification/answers`. A
valid answer applies a structured detail to the **same** event, drives
`needs_clarification → processing`, and re-estimates the event; the raw phrase
is never mutated and no second event is created. This **retires** the interim
v3 resolve mechanism — re-submitting the combined phrase via the create path
(FTY-149) — which is the documented cause of the raw-phrase-mutation and
duplicate-entry audit findings (A3/A5); the missing question/options in the
read were finding A2. Consumers landing against the new shapes: FTY-172
(estimator produces question + options — see `parse-candidates.md` v2),
FTY-171 (backend serves the new read shape and implements the answer
round-trip — evolving `estimation-jobs.md` beyond its v1 one-job-per-event /
never-reprocessed rules to express the answer-triggered re-estimate; that
amendment landed as `estimation-jobs.md` v2), FTY-153 (mobile clarify sheet).

3 (FTY-152): adds an **owner-scoped clarification read** —
`GET /api/users/{user_id}/log-events/{event_id}/clarification` — that returns the
clarification questions the estimator already persisted for a
`needs_clarification` event (see [Clarification read](clarification.md#clarification-read)). This
is additive: no existing DTO field, endpoint, or status code changes, and no
schema migration is involved (the `clarification_questions` table already exists).
It is the backend half of the "Add a detail" clarify flow; the mobile sheet
(FTY-153) consumes it.

2 (FTY-096): the create request gains an optional, opaque `idempotency_key`, and
create becomes a safe-to-retry **first-write-wins** operation — a fresh create
returns `201`, an idempotent replay of an already-submitted key returns `200`
with the existing event. The key namespace is per-user. This is the backend half
of offline logging (see [Offline submit](log-events.md#offline-submit-and-the-pending-unparsed-state)).

1 (FTY-030): introduces the `log_events` table, the status state machine, and
the create/list/get API. Creation at `pending` and the `pending → completed`
transition are implemented; the `processing`, `failed`, and
`needs_clarification` transitions are defined in the state machine and
implemented by the estimator stories (Milestone 4).

## Migration / Compatibility

- The `0003` migration applies cleanly (`alembic upgrade head`) on top of the
  goals/targets schema and is fully reversible (`alembic downgrade 0002`),
  verified by a migration apply/rollback test against a throwaway database.
- The `0015` migration (FTY-096) is additive: it adds the nullable
  `idempotency_key` column and the `(user_id, idempotency_key)` unique index to
  `log_events`, with no backfill (existing rows keep a NULL key and are
  unaffected). It applies on top of `0014` and rolls back cleanly
  (`alembic downgrade 0014`), verified by a migration apply/rollback test.
- These are additive migrations; no prior table or column is altered.
- Consumers (FTY-031 timeline, FTY-032 polling) depend on the event DTO and the
  endpoint shapes; the estimator (M4) depends on the table and extends the state
  machine map defined here. The offline outbox (FTY-104) depends on the
  safe-to-retry submit semantics and the `201`/`200` distinction.
- The FTY-152 clarification read is additive and needs no migration: the
  `clarification_questions` table already exists (migration `0005`, FTY-042).
- The `0016` migration (FTY-171) is **additive**: it creates the
  `clarification_answers` table (see **Answer persistence**,
  `clarification.md`) with its
  unique `question_id` idempotency anchor and cascading ownership FKs; no prior
  table or column is altered and no backfill is needed. It applies on top of
  `0015` and rolls back cleanly (`alembic downgrade 0015`), verified by an
  apply/rollback test and exercised against Postgres by the FTY-143 migration
  guard.
- The `0017` migration (FTY-172) is **additive**: it adds the not-null
  `options` JSON column to `clarification_questions`, backfilled/defaulted to
  `[]` for existing deterministic questions. It applies on top of `0016` and
  rolls back cleanly (`alembic downgrade 0016`), verified by an
  apply/rollback test.
- The `0019` migration (FTY-321) is **additive**: it adds the nullable
  `voided_at` timestamptz column to `log_events` with no backfill (existing rows
  keep `voided_at = NULL` and stay live). It applies on top of `0018` and rolls
  back cleanly (`alembic downgrade 0018`), verified by an apply/rollback test
  and exercised against Postgres by the FTY-143 migration guard. Retention is
  unchanged — the column lives on `log_events` and is removed by the existing
  `ON DELETE CASCADE` on account deletion.
- The `0023` migration (FTY-421) is **additive**: it adds the nullable `name`
  `String` column to `log_events` with no backfill (existing rows read back
  `name = NULL` and stay live). Rendered DDL is Postgres/SQLite-parity — a plain
  nullable column with no server default. It applies on top of `0022` and rolls
  back cleanly (`alembic downgrade 0022`), verified by an apply/rollback test and
  exercised against Postgres by the FTY-143 migration guard. Retention is
  unchanged — the column lives on `log_events` and is removed by the existing
  `ON DELETE CASCADE` on account deletion. The estimator (FTY-422) is the writer;
  the mobile display (FTY-420) is the reader.
- **FTY-170 (breaking, pre-v1, no shim).** The clarification read's
  per-question shape changes from `{ text }` to `{ id, text, options }`, the
  read is scoped to unanswered questions, and the clarification answer
  (resolve) endpoint is added. The interim resolve — re-submitting the
  combined phrase via the create path (FTY-149) — is **retired**; it mutated
  the raw phrase and duplicated entries (audit findings A3/A5). No back-compat
  shim is kept: pre-v1, the old shape has no consumers to preserve. Landing
  order for implementers: the `options` persistence and produce side is the
  parse contract's (`parse-candidates.md` v2, `0017` with FTY-172); the
  `clarification_answers` table, the new read shape, and the answer round-trip
  are FTY-171; the mobile clarify sheet (FTY-153) consumes both new shapes.
- **FTY-278 (contract only; additive, pre-v1, no shim).** Adds the first-class
  `partially_resolved` event status and its two transitions
  (`processing → partially_resolved`, `partially_resolved → processing`) as the
  item-scoped partial state, keeps the **FTY-170 clarification read/answer shape
  unchanged** (the item↔question link stays the internal, producer-side
  `clarification_questions.derived_food_item_id`, `parse-candidates.md` v5 — never
  surfaced in the read), relaxes the day-listing read's event-status gate to
  include `partially_resolved`, and specifies the sibling-preserving answer
  re-estimate. The new status is a value in the existing string `status` column,
  so it needs **no schema migration**. **No code, no migration, and no read/DTO
  change land in this story** — it settles the semantics only. The downstream
  **implementation is a required follow-up split** (planner-decomposed into
  properly-laned stories): (a) a parse/estimator story to persist an entry's
  costable siblings on a `partially_resolved` event and link each item-scoped
  question to its `unresolved` component via the additive, nullable
  `derived_food_items.id` reference on `clarification_questions`
  (`parse-candidates.md` v5 — an additive, reversible migration owned by that
  story); (b) the backend read/answer story that relaxes the day-listing and
  daily-summary reads and implements the sibling-preserving re-estimate
  (`estimation-jobs.md` v3, `daily-summary.md`), leaving the FTY-170
  clarification read/answer shape unchanged; and, once the reads
  expose partial state, an optional mobile presentation story (no visual redesign
  is specified here). Until that split lands, FTY-301's default rough-estimate path
  handles recognizable amountless components; any remaining allowed clarification
  still routes the whole event to event-level `needs_clarification` with nothing
  committed.
- **FTY-374 (contract only; no code, no migration in this story).** Adds the
  unified text+image create ([log-event-images.md](log-event-images.md); the
  retention/worker/parse halves are `log-attachments.md` v3,
  `estimation-jobs.md` v6, `parse-candidates.md` v12 /
  `interpretation-session.md` v2). Additive for the JSON path — nothing about
  the JSON shape changes. Downstream: **FTY-375** (ingestion/retention),
  **FTY-376** (estimator consumption), plus a required follow-up **mobile
  composer** story.
