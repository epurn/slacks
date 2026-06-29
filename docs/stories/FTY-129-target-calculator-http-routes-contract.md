---
id: FTY-129
state: ready
primary_lane: contracts
touched_lanes: []
review_focus:
  - all-three-routes-documented
  - paths-params-verified-against-router
  - status-codes-match-implementation
  - request-response-shapes-correct
  - style-matches-daily-summary
risk: low
tags:
  - docs
  - contracts
  - targets
approved_dependencies: []
requires_context:
  - docs/contracts/target-calculator.md
  - docs/contracts/daily-summary.md
  - docs/contracts/goals-target-reveal.md
autonomous: true
---

# FTY-129: Document The Target Endpoints' HTTP Routes In `target-calculator.md`

## State

ready

## Lane

contracts

## Dependencies

- None to schedule. The three endpoints are **already merged** (FTY-095);
  this documents the shipped surface. Authors in parallel with FTY-128
  (`CHANGELOG.md`), FTY-130 (`threat-model.md`), and FTY-142 (`README.md` /
  `contracts/README.md` / `system-overview.md`) — those touch different files.
  (FTY-142 edits `contracts/README.md`, a different file.)
- **Rebase note (cross-lane same-file):** **FTY-127** (backend-core) also edits
  `docs/contracts/target-calculator.md` — it adds a note that the override
  set/reset endpoints **materialise** an in-horizon day's row on demand and
  rewords the 404 Errors row. This story adds the **HTTP route block** to the same
  file. Different sections, no semantic overlap, but the same physical file across
  two lanes (the steward serializes by path *within* a lane, not across), so
  whichever merges first, the second must **rebase on it**. When this story writes
  the Errors row for the override/reset routes, keep it consistent with FTY-127's
  "no active goal covering the day → 404" wording.

## Outcome

`target-calculator.md` documents the **HTTP route surface** for the three
shipped target endpoints, closing the one gap among the HTTP-bearing contracts:
`daily-summary.md`, `goals-target-reveal.md`, and `log-events.md` each carry an
explicit route block, but `target-calculator.md` documents only the persistence
schema, the calculator I/O, and the override/reset *semantics* — never the
path/method/params/status-codes of the routes that expose them. A self-hoster or
client author reading the contract can't currently see how to call the override
surface; after this story they can.

The three routes to document, owner-scoped over the active goal's target row
(verified against `backend/app/routers/targets.py`, prefix `/api/users`):

1. `GET    /api/users/{user_id}/target` — read the derived-vs-overridden
   read-model (`get_target`, ~line 48).
2. `PUT    /api/users/{user_id}/target/override` — set a calorie and/or macro
   override (`set_override`, ~line 70).
3. `POST   /api/users/{user_id}/target/override/reset` — clear override(s) back
   to derived (`reset_override`, ~line 98).

## Scope

