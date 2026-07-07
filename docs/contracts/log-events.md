# Contract: Log Events

## Purpose

Define the log-event data model, its status state machine, and the create /
list-today / get-by-id API, so a user can turn natural-language input into a
pending raw log event and read their Today events back. This gives the mobile
timeline (FTY-031) and polling (FTY-032) a real backend, and gives the estimator
(Milestone 4) the row it later processes.

This contract covers five things:

1. the `log_events` persistence schema and its migration;
2. the **event status state machine** — the full v1 status vocabulary and the
   legal transitions between statuses, a named contract the estimator stories
   extend without redefining;
3. the create / list-today / get-by-id request/response shapes and their
   object-level authorization rule;
4. the **clarify-loop API** for a `needs_clarification` or `partially_resolved`
   event — the clarification read (question text + quick-pick options) and the
   clarification answer (resolve) that applies a structured detail to the
   same event and re-estimates it;
5. the **day-listing read** (FTY-198) — an owner-scoped, Today-feed-shaped read
   for an arbitrary calendar day, returning each event plus the shared derived
   item read-model (`source` provenance + `is_edited`).

It deliberately excludes estimation, job enqueue, and worker processing
(FTY-040+); editing or deleting events (later stories); and new derived-item
persistence. The day-listing read composes the existing derived food/exercise
item read-model without changing its storage contract. Saved image attachments are owned by their own contract
(`log-attachments.md`, FTY-077): a `log_attachments` row references a log event but
is written only when the user explicitly saves an uploaded image.

## Owner

backend-core / contracts lane (`backend/app/models/log_events.py`,
`backend/app/schemas/log_events.py`, `backend/app/services/log_events.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`).

## Version

6 (FTY-278): defines the **item-scoped partial clarification** contract for a
mixed food log by adding a first-class **`partially_resolved`** event status — a
**pre-v1 additive extension** of the status vocabulary and state machine, with no
back-compat shim. Before FTY-278 a mixed log with any un-costable component routed
the *whole* entry to a terminal-with-nothing-committed `needs_clarification` event:
no item was persisted while a question waited. FTY-278 makes clarification
**item-scoped**: the costable components of the entry are committed as `resolved`
derived items (and counted — see `daily-summary.md`) on a new `partially_resolved`
event while a **specific unresolved component** owns the open question.
`needs_clarification` keeps its pre-FTY-278 meaning — event-level clarification
with *nothing* committed (no component individually costed). Concretely this story
settles four contract points and cross-links the affected contracts:

1. **Event status and transitions** — a new **`partially_resolved`** status is the
   item-scoped partial state: it carries committed `resolved` items alongside an
   open item-scoped question. The state machine gains two transitions —
   `processing → partially_resolved` (the estimator commits the costable siblings
   and raises the item-scoped question in one terminal transaction) and
   `partially_resolved → processing` (answering re-estimates the same event).
   `needs_clarification` and its transitions are unchanged and still mean the
   event-level, nothing-committed case.
2. **Question → component reference** — each item-scoped clarification question
   names the specific unresolved component by a stable `derived_food_item_id`
   reference (see `parse-candidates.md`), never by echoing the raw diary phrase;
   the clarification read surfaces that reference as `item_id` so the client
   associates the question with the resolved/unresolved item rows it already
   renders.
3. **Partial read exposure** — the day-listing read returns a partial event's
   committed `resolved` items (its event-status gate relaxes from `completed`-only
   to `completed` **or** `partially_resolved`); the open question remains
   discoverable through the status-gated clarification read.
4. **Answer flow** — answering an item-scoped question re-estimates the **same**
   event (`partially_resolved → processing`), preserves the already-resolved
   siblings, and completes the entry when the last component resolves, with no
   double-counting or duplicate item rows (the job/run mechanics are
   `estimation-jobs.md` v3).

