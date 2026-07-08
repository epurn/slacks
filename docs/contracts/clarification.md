# Contract: Clarification

## Purpose

Define the **clarify-loop sub-API** for a `needs_clarification` or
`partially_resolved` log event: the clarification read (question text plus
quick-pick options) and the clarification answer (resolve) that applies a
structured detail to the same event and re-estimates it. This is the "Add a
detail" round-trip the mobile clarify sheet (FTY-153) drives.

This page owns the read/answer **endpoint contract only**. It does not own:

- the log-event data model or the **event status state machine** — the full
  `LogEventStatus` vocabulary, including `needs_clarification` and
  `partially_resolved` and the transitions between them, stays defined in
  `log-events.md` (see its [State machine](log-events.md#state-machine)
  section);
- the parse step's production of clarification questions and the
  `clarification_questions` persistence shape (`parse-candidates.md`);
- the answer-triggered re-estimate's job/run mechanics (`estimation-jobs.md`).

## Owner

backend-core / contracts lane (`backend/app/routers/log_events.py` — both
endpoints; `backend/app/services/log_events.py` — the read,
`list_clarification_questions`; `backend/app/services/clarification.py` — the
answer/resolve, `answer_clarification_question`; `backend/app/schemas/log_events.py`,
`backend/alembic/`).

## Version

1 (FTY-282): relocates the clarify-loop endpoint contract out of
`log-events.md` into its own page — a **verbatim move, no semantic change**.
The read/answer shapes, status gating, idempotency, and privacy rules are
unchanged from `log-events.md`'s prior versions 3 (FTY-152, adds the read), 4
(FTY-170, the `{ id, text, options }` read shape plus the answer/resolve
endpoint), and 6 (FTY-278, item-scoped-question notes, no shape change). See
`log-events.md`'s Version history for the full semantic history of these
endpoints prior to this relocation.

## Inputs

All requests carry `Authorization: Bearer <token>` and target the
authenticated user's own `{user_id}`.

- `GET /api/users/{user_id}/log-events/{event_id}/clarification` — returns the
  **unanswered** clarification questions persisted for one of the user's
  `needs_clarification` or `partially_resolved` events — question text plus
  quick-pick options — ordered by `position`. The read is **status-gated**: an
  event in any other status serves `{ "questions": [] }`. A lazy per-event read
  the client fetches when opening the clarify sheet, so the Today list/poll DTO
  stays lean. See [Clarification read](#clarification-read).
- `POST /api/users/{user_id}/log-events/{event_id}/clarification/answers` —
  `{ "question_id": UUID, "answer": str }`. Resolves one clarification
  question on the user's own `needs_clarification` or `partially_resolved`
  event by applying the answer as a structured detail to the **same** event
  and re-estimating it. See
  [Clarification answer (resolve)](#clarification-answer-resolve).

## Outputs

### Clarification read

`GET /api/users/{user_id}/log-events/{event_id}/clarification` exposes the
clarification questions the estimator persisted for an event (the parse step
writes one `clarification_questions` row per question when the input is
genuinely indeterminate; this endpoint reads them back to the owning client).
It is the data the mobile clarify sheet (FTY-153) needs to render Slacks'
actual question with tappable quick-pick chips and a free-text fallback
(`docs/design/ux-design.md` §4a) instead of a generic line over a bare text
field.

The response carries a `needs_clarification` or `partially_resolved` event's
**unanswered** questions, ordered by `position` (the read is **status-gated** —
see below). Each
question carries its persisted row's stable `id` (the key an answer submission
references), the specific question `text`, and an `options` array of candidate
quick-pick values — the **unchanged FTY-170 shape**. An **item-scoped** question
(FTY-278) is **not** a new read field: it is an ordinary question whose `text`
names the specific unresolved component (by its sanitized food `name`), while
the producer-side item link stays internal
(`clarification_questions.derived_food_item_id`, `parse-candidates.md`) and is
**never surfaced in this read**:

```json
{
  "questions": [
    {
      "id": "b9c1…",
      "text": "How much milk?",
      "options": ["a splash", "1/2 cup", "1 cup"]
    }
  ]
}
```

- **An item-scoped question reuses the FTY-170 read shape unchanged (FTY-278).**
  It carries **no extra field** — the client renders `text` + `options` exactly
  as for any other question. The specific `unresolved` component it clarifies is
  identified **server-side** by the internal
  `clarification_questions.derived_food_item_id` link (`parse-candidates.md`,
  which the answer-triggered re-estimate uses to re-cost only that component) and
  named to the user through the question `text` (the component's sanitized food
  `name`). The read never surfaces that link and the `text` never contains the
  raw diary phrase. Under the FTY-275 baseline no question is item-scoped, so
  every question is event-level with no component link.

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
   for an item-scoped one (both legal in `log-events.md`'s state machine) — and
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
answered question is item-scoped (the event is `partially_resolved`), the answer
supplies the missing portion for **that one component**; the re-estimate re-costs
**only that open component** and must not re-ask for, re-cost, re-create, or
duplicate the siblings already resolved in an earlier round. The already-`resolved`
siblings are **left untouched** — their rows, committed values, and evidence stay
exactly as first committed; only the newly-answered component's own row is
advanced **in place** from `unresolved` to `resolved` (or, if the enriched input
is still indeterminate, the event stays `partially_resolved` with a fresh
item-scoped question while the siblings stay resolved untouched). Because `intake`
sums the event's `resolved` items and the siblings are never re-created, a
component resolved in an earlier round can never be **double-counted** or spawn a
**duplicate** row (the job/run mechanics are `estimation-jobs.md` v3; the counting
rule is `daily-summary.md`).
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
account via the cascades. Answered questions and their answers are **kept** when a
fresh round replaces the unanswered rows — they carry the accumulated details the
re-estimate consumes. Because an item-scoped question's `derived_food_item_id` is
`ON DELETE SET NULL` (`parse-candidates.md` v5), not `CASCADE`, an answered
question is never cascade-deleted with its `question_id` answer anchor: the
answered component's row is advanced **in place** (not deleted), and were a
referenced derived-item row ever removed the link is simply nulled — detaching the
question rather than destroying the accumulated detail.

**A resolve is a re-estimate, not an edit.** The answer supplies a missing
detail and the estimator recomputes the entry from the enriched input; the
result carries estimator provenance and the item is not marked user-edited.
Deterministically overriding a derived item's value or portion afterwards is
the separate corrections path (`corrections.md`) — the two levers must not be
conflated.

## Validation, Authorization, Privacy, and Errors

Shared across every `log-events` endpoint, including this sub-API — the
question/answer field validation, object-level authorization and fail-closed
scoping, privacy/retention rules for question and answer text, and the shared
error table — stay defined once in `log-events.md`: see its
[Validation](log-events.md#validation), [Authorization](log-events.md#authorization),
[Privacy and Retention](log-events.md#privacy-and-retention), and
[Errors](log-events.md#errors) sections.

## Examples

```sh
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

This page introduces no migration of its own — it is a docs-only relocation.
The `clarification_questions` and `clarification_answers` tables, and their
migrations (`0005`/FTY-042, `0016`/FTY-171, `0017`/FTY-172), remain owned and
documented by `log-events.md`'s and `parse-candidates.md`'s Migration /
Compatibility sections.
