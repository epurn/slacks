---
id: FTY-136
state: ready_with_notes
primary_lane: mobile-core
touched_lanes: []
review_focus:
  - behaviour-preserving-error-messages
  - names-preserved-aliases-and-subclasses
  - single-shared-primitives
  - api-tests-pass-unchanged
  - stays-inside-api-no-consumer-edits
risk: medium
tags:
  - mobile
  - refactor
  - api-client
  - dedup
  - dry
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-136: Consolidate the Duplicated Mobile API-Client Boilerplate (mobile)

## State

ready_with_notes

## Lane

mobile-core

## Dependencies

- **None to schedule.** Every referenced module is already merged on `main`. This
  is a pure internal refactor of the mobile `api/` clients. `approved_dependencies: []`.
- **Parallel-author note:** this story touches only `mobile/api/*`. FTY-133
  touches only `mobile/components/*`. Disjoint by path, so although both are
  `mobile-core` they can author in parallel without serializing.

## Outcome

The canonical authenticated-session type `ApiSession` already exists at
`mobile/state/session.tsx:48` and is consumed correctly by `api/corrections.ts`
and `api/labelCapture.ts`. The other session-scoped clients each **re-implement
the same boilerplate**:

1. **Seven modules redeclare a structurally identical session interface** —
   `{ readonly baseUrl; readonly token; readonly userId }` — under seven different
   names: `DailySummarySession`, `DerivedItemSession`, `GoalsSession`,
   `LogEventSession`, `ProfileSession`, `SavedFoodSession`, `WeightSession`
   (`api/dailySummary.ts`, `derivedItems.ts`, `goals.ts`, `logEvents.ts`,
   `profile.ts`, `savedFoods.ts`, `weightEntries.ts`).
2. **`authHeaders(session)` is duplicated verbatim in nine modules** —
   `corrections`, `dailySummary`, `derivedItems`, `goals`, `logEvents`, `profile`,
   `savedFoods`, `weightEntries`, plus the **special** `auth.ts` (whose variant is
   intentionally different — see below).
3. **Ten near-identical `class XxxApiError extends Error { status }` classes** —
   `AuthApiError`, `CorrectionsApiError`, `DailySummaryApiError`,
   `DerivedItemApiError`, `GoalsApiError`, `LabelUploadApiError`,
   `LogEventApiError`, `ProfileApiError`, `SavedFoodApiError`, `WeightApiError`.
4. **Per-file `readError` / `xxxBaseUrl` helpers** that each repeat the same
   user-scoped URL build (`${baseUrl}/api/users/${encodeURIComponent(userId)}/…`)
   and the same status→message switch shape (with per-endpoint message text).

This story introduces one shared `mobile/api/client.ts` and migrates the modules
onto it, eliminating the duplication while **preserving every observable
behaviour byte-for-byte** — most importantly, each endpoint's exact current error
message text and status mapping.

## Scope

- **Add `mobile/api/client.ts`** exposing the shared primitives:
  - **`ApiSession`** — re-exported from `@/state/session` as the single canonical
    session shape.
  - **`authHeaders(session)`** — one implementation returning the JSON header set
    used by the nine JSON endpoints: `{ Authorization: \`Bearer ${token}\`,
    'Content-Type': 'application/json', Accept: 'application/json' }`.
  - **`ApiError extends Error`** — the shared base carrying `readonly status:
    number` (and `message`). The ten existing classes become thin subclasses
    (`class GoalsApiError extends ApiError {}` etc.) that set their own `name`.
  - **`userScopedUrl(session, ...segments)`** — builds
    `${baseUrl}/api/users/${encodeURIComponent(userId)}` and appends the given
    path segments, preserving each module's exact current path and
    `encodeURIComponent` placement (e.g. corrections appends
    `derived-items/food/${encodeURIComponent(itemId)}`; goals appends `goal` /
    `target` / `target/override` / `target/override/reset`).
  - **`request<T>(url, opts)`** — one fetch wrapper: takes an injectable
    `fetchImpl` (default `fetch`), method, headers, optional body; on
    `response.ok` parses and returns `T`; on non-2xx builds the caller's named
    `ApiError` via a **caller-supplied error factory + status→message resolver**
    so the *exact* per-endpoint message text is preserved; never logs nutrition,
    credential, or body values.
- **Migrate the seven straggler modules** (`dailySummary`, `derivedItems`,
  `goals`, `logEvents`, `profile`, `savedFoods`, `weightEntries`): delete the
  local session interface and **re-export an alias** instead
  (`export type GoalsSession = ApiSession;` etc. — see Non-Goals on why aliases,
  not removal); delete the local `authHeaders` / `xxxBaseUrl` / `readError`; route
  calls through the shared `authHeaders` / `userScopedUrl` / `request`, passing
  each call's own status→message table.
- **Migrate `corrections.ts`** (already on `ApiSession`): drop its local
  `authHeaders` / `itemBaseUrl` / `readError`; use the shared primitives; keep its
  exact messages.
- **Rebase all ten error classes onto the shared `ApiError`** base (keep each
  class and its `name`).