**This version is a contract decision only; it edits no product code.** The
downstream estimator/backend implementation is a required follow-up split (called
out under Migration / Compatibility). Until it lands, the shipped behaviour is the
**FTY-275 baseline**: a genuinely amountless component still routes the whole event
to an event-level `needs_clarification` with nothing committed (`food-resolution.md`
v8/v9).

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
`needs_clarification` event (see [Clarification read](#clarification-read)). This
is additive: no existing DTO field, endpoint, or status code changes, and no
schema migration is involved (the `clarification_questions` table already exists).
It is the backend half of the "Add a detail" clarify flow; the mobile sheet
(FTY-153) consumes it.

2 (FTY-096): the create request gains an optional, opaque `idempotency_key`, and
create becomes a safe-to-retry **first-write-wins** operation — a fresh create
returns `201`, an idempotent replay of an already-submitted key returns `200`
with the existing event. The key namespace is per-user. This is the backend half
of offline logging (see [Offline submit](#offline-submit-and-the-pending-unparsed-state)).

1 (FTY-030): introduces the `log_events` table, the status state machine, and
the create/list/get API. Creation at `pending` and the `pending → completed`
transition are implemented; the `processing`, `failed`, and
`needs_clarification` transitions are defined in the state machine and
implemented by the estimator stories (Milestone 4).

## Inputs

### Persistence

The `0003` migration creates:

- **`log_events`** — a user-owned raw log entry. Columns: `id` (UUID, PK),
  `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`, indexed), `raw_text`
  (text, not null), `status` (string, not null), `idempotency_key` (string,
  **nullable**), `created_at` (timestamptz, not null, indexed), `updated_at`
  (timestamptz, not null). `created_at` is indexed because the Today timeline
  queries events by day.
- A composite **unique index** `(user_id, idempotency_key)`
  (`uq_log_events_user_idempotency_key`, added by the `0015` migration) makes the
  key namespace per-user and the database the dedup authority. NULL keys are
  distinct in Postgres (and SQLite), so the online/no-key path and the
  label-upload path keep inserting freely.

### HTTP requests

All requests carry `Authorization: Bearer <token>` and target the
authenticated user's own `{user_id}`.

- `POST /api/users/{user_id}/log-events` —
  `{ "raw_text": str, "idempotency_key"?: str }`. Creates a `pending` event.
  `raw_text` is trimmed; it must be non-empty after trimming and at most 2000
  characters. The optional `idempotency_key` is an **opaque** client token (a
  UUID/ULID by convention — the server never parses or interprets it): trimmed,
  non-empty after trimming when present, and at most 200 characters. Unknown body
  keys are rejected. See [Idempotent create](#idempotent-create-201-vs-200).
- `GET /api/users/{user_id}/log-events?day=YYYY-MM-DD` — lists the user's events
  whose `created_at` falls on `day`, resolved in the user's profile timezone.
  `day` is optional and defaults to the current day in that timezone.
- `GET /api/users/{user_id}/log-events/by-date?day=YYYY-MM-DD` — lists the user's
  day entries in the Today-feed shape: each row has `event` (the event DTO) and
  `items` (derived food/exercise item DTOs with `source` and `is_edited`). The
  same profile-timezone day bounds and oldest-first event ordering as
  `GET .../log-events?day=` apply. `day` is optional and defaults to the current
  day in that timezone.
- `GET /api/users/{user_id}/log-events/{event_id}` — returns one of the user's
  events by id (for polling).
- `GET /api/users/{user_id}/log-events/{event_id}/clarification` — returns the
  **unanswered** clarification questions persisted for one of the user's
  `needs_clarification` or `partially_resolved` events — question text plus
  quick-pick options — ordered by `position`. The read is **status-gated**: an
  event in any other status serves `{ "questions": [] }`. A lazy per-event read the client
  fetches when opening the clarify sheet, so the Today list/poll DTO stays
  lean. See [Clarification read](#clarification-read).
- `POST /api/users/{user_id}/log-events/{event_id}/clarification/answers` —
  `{ "question_id": UUID, "answer": str }`. Resolves one clarification
  question on the user's own `needs_clarification` or `partially_resolved` event
  by applying the answer as a structured detail to the **same** event and re-estimating it.
  See [Clarification answer (resolve)](#clarification-answer-resolve).

## Outputs

The event DTO (returned by create, each list element, get-by-id, and the
clarification answer):

```json
{
  "id": "UUID",
  "user_id": "UUID",
  "raw_text": "string",
  "status": "pending | processing | completed | failed | needs_clarification | partially_resolved",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

- **Create (fresh)** → `201` with the event DTO at `status: "pending"`.
- **Create (idempotent replay)** → `200` with the **existing** event's DTO at its
  current status (see [Idempotent create](#idempotent-create-201-vs-200)).
- **List-today** → `200` with a JSON array of event DTOs, ordered oldest-first.
- **Day-listing read** → `200` with a JSON array of entry DTOs, ordered
  oldest-first by the owning event:

```json
[
  {
    "event": {
      "id": "UUID",
      "user_id": "UUID",
      "raw_text": "rice and a walk",
      "status": "completed",
      "created_at": "datetime",
      "updated_at": "datetime"
    },
    "items": [
      {
        "item_type": "food",
        "id": "UUID",
        "user_id": "UUID",
        "log_event_id": "UUID",
        "name": "white rice",
        "quantity_text": "1 serving",
        "unit": null,
        "amount": 1.0,
        "status": "resolved",
        "grams": 150.0,
        "calories": 205.0,
        "protein_g": 4.3,
        "carbs_g": 44.5,
        "fat_g": 0.4,
        "calories_estimated": 205.0,
        "protein_g_estimated": 4.3,
        "carbs_g_estimated": 44.5,
        "fat_g_estimated": 0.4,
        "source": {
          "source_type": "trusted_nutrition_database",
          "label": "USDA",
          "ref": "usda_fdc:168880"
        },
        "is_edited": false,
        "created_at": "datetime",
        "updated_at": "datetime"
      }
    ]
  }
]
```

`items` uses the shared `DerivedFoodItemDTO | DerivedExerciseItemDTO` shape from
`corrections.md` / `daily-summary.md`, but only for finalized item detail: the
owning event must be `completed` **or** `partially_resolved` (the FTY-278 partial
state), the item must be `resolved`, and its costed value must be present
(`calories` for food, `active_calories` for exercise). This mirrors the
`daily-summary.md` finalized-state filter exactly — a `resolved`, costed item is
surfaced whether it is the whole of a `completed` entry or a **costable sibling of
a `partially_resolved` entry**, so a mixed log's resolved components appear in
place while its unresolved component's question stays open. A pending, processing,
failed, `needs_clarification`, or completed/partial-with-no-finalized-item event is
still returned with `items: []`, matching the Today timeline's status-row
fallback. Non-finalized item rows — including the **unresolved component** that
owns an item-scoped question — remain persisted with their own `status`
(`unresolved` / `proposed`) and nullable values but are **not** included in this
read; that component is instead discoverable through the status-gated
clarification read (its question carries the component's `item_id`), so the
`items` array stays "finalized costed detail only" and never surfaces an
uncosted placeholder row. (Under the FTY-275 baseline a mixed log routes to an
event-level `needs_clarification` with no committed items, so it returns
`items: []` until the FTY-278 follow-up lands.)
- **Get-by-id** → `200` with the event DTO.

The DTO does **not** echo `idempotency_key`: it is a write-only request token with
no consumer need in the response (a client already holds the key it sent).

**Timestamps are UTC, serialized timezone-aware.** `created_at` and `updated_at`
are stored as UTC (`timestamptz`) and serialized as **timezone-aware ISO-8601 with
an explicit UTC offset** (e.g. `2026-06-16T01:00:00Z`) — never a naive datetime a
client would misread as its own local time. This is what lets the client convert an
instant to the device zone unambiguously, so an entry logged the previous local
evening renders — and buckets — under the correct day. The backend enforces this at
the ORM boundary (a UTC-normalizing `timestamptz` type), so the guarantee holds on
every backend regardless of whether the driver preserves the offset on read.

### Idempotent create (`201` vs `200`)

`POST .../log-events` is safe to retry when an `idempotency_key` is supplied —
**first-write-wins**, scoped per user:

- **No key** → behaves exactly as v1: create a `pending` event and enqueue its
  estimation job. Returns `201`. Back-compatible.
- **Key supplied, no event yet for `(user_id, key)`** → create the `pending`
  event, store the key, enqueue the job. Returns `201`.
- **Key supplied, an event already exists for `(user_id, key)`** → return that
  **existing** event's current DTO, create **no** new row, enqueue **no** second
  job. Returns `200`. The `201`/`200` distinction lets the client tell a fresh
  create from a replay.

Replay reflects the event's **current** status: if the original has advanced to
`processing` or `completed` before the retry arrives, the replay returns that
status so the client reconciles rather than resetting it.

The create path is **race-safe**: two concurrent same-key submits (a double outbox
flush, parallel retries) converge to one event. The `(user_id, idempotency_key)`
unique index is the guard — the insert that loses the race catches the integrity
violation, re-reads the now-committed sibling, and returns it as the `200` replay.
No `500`, no duplicate, no orphaned second enqueue.

**Body mismatch is not an error.** A replay carrying a different `raw_text` under
the same key still returns the **originally stored** event (no new row, no
re-enqueue); the divergent body is ignored. The offline outbox sends a
byte-identical body by construction, so a mismatch only arises from a client
key-reuse bug, and the client owns key generation.

### Offline submit and the pending-unparsed state

An offline-queued entry is a **client-only** state (the FTY-104 outbox) with **no
server row** until it is submitted. There is no server status for "queued offline":
on submit the entry becomes a server `pending` event — the pending-unparsed,
uncounted state (a raw event exists but no derived items yet, so it does not count
in the day's totals) — and runs the unchanged `pending → processing → completed`
transitions the estimator drives (see `estimation-jobs.md`). A keyed create
enqueues exactly as the no-key path does; the replay path enqueues nothing.

### Clarification read

`GET /api/users/{user_id}/log-events/{event_id}/clarification` exposes the
clarification questions the estimator persisted for an event (the parse step
writes one `clarification_questions` row per question when the input is
genuinely indeterminate; this endpoint reads them back to the owning client).
It is the data the mobile clarify sheet (FTY-153) needs to render Fatty's
actual question with tappable quick-pick chips and a free-text fallback
(`docs/design/ux-design.md` §4a) instead of a generic line over a bare text
field.

The response carries a `needs_clarification` or `partially_resolved` event's
**unanswered** questions, ordered by `position` (the read is **status-gated** —
see below). Each
question carries its persisted row's stable `id` (the key an answer submission
references), the specific question `text`, an `options` array of candidate
quick-pick values, and — for an **item-scoped** question (FTY-278) — an `item_id`
naming the specific unresolved derived component the question is about:

```json
{
  "questions": [
    {
      "id": "b9c1…",
      "text": "How much milk?",
      "options": ["a splash", "1/2 cup", "1 cup"],
      "item_id": "e4a2…"
    }
  ]
}
```

- **`item_id` is the target unresolved component (FTY-278).** The
  `derived_food_items.id` of the persisted `unresolved` component this question
  clarifies (see `parse-candidates.md`), so a client attaches the question to the
  exact item row it already renders — scoped to that component, not the whole
  entry. It is `null` for an **event-level** question (parse-time ambiguity not
  tied to one component — including every question under the FTY-275 baseline,
  where no component is individually costed). It never contains the raw diary
  phrase; the human context is the referenced component's own sanitized `name`.

- **Options are display candidates, never an enum.** They exist so the client
  can render one-tap chips; the server never validates an answer against
  them. **Free-text is always an allowed answer**, whether or not options are
  present.
- **When present, options are up to 5 short candidates** (2–5 for model-raised
  parse clarifications; deterministic backend-raised questions may have none),
  each length-bounded — the
  bounds and the persistence shape are the parse contract's
  (`parse-candidates.md` v2, `ClarificationQuestion`). The list MAY be empty;
  the client then shows the free-text affordance only (e.g. the deterministic
  plausibility/food/exercise/label gates' targeted questions carry no options).

The read is **status-gated, not row-driven**: questions are served only while
the event is in `needs_clarification` **or** `partially_resolved` — the two
statuses in which a fresh answer can be accepted (see the `409` rule under
[Clarification answer](#clarification-answer-resolve)).

- **Owned `needs_clarification` or `partially_resolved` event with unanswered
  questions** → `200` with the questions ordered by `position`, matching the
  stored rows.
- **Owned event in any other status, or with no unanswered rows persisted** →
  `200 { "questions": [] }`. There is **no status oracle**: "wrong status" and
  "no rows" are indistinguishable. The status gate matters in the mid-round
  window the answer flow itself creates: with two questions in a round,
  answering Q1 drives the event to `processing` while Q2's row is still
  persisted and unanswered. The read returns `[]` in that window rather than
  serving a question whose fresh answer would `409` (a chip the client could
  only dead-end on). The leftover row is stale pending the re-estimate's
  outcome — a fresh clarification round **replaces** the unanswered rows, and
  a completing re-estimate leaves them permanently unserved.
- **Cross-user or nonexistent `event_id`** → `404`, reusing get-by-id's
  fail-closed scoping (no existence oracle).

An answered question is resolved and is not re-served. When a re-estimate
raises a fresh clarification round, the new round's questions **replace** the
event's unanswered rows (see `parse-candidates.md`), so for a clarifying event
(`needs_clarification` or `partially_resolved`) the read serves exactly the
questions still open.

### Clarification answer (resolve)

`POST /api/users/{user_id}/log-events/{event_id}/clarification/answers`
resolves one clarification question on the caller's own `needs_clarification` or
`partially_resolved` event. The answer — a tapped quick-pick option's value or free text — is
applied as a **structured detail to the same event**, which is then
re-estimated with that detail as structured input. This is the first-class
resolve that replaces the retired v3 mechanism (re-submitting a combined
phrase through the create path).

Request body (unknown keys rejected):

```json
{ "question_id": "b9c1…", "answer": "4" }
```

- `question_id` — required; the `id` of one of the event's persisted
  clarification questions (from the clarification read).
- `answer` — required; the user's answer as opaque text. Trimmed; **must be
  non-empty after trimming** — an empty or whitespace-only answer is rejected
  with `422` and never submitted — and at most 300 characters. It is untrusted
  user input: stored as data via a parameterized insert, passed to the
  re-estimate as structured input, never executed or interpreted, and never
  validated against the question's `options` (free text is always allowed).

A fresh, valid answer:

1. persists the answer against the question (see **Answer persistence**
   below);
2. transitions the **same** event to `processing` — `needs_clarification →
   processing` for an event-level question, `partially_resolved → processing`
   for an item-scoped one (both legal in the state machine below) — and
   re-estimates it with the raw phrase plus **every answered (question, answer)
   pair** as structured input. The job/run mechanics of that re-estimate are
   `estimation-jobs.md` v2 (FTY-171): the resolve re-opens the event's
   terminal job for a fresh answer-triggered attempt in the same transaction,
   then enqueues; the worker itself never re-opens a terminal job, preserving
   redelivery idempotency;
3. returns `201` with the event DTO at `status: "processing"`, so the client
   updates the entry in place and polls as usual.

**Forbidden behaviours.** Contract requirements, closing the audit findings
the retired mechanism produced:

- The answer MUST NOT mutate or append to `raw_text` — the raw phrase is
  never rewritten, and nothing in the request can carry a replacement phrase
  (finding A3).
- The resolve MUST NOT create a second log event or any duplicate row — the
  detail lands on the same `event_id` (finding A5).
- An empty/whitespace answer MUST be rejected (`422`), never accepted as a
  silent no-op resolve.

**One answer per submit; rounds, not batches.** A request resolves exactly one
question (the sheet's one-tap chip flow, `ux-design.md` §4a). The re-estimate
runs with every detail answered so far; if the enriched input is still
genuinely indeterminate, the estimator raises a **fresh** clarification round
(`processing → partially_resolved` when costable siblings remain committed, or
`processing → needs_clarification` for the event-level case, with new question
rows replacing the unanswered ones); otherwise the event completes and starts
counting.

**Item-scoped resolution preserves the resolved siblings (FTY-278).** When the
answered question is item-scoped (it carries an `item_id`, so the event is
`partially_resolved`), the answer supplies the missing portion for **that one
component**; the re-estimate must not re-ask for, re-cost, or duplicate the
components already resolved in an earlier round. The re-estimate rebuilds the
event's derived items **as a set** within its terminal transaction — resolved
siblings are represented exactly once and their committed values are unchanged,
and only the newly-answered component is advanced from `unresolved` to `resolved`
(or, if the enriched input is still indeterminate, the event stays
`partially_resolved` with a fresh item-scoped question while the siblings stay
resolved). Because `intake` sums the event's `resolved` items and the event's
item set is replaced atomically per round, a component resolved in an earlier
round can never be **double-counted** or spawn a **duplicate** row (the job/run
mechanics are `estimation-jobs.md` v3; the counting rule is `daily-summary.md`).
When the final unresolved component resolves, the event reaches `completed` with
the full costed set. **Baseline:** until the FTY-278 implementation lands, a mixed
log routes to an event-level `needs_clarification` carrying no committed siblings,
so the answer flow is the event-level FTY-170 round-trip unchanged.

**Idempotent on retry (first-write-wins per question).** The unique
`question_id` on the persisted answer is the idempotency anchor, mirroring the
FTY-096 create semantics with the question id in the role of the key:

- **Question not yet answered** (event `needs_clarification` or
  `partially_resolved`) → persist the answer, drive the transition, re-estimate.
  Returns `201`.
- **Question already answered** → `200` with the event's **current** DTO —
  no new answer row, no second transition, no double re-estimate. A re-sent
  identical answer thus converges to the one resolved entry, and the replay
  reflects the event's current status (`processing`, `completed`, or a fresh
  `needs_clarification` round) so the client reconciles rather than
  resetting it.
- **Body mismatch is not an error.** A replay carrying a different `answer`
  under an already-answered `question_id` returns the stored outcome; the
  divergent body is ignored (the FTY-096 rule). Changing a resolved detail
  afterwards is the corrections path, not a second resolve.
- **Race-safe.** Two concurrent submits for the same question converge to one
  answer and one re-estimate: the insert that loses on the unique
  `question_id` catches the integrity violation, re-reads the committed
  sibling, and returns the `200` replay. No duplicate resolve, no orphaned
  second re-estimate.

**Fresh answer on an event not awaiting clarification** — the question is
unanswered but the event is not in `needs_clarification` or `partially_resolved`
(e.g. another question's answer already drove it to `processing`) →
`409 {"error": "not_awaiting_clarification"}`; nothing is persisted or
mutated. Only the replay path returns success for a non-clarifying
event, because that answer has already been applied.
Because the clarification read is status-gated, a client that fetches fresh
never renders a chip that would `409`; the `409` guards the race where the
client holds questions from an earlier fetch (or a sibling answer lands
concurrently) and the event has since moved on.

**Answer persistence (implemented by FTY-171).** One row per answered question
in `clarification_answers`: `id` (UUID PK), `question_id` (UUID, FK →
`clarification_questions.id`, `ON DELETE CASCADE`, **unique** — the
idempotency anchor: at most one answer per question), `log_event_id` and
`user_id` (UUID FKs, `ON DELETE CASCADE`, indexed — ownership at the
persistence boundary), `answer_text` (text, not null), `created_at` /
`updated_at` (timestamptz). Retention follows the owning question, event, and
account via the cascades. Answered questions and their answers are **kept** when a fresh round replaces the unanswered
rows (they carry the details the re-estimate consumes), and they survive the derived-item **rebuild** because an item-scoped
question's `derived_food_item_id` is `ON DELETE SET NULL` (`parse-candidates.md` v5), not `CASCADE`: replacing its target row **detaches** the answered question rather than cascade-deleting it or its `question_id` answer anchor.

**A resolve is a re-estimate, not an edit.** The answer supplies a missing
detail and the estimator recomputes the entry from the enriched input; the
result carries estimator provenance and the item is not marked user-edited.
Deterministically overriding a derived item's value or portion afterwards is
the separate corrections path (`corrections.md`) — the two levers must not be
conflated.

## State machine

`status` is a `LogEventStatus`. The legal transitions are the named contract in
`app/services/log_events.py` (`LEGAL_TRANSITIONS`); the only mutation path
(`transition_event`) rejects any transition not in the map.

| From | To |
| --- | --- |
| `pending` | `processing`, `completed` |
| `processing` | `completed`, `failed`, `needs_clarification`, `partially_resolved` |
| `needs_clarification` | `processing` |
| `partially_resolved` | `processing` |
| `completed` | _(terminal)_ |
| `failed` | _(terminal)_ |

FTY-030 implements creation at `pending` and the `pending → completed`
transition (exercised via the service contract before the estimator exists).
The estimator stories drive the `processing` / `failed` / `needs_clarification`
transitions by reusing this map. The clarification answer (FTY-170, above) is
the user-driven trigger for the already-legal `needs_clarification →
processing` transition; it adds no new status and no new transition.

**FTY-278 adds the `partially_resolved` status and two transitions** —
`processing → partially_resolved` and `partially_resolved → processing`.
`partially_resolved` is the item-scoped partial state: the event carries committed
`resolved` derived items (the costable siblings of a mixed log) alongside its open
item-scoped question, whereas `needs_clarification` keeps its meaning of
event-level clarification with **nothing** committed. The costable siblings are
committed in the same terminal transaction as the `processing →
partially_resolved` transition — the same atomicity the `processing → completed`
path already uses (`food-resolution.md`). Answering the item-scoped question drives
`partially_resolved → processing` and re-estimates the same event (the FTY-170
answer round-trip, generalized to the new source status). The `needs_clarification`
transitions are unchanged.

This is the **event** status vocabulary. The separate **derived-item** status
vocabulary (`DerivedItemStatus`: `unresolved` / `resolved`, plus `proposed` added
by FTY-196 for an uncounted, confirmation-required nutrition-label parse) is owned
by the estimator/label contracts (`label-upload.md`, `label-extraction.md`,
`daily-summary.md`), not here — this contract deliberately excludes derived
food/exercise items. FTY-196 adds no event status and does not change this map: a
label event still reaches terminal `completed`; only its food item is held
`proposed` until confirmed.

## Validation

- `raw_text`: required; trimmed; non-empty after trimming; 1–2000 characters.
  Whitespace-only input is rejected.
- `idempotency_key`: optional; when present, a string, trimmed, non-empty after
  trimming, and at most 200 characters. An over-length, empty/whitespace, or
  wrong-type key is rejected (`422`). It is validated as opaque data only — the
  server never parses it.
- `day`: a valid `YYYY-MM-DD` date; otherwise `422`.
- `question_id` (answer submission): required; a UUID. Missing or malformed →
  `422`. Well-formed but not one of the owned event's questions → `404` (fail
  closed, no existence oracle).
- `answer` (answer submission): required; a string, trimmed, non-empty after
  trimming, at most 300 characters. Empty/whitespace-only, oversized, or
  wrong-type → `422` — an empty answer is never submitted.
- Unknown request-body keys are rejected (`422`).
- Status is never client-settable on create; it is server-controlled and only
  changes through the state machine.

## Authorization

- Authentication: every endpoint requires a valid, unexpired bearer token;
  otherwise `401`.
- Object-level authorization: a user may create, list, and read **only their
  own** events. `{user_id}` must equal the authenticated user's id, and
  get-by-id is scoped to the owner so a cross-user id is indistinguishable from a
  missing one. A mismatch fails closed as `404` (no existence oracle). Negative
  tests prove create, list, get-by-id, and the day-listing read all fail closed.
- The clarification read reuses the same object-level scoping: a cross-user or
  nonexistent `event_id` returns `404` with no existence oracle, proven by a
  cross-user negative test.
- The clarification answer fails closed the same way: the event is loaded
  scoped to the authenticated owner, and `question_id` is resolved **scoped to
  that event** — a cross-user or nonexistent event, or a `question_id` that is
  not one of that event's questions, returns `404` with no existence oracle
  and mutates nothing. Proven by cross-user and cross-event negative tests.
- The idempotency-key lookup is **scoped to the authenticated user**, so a key can
  only ever address that user's own events: the same key string from two users
  yields two distinct events and never crosses the boundary. Proven by a per-user
  namespacing test alongside the unchanged cross-user negative tests.

## Privacy and Retention

- `raw_text` is sensitive personal data: it is user-owned, never logged, and
  never returned to a non-owner.
- Day-listing item names, calories/macros/burn values, and provenance are
  sensitive nutrition data: they are returned only to the owner through the
  scoped read, are not logged, and are derived server-side so the client never
  joins `evidence_sources` / `corrections`.
- `clarification_questions.question_text`, its quick-pick `options`, and
  `clarification_answers.answer_text` are likewise tied to the user's
  sensitive log: they are returned only to the owning client, never logged,
  never copied into estimation-run `trace`/`error` (the `parse-candidates.md`
  no-raw-text rule), and never returned to a non-owner.
- `idempotency_key` is treated as potentially sensitive (a client may derive it
  from content): it is never logged, never returned in the DTO, and never surfaced
  to a non-owner.
- Retention (per `docs/security/data-retention.md`): food and exercise logs are
  retained until user deletion or account deletion. `ON DELETE CASCADE` on
  `user_id` removes a user's events — including the `idempotency_key` column,
  which lives on `log_events` and adds no new retention surface — when the account
  is deleted.

## Errors

| Status | When |
| --- | --- |
| `401` | Missing/invalid/expired bearer token. |
| `404` | Creating, listing, day-listing, or reading events for an account the caller does not own; a get-by-id, clarification read, or clarification answer whose event does not exist for the owner; an answer whose `question_id` is not one of the owned event's questions (all fail closed). |
| `409` | A fresh (non-replay) answer for an event not in `needs_clarification` or `partially_resolved` — `{"error": "not_awaiting_clarification"}`; nothing persisted or mutated. |
| `422` | Empty/whitespace/oversized `raw_text`, empty/whitespace/oversized/wrong-type `idempotency_key`, unknown body key, malformed `day`, missing/malformed `question_id`, or empty/whitespace/oversized/wrong-type `answer`. |

## Examples

```sh
# Create a pending event
curl -sX POST :8000/api/users/<uid>/log-events \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"raw_text":"two eggs and toast"}'
# → 201 { "id": "...", "status": "pending", "raw_text": "two eggs and toast", ... }

# Offline submit with an idempotency key, then a safe retry of the same key
curl -sX POST :8000/api/users/<uid>/log-events \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"raw_text":"two eggs and toast","idempotency_key":"01J...ULID"}'
# → 201 { "id": "abc", "status": "pending", ... }
curl -sX POST :8000/api/users/<uid>/log-events \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"raw_text":"two eggs and toast","idempotency_key":"01J...ULID"}'
# → 200 { "id": "abc", "status": "pending", ... }   # same id, no new row, no re-enqueue

# List today's events
curl -s ':8000/api/users/<uid>/log-events?day=2026-06-26' -H 'authorization: Bearer <t>'
# → 200 [ { "id": "...", "status": "pending", ... } ]

# List a day's Today-feed-shaped entries with derived item provenance
curl -s ':8000/api/users/<uid>/log-events/by-date?day=2026-06-26' \
  -H 'authorization: Bearer <t>'
# → 200 [ { "event": { "id": "...", "status": "completed", ... },
#           "items": [ { "item_type": "food", "source": { ... },
#                        "is_edited": false, ... } ] } ]

# Poll one event
curl -s :8000/api/users/<uid>/log-events/<event_id> -H 'authorization: Bearer <t>'
# → 200 { "id": "...", "status": "pending", ... }

# Read an event's open clarification questions (for the clarify sheet)
curl -s :8000/api/users/<uid>/log-events/<event_id>/clarification -H 'authorization: Bearer <t>'
# → 200 { "questions": [ { "id": "b9c1…", "text": "How many cracker sandwiches?",
#                          "options": ["2", "4", "6"] } ] }
# (status-gated: an event not in needs_clarification or partially_resolved, or
#  with no unanswered rows, → 200 { "questions": [] })

# Answer one question (a tapped chip or free text), then retry the same answer safely
curl -sX POST :8000/api/users/<uid>/log-events/<event_id>/clarification/answers \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"question_id":"b9c1…","answer":"4"}'
# → 201 { "id": "<event_id>", "status": "processing",
#         "raw_text": "crackers and peanut butter", ... }
#   (same event, raw phrase untouched, no new row; re-estimated with the detail)
curl -sX POST :8000/api/users/<uid>/log-events/<event_id>/clarification/answers \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"question_id":"b9c1…","answer":"4"}'
# → 200 { "id": "<event_id>", "status": "completed", ... }
#   (idempotent replay: converged to the one resolved entry, no double re-estimate)
```

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
  `clarification_answers` table (see **Answer persistence** above) with its
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
  item-scoped partial state, adds the clarification read's `item_id`
  target-component field, relaxes the day-listing read's event-status gate to
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
  story); (b) the backend read/answer story that serves `item_id`, relaxes the
  day-listing and daily-summary reads, and implements the sibling-preserving
  re-estimate (`estimation-jobs.md` v3, `daily-summary.md`); and, once the reads
  expose partial state, an optional mobile presentation story (no visual redesign
  is specified here). Until that split lands, the shipped behaviour is the
  FTY-275 baseline: an amountless component routes the whole event to an
  event-level `needs_clarification` with nothing committed.
