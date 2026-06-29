---
id: FTY-134
state: ready
primary_lane: backend-core
touched_lanes: []
review_focus:
  - helper-consolidation
  - no-behaviour-change
  - single-source-of-truth
  - leaky-private-import-removed
  - tz-dst-preserved
risk: low
tags:
  - refactor
  - timezone
  - daily-summary
  - targets
  - log-events
approved_dependencies: []
requires_context:
  - docs/architecture/repo-layout.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/contracts/daily-summary.md
  - docs/contracts/target-calculator.md
autonomous: true
---

# FTY-134: Consolidate the Remaining Day/Timezone Helpers FTY-120 Missed (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. This is a **pure refactor** over already-merged service code:
  FTY-120 created `app/timeutils.py` (the `user_timezone` / `day_bounds_utc` /
  `next_day` home) and the public `_resolve_active_target_row` query; this story
  finishes that consolidation across the call sites FTY-120 did not reach
  (`weight_entries`, `goals`, the five inline "today" patterns, and the leaky
  private import in `daily_summary`). Nothing blocks it.
- **Rebase note (no scheduling dep):** it edits `targets.py`, `daily_summary.py`,
  and `goals.py`, which overlap **FTY-127** (also backend-core, same files). The
  two serialize in the backend-core lane regardless; whichever merges first,
  **rebase this on whatever backend-core work merges first** to avoid a churn
  conflict. `approved_dependencies` stays empty — there is no behavioural
  dependency, only a file-overlap rebase.

## Outcome

FTY-120 left three copies of the day/timezone logic collapsed to one, but the
audit confirms three loose ends it did not reach. This story closes them so the
"what day is it in the user's timezone" and "active target row for a day" logic
each have a **single source of truth** with **no per-module copies and no leaky
cross-module private imports**. **Behaviour is unchanged** — this only removes
duplication and tightens module boundaries so a future timezone/DST correctness
fix can no longer land in one place and silently miss the others.

1. **`weight_entries._user_timezone` is a verbatim fourth copy of the shared
   resolver.** `app/services/weight_entries.py` (~198–209) defines a private
   `_user_timezone(session, owner_id) -> ZoneInfo` whose **own docstring admits**
   it "mirrors the same resolver used by daily_summary and targets" — i.e. it is a
   byte-for-byte duplicate of `app.timeutils.user_timezone`. FTY-120 centralised
   the other three; this copy escaped the sweep. Import the shared one and delete
   the copy.
2. **The `datetime.now(user_timezone(...)).date()` "today in the user's tz"
   pattern is open-coded at five call sites.** The exact two-line idiom — resolve
   the profile timezone, then take `datetime.now(tz).date()` — is repeated inline
   in `daily_summary.py` (~90–92), `goals.py` (~183–184), `log_events.py`
   (~160–162), `targets.py` `_resolve_day` (~329–330), and `weight_entries.py`
   `create_entry` (~106–107). "Today, in this user's calendar" is a single
   concept and deserves one helper.
3. **`daily_summary.py` reaches across a module boundary for a private name.**
   `daily_summary.py:54` imports `_resolve_active_target_row` (leading underscore
   = module-private by convention) from `targets.py`. FTY-120 deliberately
   consolidated the active-target *query* into one resolver, but left it named
   private while a second module depends on it — a leaky private import that lint
   and readers both flag. Promote it to a public `resolve_active_target_row`.

## Scope

- **Delete the duplicate timezone resolver in `weight_entries.py`.** Remove the
  private `_user_timezone` (~198–209), import `user_timezone` from
  `app.timeutils`, and call it at the one use site (`create_entry`, ~106). Drop
  the now-unused `from zoneinfo import ZoneInfo` import.
- **Add one `current_day` helper to `app/timeutils.py` and route all five sites
  through it.** Add:
  - `current_day(session: Session, owner_id: uuid.UUID) -> date` returning
    `datetime.now(user_timezone(session, owner_id)).date()` — the existing idiom,
    defined once, reusing the already-centralised `user_timezone`.
  - Replace the inline pattern at all five call sites with a `current_day(...)`
    call:
    - `weight_entries.create_entry` (~106–107) — the `today` used for the
      effective-date upper bound (FTY-119).
    - `goals._resolve_day` (~183–184) — the today default when `for_date` is
      omitted; the `for_date is not None` early-return is preserved exactly.
    - `targets._resolve_day` (~329–330) — same today default + `for_date`
      passthrough, preserved exactly.
    - `daily_summary.get_daily_summary` (~90–92) and `log_events` list-by-day
      (~160–162) — the today default when `day` is omitted. **See the
      Accepted-Micro-Divergence note below:** these two also need `tz` locally for
      `day_bounds_utc`, so calling `current_day` re-resolves the timezone once on
      the `day is None` path. This is an explicit, documented choice (identical
      output, one extra indexed lookup only when the caller omits the day) in
      exchange for a single "today" source.
