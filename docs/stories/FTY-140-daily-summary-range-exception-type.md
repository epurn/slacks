---
id: FTY-140
state: ready
primary_lane: backend-core
touched_lanes: []
review_focus:
  - distinct-exception-for-ordering
  - status-code-unchanged
  - contract-error-wording
risk: low
tags:
  - daily-summary
  - error-semantics
  - cleanup
approved_dependencies: []
requires_context:
  - docs/contracts/daily-summary.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-140: Distinct Exception Type For The Daily-Summary Range Ordering Error (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. Pure cleanup over already-merged FTY-123 range-read code
  (`app/services/daily_summary.py`, `app/routers/daily_summary.py`).
- **Rebase note:** **FTY-127** also edits `daily_summary.py` (read-path
  carry-forward in `_resolve_target` / `_resolve_targets_by_day`). This story edits
  a different function (`get_daily_summaries`'s validation) and the module's
  exception classes, so there is no semantic overlap, but both touch the same file
  — whichever merges first, the second should **rebase on it**.

## Outcome

`get_daily_summaries` (`daily_summary.py` ~132–133) raises
`DailySummaryRangeTooLarge("'from' must be on or before 'to'")` for the
`start > end` **ordering** error. That is a **span/size error type reused for an
ordering error** — the message and class name say "too large" for what is actually
"out of order". The HTTP behaviour is correct (both still render `422` via the
router), but the type/message semantics are wrong, which makes the code misleading
to read and makes a precise test (or a future caller that branches on the
exception) impossible. Introduce a **distinct exception for the ordering case** so
each failure mode has an honest type, with no change to the observable `422`.

## Scope

- Add a new exception class in `daily_summary.py`, e.g.
  `DailySummaryInvalidRange(Exception)` (docstring: raised when `from` is after
  `to` — an ordering error, distinct from the span-too-large case), and keep
  `DailySummaryRangeTooLarge` exclusively for the **span exceeds
  `MAX_RANGE_DAYS`** case.
- In `get_daily_summaries`, raise `DailySummaryInvalidRange` for the `start > end`
  branch (with a clear ordering message); keep raising `DailySummaryRangeTooLarge`
  for the span check.
- In `routers/daily_summary.py`, map the new exception to the **same `422`** as
  `DailySummaryRangeTooLarge` (add it to the existing `except` for the range
  endpoint — either a shared `except (DailySummaryRangeTooLarge,
  DailySummaryInvalidRange)` or a second handler, both → 422 with `detail=str(exc)`).
- Update `docs/contracts/daily-summary.md` only if it conflates the two reasons.
  The Errors table currently lists them together ("`from` after `to`, or span
  exceeding 366 days" → `422`); split the wording so the two distinct reasons read
  as the two distinct (still-`422`) failure modes they now are. No status-code or
  request/response shape change.

## Non-Goals

- **No status-code change.** Both the ordering and span errors stay `422`. This is
  a type/message correction, not a behaviour change.
- **No change to the single-day endpoint, the range read math, or the DTO shape.**
- **Do not touch the carry-forward / materialisation logic** — that is FTY-127.
- **Do not rename `DailySummaryRangeTooLarge`** or change its span semantics; it
  keeps owning the span-too-large case exactly.

## Contracts

- **`docs/contracts/daily-summary.md`** — at most a wording refinement in the
  Errors table to name the ordering vs span reasons separately. No version bump is
  required (both remain `422`, no shape/behaviour change); add one if the repo
  convention expects a doc edit to bump it.

## Security / Privacy

- **None new.** No new input, surface, stored field, or external egress. The
  fail-closed `422` for a bad range is preserved exactly; this only gives the
  ordering failure its own honest type.

## Acceptance Criteria

- `daily_summary.py` defines a distinct `DailySummaryInvalidRange` (or equivalent)
  for the `start > end` case; `DailySummaryRangeTooLarge` is raised **only** for
  the span-too-large case.
- The range endpoint returns `422` for **both** an inverted range and an
  over-`MAX_RANGE_DAYS` span (unchanged observable behaviour), each with a clear,
  reason-appropriate `detail` message.
- A test asserts the ordering case raises the new type (service level) and returns
  `422` (router level), and the span case raises `DailySummaryRangeTooLarge` and
  returns `422` — proving the two failure modes are now distinct types mapping to
  the same status.
- The contract's Errors wording (if it conflated the two) distinguishes them.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **New / extended service test:** `get_daily_summaries` with `start > end` raises
  `DailySummaryInvalidRange`; with a span > `MAX_RANGE_DAYS` raises
  `DailySummaryRangeTooLarge` (two distinct types).
- **New / extended API test (`test_daily_summary_api`):** the range endpoint
  returns `422` for an inverted `from`/`to` and for an over-cap span, each with the
  expected message — confirming both still render `422`.
- **Regression:** the existing FTY-123 range tests stay green.

## Planning Notes

- **Minimal-surface change.** The fix is one new exception class, one changed
  `raise`, one router `except` line, and a doc wording tweak — deliberately small.
  The HTTP contract is untouched precisely so this cannot regress a client.
- **Why bother if behaviour is unchanged:** an exception type reused across two
  unrelated failure modes is a latent trap — a future caller (or a precise test)
  that branches on `DailySummaryRangeTooLarge` would silently catch ordering
  errors too. Giving each failure its own type is the cheap, correct fix while the
  surface is still pre-v1 with no external consumers.
- No health/nutrition/behavioural decision is involved, so no evidence research is
  warranted.

## Readiness Sanity Pass

- **Product decision gaps:** none — the only choice (new type name + shared vs
  separate router handler) is decided above and either handler form is acceptable.
- **Cross-lane impact:** primary backend-core, **no touched lanes.** **Single
  boundary, zero big rocks:** no public contract *behaviour* change (status codes
  unchanged; only error-reason wording), no schema migration / new table, no new
  untrusted-input trust boundary.
- **Size:** `review_focus` = 3, `requires_context` = 3 — comfortably one small
  story.
- **Security/privacy risk:** low — no new input or surface; the fail-closed `422`
  is preserved.
- **Verification path:** `make verify` + a service test distinguishing the two
  exception types + an API test confirming both still return `422`.
- **Assumptions safe for autonomy:** yes — fully specified, observable behaviour
  unchanged, no migration / contract-shape / UI / provider involvement.
</content>