- **Handle the two special modules explicitly:**
  - **`auth.ts`** — `login` / `register` are **pre-session** (no token yet); its
    `authHeaders()` takes no session and emits **no `Authorization` header**. Keep
    that no-Bearer header path; `auth.ts` shares only the `ApiError` base, not the
    authenticated `authHeaders`.
  - **`labelCapture.ts`** — uploads **multipart/form-data**; it must **not** set
    `Content-Type: application/json` (the `FormData` boundary is set by the
    runtime). Preserve its bespoke header construction; it shares only the
    `ApiError` base (and may reuse a tiny bearer-only helper at most). Do not push
    it onto the JSON `authHeaders`.

## Non-Goals

- **No behaviour change of any kind.** No endpoint, request shape, response shape,
  status code, URL, or contract changes. The migrated clients must produce
  byte-identical requests and identical thrown errors.
- **Do not change a single error message string or status mapping.** Each
  endpoint's current status→message text (e.g. goals' "Complete your profile
  before setting a goal." on 409) is the protected invariant; the shared
  `request()` carries it through unchanged.
- **Do not collapse the ten error classes into one.** ~12 production sites do
  `error instanceof XxxApiError` (`state/reachability.ts`, `app/day.tsx`,
  `components/SignInScreen.tsx`, `EditableItemRow.tsx`, `LogScreen.tsx`,
  `TodayScreen.tsx`, `WeightLogSheet.tsx`, `WeightScreen.tsx`, `TrendsScreen.tsx`,
  `CorrectionSheet.tsx`, `SettingsScreen.tsx`, `LabelCaptureScreen.tsx`) and the
  tests assert `name: "XxxApiError"` / `toBeInstanceOf(XxxApiError)`. Keep the
  named subclasses so all of these keep working **without edits**.
- **Do not remove the per-module `Session` type names.** They are imported by name
  in `components/TrendsScreen.tsx`, `components/TypeaheadSuggestionBar.tsx`, and
  `state/session.tsx` (+ tests). Keep them as `= ApiSession` aliases so those
  imports resolve unchanged.
- **Do not edit any `components/*` or `state/*` file, or any `api/*.test.ts`
  assertion.** The whole refactor stays inside `mobile/api/` non-test source; the
  unchanged consumer files and unchanged test suites are the proof of behaviour
  preservation.
- **Do not alter `auth.ts`'s pre-session header path or `labelCapture.ts`'s
  multipart upload semantics.**
- Leave non-session-scoped helpers (`serverConnection.ts`, `config.ts`) alone —
  they are not authenticated user-scoped clients.

## Contracts

- **None.** This is a client-internal refactor; no `docs/contracts/*` file is
  touched and no HTTP contract changes.

## Security / Privacy

- **None new.** No new surface, input, stored field, or network call. Positive
  effect: centralising `authHeaders`, the URL builder, and the error-mapping into
  one `client.ts` removes the latent risk of a future auth-header or
  error-redaction fix landing in one of nine copies and silently missing the
  others. The existing privacy property — **errors carry only HTTP status + an
  action label, never nutrition, body-metric, or credential values** — must be
  preserved exactly (the goals/auth tests that assert a message does **not**
  contain a sensitive value stay green).

## Verified-Identical Note (read before implementing)

The audit confirmed the duplication against the real files:

- The seven straggler `*Session` interfaces are **structurally identical** to
  `ApiSession` (`{ readonly baseUrl; readonly token; readonly userId }`) — safe to
  alias to it.
- `authHeaders(session)` is **byte-identical** across the nine JSON modules
  (modulo quote style). **`auth.ts` is the exception** — no session arg, no
  `Authorization` header (pre-login). **`labelCapture.ts` is the other exception**
  — multipart, no JSON `Content-Type`. These two are *legitimate divergences*, not
  duplication; fence them off (share only the `ApiError` base).
- Each module's `readError` shares the same **switch shape** but has **per-endpoint
  message text**. Only the shape is duplicated; the text is intentional and must
  be preserved — so the shared `request()` consolidates the *mechanism* (fetch →
  ok? → parse / throw) while each caller passes its own message table.

If implementation reveals any divergence not listed here, **stop and flag it**
rather than silently picking one — but none is expected.

## Acceptance Criteria

- `mobile/api/client.ts` exists and exports: the canonical `ApiSession`
  (re-export), one `authHeaders`, one `ApiError` base (carrying `status`), one
  `userScopedUrl`, and one `request()` wrapper.
- The seven straggler modules no longer declare their own session interface (they
  alias `ApiSession`), and no module except `auth.ts` / `labelCapture.ts` defines
  its own `authHeaders`; no module keeps a local `xxxBaseUrl` / `readError` copy.
- All ten `XxxApiError` classes extend the shared `ApiError` and keep their own
  `name`; `instanceof XxxApiError` **and** `instanceof ApiError` both hold.
- Every endpoint's exact status→message text, status code, URL string, and
  `encodeURIComponent` placement are unchanged; `auth.ts` stays no-Bearer;
  `labelCapture.ts` stays multipart.
- **All existing `api/*.test.ts` suites pass with zero assertion edits**, and **no
  `components/*` / `state/*` file is modified** — the two together prove the
  refactor is behaviour- and boundary-preserving.