- **Promote the leaky private resolver to public.** Rename
  `targets._resolve_active_target_row` → `resolve_active_target_row` (no leading
  underscore). Update its internal caller `targets._resolve_active_target` and the
  `daily_summary.py:54` import. No signature, query, or not-found-policy change —
  `targets` still raises `TargetNotFound`, `daily_summary` still returns `None`
  and projects the read-model.
- **Remove any import left unused by the edits** (ruff enforces this; e.g. the
  dropped `ZoneInfo` in `weight_entries`).
- **Add focused unit tests** for `current_day` (see Verification).

## Non-Goals

- **No behaviour change.** No new validation, endpoint/router change, contract
  change, or migration. The consolidated path produces identical results to the
  prior per-module code.
- **Do not change DST / timezone semantics.** The UTC fallback, the half-open
  `[start, end)` window, and the `ZoneInfo(tz_name or "UTC")` default are
  preserved exactly — they already live in `timeutils` and are not touched.
- **Do not change the two active-target callers' not-found policies.** The
  raise-vs-`None` divergence FTY-120 documented is load-bearing; this story only
  renames the shared query, it does not collapse the policies.
- **Do not change the timezone-resolution semantics of the five "today" sites.**
  Same zone, same UTC fallback, same `.date()` — only the call shape changes.
- Touch no module beyond `weight_entries.py`, `goals.py`, `targets.py`,
  `daily_summary.py`, `log_events.py`, and `timeutils.py` (plus their tests).

## Contracts

- **None.** `docs/contracts/daily-summary.md` and
  `docs/contracts/target-calculator.md` are referenced for the day-default and
  active-target behaviour the refactor must preserve, but are **not modified** —
  the observable contract is unchanged by construction.

## Security / Privacy

- **None new.** No new surface, input, or stored field. Positive effect:
  centralising the timezone resolver and the "today" idiom removes the latent risk
  of a future tz/DST correctness fix landing in only one of (now) five copies — a
  class of silent drift across the weight-date bound, the Today timeline, the
  daily summary, goals, and target lookups. Weight and target values remain
  sensitive personal data and are never logged; this refactor adds no log lines.

## Verified-Identical Note (read before implementing)

The audit confirmed the duplicated blocks against the real files:

- `weight_entries._user_timezone` (~198–209) is **logic-identical** to
  `app.timeutils.user_timezone` — same `select(UserProfile.timezone)` +
  `ZoneInfo(tz_name or "UTC")` fallback; only the docstring wording differs (and
  it self-documents that it mirrors the shared resolver). Safe to delete and
  import.
- The five `datetime.now(user_timezone(...)).date()` sites are the **same idiom**;
  `goals._resolve_day` and `targets._resolve_day` wrap it with the **identical**
  `for_date is not None` early-return, which must be preserved verbatim.
- `_resolve_active_target_row` is already the single consolidated query (FTY-120);
  this is a **rename only** — no query or policy change.

**Accepted micro-divergence (the one intentional, output-preserving change):** at
`daily_summary.get_daily_summary` and the `log_events` list-by-day path, `tz` is
resolved locally because it is also passed to `day_bounds_utc(day, tz)`. Routing
the today-default through `current_day(session, owner_id)` re-resolves the profile
timezone a second time **only on the `day is None` path**. The resulting `day`
value is identical; the cost is one extra indexed `UserProfile.timezone` lookup
when the caller omits the day. This is chosen deliberately to keep a single
"today" source rather than re-inlining the idiom at two sites. It is the **only**
divergence introduced.

If implementation reveals any further divergence not listed here, **stop and flag
it** rather than silently picking one — but none is expected.

## Acceptance Criteria

- `weight_entries.py` no longer defines `_user_timezone`; it imports and calls
  `app.timeutils.user_timezone`, and the unused `ZoneInfo` import is gone.