- **Edit only `docs/contracts/target-calculator.md`.** Add an **HTTP routes**
  block documenting the three endpoints, matching the style of
  `daily-summary.md`'s request/response blocks (fenced request lines with the
  `Authorization: Bearer <token>` header, a per-route description, and an
  errors/status mapping). The natural home is alongside the existing
  **"Manual override + reset, with provenance (FTY-095)"** section (the route
  block makes that section's semantics callable) or as a new top-level
  **HTTP routes** section above **Validation** — author's discretion.
- **For all three routes document:** the method + path; that `{user_id}` is the
  authenticated user's own id (object-level ownership checked on every access);
  the optional **`day`** query param (`YYYY-MM-DD`, **defaults to today in the
  user's profile timezone**, malformed → `422`); `200 OK` with `TargetReadModel`
  on success.
- **Request bodies:**
  - `PUT …/target/override` takes **`TargetOverrideRequest`** — optional
    `calorie_target_kcal` (int ≥ 1), `protein_target_g` / `carbs_target_g` /
    `fat_target_g` (int ≥ 0); at least one must be present; `extra="forbid"`.
  - `POST …/target/override/reset` takes **`TargetResetRequest`** — optional
    `targets` (list of the overridable-target names); `null`/empty resets **all**
    in-force overrides; idempotent.
  - `GET` takes no body.
- **Response:** all three return **`TargetReadModel`** — per target (`calories`,
  `protein_g`, `carbs_g`, `fat_g`) a `{ effective, derived, source }` component.
  Cross-reference the existing read-model description in the same file rather
  than redefining the shape.
- **Status mapping** (verify against the router + schemas before writing):
  - `200` — success (all three).
  - `404` — cross-user access **or** no active goal / no stored target for the
    day (`GoalForbidden` / `TargetNotFound` → fail closed, **no existence
    oracle**; both map to the same `target not found`).
  - `422` — malformed `day`; an **out-of-band override** (`OverrideOutOfBand`,
    `PUT` only — rejected, not clamped, nothing persisted); an **empty override
    body** (no calorie or macro provided).
  - `401` — missing/invalid bearer token (the standard authenticated-surface
    code; confirm against `CurrentUser`).
- **Verify exact paths, the `day` param default, the request/response model
  names, and every status code against `backend/app/routers/targets.py` and
  `backend/app/schemas/targets.py` before finalising the acceptance** — the
  contract must match the code, not this spec's paraphrase.

## Non-Goals

- **No code change.** Documentation only — the routes already ship; nothing in
  `backend/` is touched.
- **No version bump of the contract beyond what the new route block needs.** The
  routes shipped under the FTY-095 work the existing Version line (3) already
  names; adding the route documentation does not change behaviour, so do not
  invent a new feature version. (If the contract convention requires noting the
  documentation addition, a one-line note is fine — but no semantic version
  change.)
- **Do not redefine** the persistence schema, the calculator math, the macro
  derivation, the override/reset semantics, or the read-model shape — they are
  already documented in this file; the route block **references** them.
- **Do not touch** `daily-summary.md`, `goals-target-reveal.md`, or any other
  contract — they are referenced for style only.
- No mobile/client documentation.

## Contracts

- **This story is itself a contract-doc edit** to `target-calculator.md`. It
  documents an **already-shipped** HTTP surface; the observable behaviour is
  unchanged (the routes exist and behave as documented today). No request/
  response shape is altered — this records what the router already does.

## Security / Privacy

- Docs-only, **public repo**. Documenting the routes makes the fail-closed
  posture **more** auditable: the route block states the owner-scoping, the
  `404`-no-oracle discipline, the reject-don't-clamp `422` on out-of-band
  overrides, and that target numbers are sensitive derived body data never
  logged (already asserted in the router docstring and the file's Privacy
  section). No new surface, input, or stored field. Rated **low**.

## Acceptance Criteria

- `target-calculator.md` contains an HTTP route block documenting all three
  endpoints with method, path, the `day` query param (default = today in profile
  tz; malformed → `422`), request body model (`TargetOverrideRequest` /
  `TargetResetRequest` / none), and `200` response (`TargetReadModel`).
- The documented status mapping matches the implementation: `200` success;
  `404` cross-user / no-active-target (fail closed, no oracle); `422` malformed
  `day`, out-of-band override, empty override body; `401` missing/invalid token.
- The block's style matches `daily-summary.md`'s request/response/errors blocks.
- The route documentation is verified against `backend/app/routers/targets.py`
  and `backend/app/schemas/targets.py` — exact paths, param, model names, and
  status codes.
- No `backend/` code, no other contract file, and no version-source file is
  touched.
- `make verify` passes (governance boundary + docs checks).

## Verification

- `make verify` (governance boundary + docs/link checks).
- Manual diff confirming each route's path/method/param/body/response/status
  matches `routers/targets.py` + `schemas/targets.py`, and that the style
  mirrors `daily-summary.md`.

## Planning Notes

- **One judgment call — placement.** Either fold the route block into the
  existing FTY-095 override/reset section or add a dedicated HTTP-routes section
  above Validation; both are acceptable. The route block is the only addition.
- **Authoritative source is the code**, not this spec: the author reads
  `routers/targets.py` (paths `~:48/70/98`, the shared `_DAY_QUERY`, the
  `GoalForbidden`/`TargetNotFound`→404 and `OverrideOutOfBand`→422 handlers) and
  `schemas/targets.py` (`TargetOverrideRequest` ge-bounds + at-least-one
  validator, `TargetResetRequest.targets`, `TargetReadModel`) and documents what
  is actually there.
- **No evidence research warranted** — this records a shipped HTTP surface; it
  settles no health/nutrition/behavioural question.

## Readiness Sanity Pass

- **Product decision gaps:** none — the routes are shipped; this documents them.
  Placement is the only discretionary call.
- **Cross-lane impact:** contracts (docs) only, **no touched lanes**. **Single
  boundary, zero big rocks:** no schema migration, no new table, no new trust
  boundary, and no *change* to a public contract — it documents an existing one.
  Owns `target-calculator.md` exclusively — no overlap with FTY-128/130/142.
- **Size:** `review_focus` = 5 (at ceiling), `requires_context` = 3 (under 8).
  One story.
- **Security/privacy risk:** low — public-repo docs; documenting the routes
  improves auditability of the existing fail-closed posture; no new surface.
- **Verification path:** `make verify` + a code-cross-checked read-through diff.
- **Assumptions safe for autonomy:** yes — the three routes, their params,
  bodies, responses, and status codes are enumerated, and the author is directed
  to verify each against the merged router/schemas before finalising.