- No contract, schema, or migration is touched.
- `make verify` (mobile: `npm run typecheck && npm run lint && npm test`) passes.

## Verification

- Run the mobile verify path: `cd mobile && npm run typecheck && npm run lint &&
  npm test` (i.e. `mobile/verify.sh` / root `make verify`).
- **Existing `api/*.test.ts` stay green with zero assertion changes** — the primary
  proof the consolidation is behaviour-preserving (the suites already assert the
  exact messages, statuses, `name`s, and `instanceof` relationships).
- **A `git diff --stat` shows changes confined to `mobile/api/` non-test source
  (+ the new `client.ts`/`client.test.ts`)** — no `components/*`, `state/*`, or
  test-assertion edits — the proof the refactor stayed inside its boundary.
- **New `api/client.test.ts`:** `authHeaders(session)` returns the exact JSON
  header set; `ApiError` carries `status` and a subclass preserves its `name` and
  satisfies `instanceof` both the subclass and the base; `request()` returns the
  parsed body on a 2xx and throws the **caller-supplied** named `ApiError` with the
  **caller-supplied** message on a non-2xx; `userScopedUrl` encodes `userId` and
  appends segments verbatim.
- **A `grep` proving no straggler module still defines its own `authHeaders` /
  `readError` / `*BaseUrl`** (single source of truth), and that `auth.ts` /
  `labelCapture.ts` retain their special header paths.

## Planning Notes

- **Pulled into v1 by a clean-break decision.** The roadmap recorded this dedup as
  a deliberate **post-v1 follow-up** ("mobile API-client boilerplate dedup is a
  post-v1 follow-up", Release-Audit note). It is now being pulled into v1: there
  are no users, and the clean-break principle favours killing this debt before the
  tag rather than shipping nine copies of the auth/URL/error boilerplate.
- **Large but mechanical** → `ready_with_notes`. Roughly ten modules change, but
  every change is a mechanical lift onto shared primitives. The single real risk is
  **preserving each endpoint's exact current error messages and status mapping**;
  the design (per-call message table funneled through one `request()`) plus the
  unchanged test suites as the safety net mirror FTY-120's "existing tests green,
  zero assertion edits" model.
- **Name preservation is the technique that keeps this one boundary.** Aliasing the
  `*Session` types and subclassing the `*ApiError` classes (instead of collapsing
  them) is what lets the ~12 `instanceof` consumer sites and every test compile and
  pass **unchanged** — which is exactly what keeps every edit inside `mobile/api/`
  and out of `components/*`/`state/*` (so it stays a single path-set, parallel-safe
  with FTY-133). Collapsing to one class would bleed edits into `components/*` and
  break the "tests unchanged" invariant — explicitly rejected in Non-Goals.
- **Two legitimate special cases, not duplication:** `auth.ts` (pre-session, no
  Bearer) and `labelCapture.ts` (multipart, no JSON `Content-Type`). They share
  only the `ApiError` base. Forcing either onto the JSON `authHeaders` would be a
  behaviour change.
- **Lint/quote style:** the modules currently mix single- and double-quote styles;
  the new `client.ts` and the migrated modules must satisfy the repo's
  lint/prettier config (run `npm run lint`).
- **No evidence research warranted:** a pure internal refactor with no health,
  nutrition, or behavioural decision — the evidence-backed-by-default rule does not
  apply.

## Readiness Sanity Pass

- **Product decision gaps:** none. The design (shared primitives + name
  preservation + fenced special cases) is fully specified; no open product
  question. `ready_with_notes` because the notes (clean-break pull-in, the
  name-preservation rationale, the two special cases) are non-blocking context an
  author should read.
- **Cross-lane impact:** primary `mobile-core`, **no touched lanes**. **Single
  boundary, zero big rocks:** no public contract change (client-internal only), no
  schema migration / new table, no new untrusted-input trust boundary. The
  name-preservation technique keeps all edits inside `mobile/api/` — one path-set.
- **Size:** `review_focus` = 5 (at the ceiling, not over); `requires_context` = 2
  (well under 8). Large by file count but mechanical, single-boundary, and not
  over either threshold → one story, no split. (Were it to require editing the ~12
  `instanceof` consumer sites, it would cross into `components/*` and warrant a
  split — the name-preservation design specifically avoids that.)
- **Parallel safety:** disjoint path-set from FTY-133 (`components/*`) — both
  `mobile-core` but safe to author concurrently.
- **Security/privacy risk:** low — no new surface; preserves the
  "errors carry status + action only" redaction property and *reduces* drift risk
  by centralising auth headers and error mapping.
- **Verification path:** `make verify` + `api/*.test.ts` unchanged + a diff-scope
  check (no consumer/test edits) + new `client.test.ts`.
- **Assumptions safe for autonomy:** yes — behaviour-preserving with the shared
  primitives, name-preservation rule, exact-message invariant, and the two special
  cases all pinned, plus the unchanged test suites and diff-scope check as the
  net, and a "stop and flag any unlisted divergence" escape hatch. No migration,
  no contract, no consumer edits.
</content>