- `app/timeutils.py` defines `current_day(session, owner_id) -> date`, and all
  five previously-inline sites (`weight_entries.create_entry`, `goals._resolve_day`,
  `targets._resolve_day`, `daily_summary.get_daily_summary`, `log_events`
  list-by-day) call it. No `datetime.now(user_timezone(...)).date()` idiom remains
  open-coded in those services.
- `targets.resolve_active_target_row` is public (no leading underscore); both its
  internal caller and the `daily_summary` import reference the public name. No
  module imports an underscore-private name from another module.
- The two active-target callers keep their existing not-found policy (`None` vs
  `TargetNotFound`) and return shape (read-model vs raw `DailyTarget`); the
  `for_date`/`day` early-returns in `goals` and `targets` are unchanged.
- **All existing `weight_entries`, `goals`, `targets`, `daily_summary`, and
  `log_events` service tests pass with zero assertion edits** — same days,
  windows, DST behaviour, target lookups, and date-bound rejections as before.
- No router, schema, contract, or migration is touched.
- `make verify` passes (ruff check + ruff format --check + mypy + pytest).

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh`, i.e. root
  `make verify`.
- **Existing service tests stay green with no assertion changes** — the primary
  proof the consolidation is behaviour-preserving across the five modules,
  including the FTY-119 future-date rejection in `weight_entries` (which depends on
  the resolved "today") and the goal/target `for_date` defaults.
- **New focused unit tests for `current_day`:** returns today in the owner's
  profile timezone; falls back to UTC when the profile has no timezone; and a
  user whose local "today" differs from UTC "today" (e.g. a far-east or far-west
  zone near midnight) gets the local calendar day, not the UTC one — locking in the
  preserved semantics.
- **New focused unit test (or reuse) proving the public rename is wired:**
  `daily_summary._resolve_target` and `targets._resolve_active_target` both
  resolve through `resolve_active_target_row` and still map a missing row to their
  respective policies (`None` vs `TargetNotFound`).

## Planning Notes

- **Home for `current_day`:** `app/timeutils.py`, which already owns
  `user_timezone` / `day_bounds_utc` / `next_day` (FTY-120) and mirrors the repo's
  flat `app/` layout in `docs/architecture/repo-layout.md`. No new module.
- **The accepted micro-divergence is the one real judgment call** and is decided
  above: prefer a single `current_day` source over avoiding a second cheap indexed
  lookup on the day-omitted path; the output is identical. If the author judges the
  extra lookup unacceptable at one of the two sites, the safe fallback is to keep
  `tz` local there and derive the day from it — but the default decision is to use
  `current_day` at all five for one source of truth. Note whichever was chosen.
- **Public vs private names:** the active-target query crosses a module boundary,
  so it must be public (no underscore) — matching how FTY-120 made the time-window
  helpers public on extraction.
- **Why this is safe to automate:** every change is mechanical (delete-and-import,
  extract-and-call, rename), the divergences are fenced, and the existing service
  tests staying green is the safety net.

## Readiness Sanity Pass

- **Product decision gaps:** none. The one judgment call (the day-omitted-path
  micro-divergence) is decided above. No health, nutrition, or behavioural question
  is involved, so no evidence research is warranted.
- **Cross-lane impact:** primary backend-core, **no touched lanes** — pure
  internal refactor, no contract or security surface. **Single boundary, zero big
  rocks:** no public contract change, no schema migration / new table, no new
  untrusted-input trust boundary. All edits are in the one serializing backend-core
  lane; the `targets.py`/`daily_summary.py`/`goals.py` overlap with FTY-127 is a
  same-lane rebase, not a second boundary.
- **Size:** `review_focus` = 5 (at the ceiling, not over); `requires_context` = 5
  (under 8). One story — it is a single, mechanical follow-up to FTY-120 with no
  new public contract, migration, or trust boundary, so it does not breach the
  split rule.
- **Security/privacy risk:** low — no new input, stored field, or endpoint, and no
  new log lines; the refactor *reduces* latent tz/DST-fix drift. It touches five
  correctness-critical service modules, so the existing tests staying green (no
  assertion edits) is the required safety net.
- **Verification path:** `make verify` + existing service tests unchanged + new
  `current_day` unit tests (incl. a near-midnight cross-zone case) + the
  public-rename wiring test.
- **Assumptions safe for autonomy:** yes — behaviour-preserving consolidation with
  the verified-identical blocks confirmed against the real files, the single
  intentional micro-divergence explicitly fenced and justified, and a rebase note
  for the FTY-127 file overlap.
