---
id: FTY-141
state: ready
primary_lane: backend-core
touched_lanes: []
review_focus:
  - snapshot-stability
  - drift-fails-the-test
  - documented-regeneration
risk: low
tags:
  - testing
  - openapi
  - contracts
  - drift-guard
approved_dependencies: []
requires_context:
  - docs/architecture/repo-layout.md
  - docs/standards/testing-standards.md
  - docs/contracts/README.md
autonomous: true
---

# FTY-141: OpenAPI Contract Snapshot Test (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. Adds a new test file + fixture only; no existing source is
  edited. The FastAPI app and all routers are already merged (`app/main.py`
  `create_app`, the eleven included routers).
- No file overlap with FTY-127 or FTY-140 (both edit services/contracts/docs, not
  the test suite), so this runs fully in parallel within the backend-core lane.

## Outcome

There is **no artifact guarding drift between the server's actual OpenAPI surface
and the `docs/contracts/*` specs.** The human-readable contracts describe each
endpoint's shape, but nothing fails when a code change silently alters the
generated schema (a renamed field, a changed status, a dropped/added route, a
loosened type) without a corresponding contract review. The `docs/contracts/`
README explicitly calls HTTP APIs and DTOs out as contract-governed boundaries,
yet the generated surface is currently unguarded. Add a **snapshot test** that
asserts the app's generated OpenAPI schema against a **checked-in JSON snapshot**,
failing CI on any unreviewed drift, with a **documented one-command regeneration**
so an intentional change is a deliberate, reviewable diff.

## Scope

- Add a checked-in snapshot fixture of the canonical OpenAPI schema, e.g.
  `backend/tests/snapshots/openapi.json`, generated from `create_app(...).openapi()`
  (using the same test `Settings(environment="test")` the suite already uses, so
  the schema is enabled and deterministic — note `openapi_url` is `None` only in
  `production`, but `app.openapi()` builds the dict regardless of environment).
- Add a test, e.g. `backend/tests/test_openapi_snapshot.py`, that builds the app's
  current schema and asserts **deep equality** against the checked-in snapshot,
  failing with a clear message that points at the regeneration command when they
  diverge.
- Provide a **documented regeneration command** for an intentional change. Prefer a
  **test-only, env-guarded self-update** (no new product/script wiring): when an
  env var is set (e.g. `UPDATE_OPENAPI_SNAPSHOT=1`) the test rewrites the fixture
  instead of asserting; document the exact command in the test module docstring
  (e.g. `UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi_snapshot.py`).
  This keeps the change entirely under `tests/` and needs no change to `verify.sh`,
  the Makefile, or `app/`.
- Ensure the snapshot is **stable/deterministic**: serialize with sorted keys and a
  fixed indent so a regeneration produces a minimal, reviewable diff and key
  ordering never causes a spurious failure.

## Non-Goals

- **No change to the API, routers, schemas, or `app/main.py`.** This is a
  test + fixture addition only.
- **Do not auto-generate or rewrite `docs/contracts/*`.** The snapshot guards the
  *machine* surface; the human contracts stay authored. (The test's value is that a
  contract review is *forced* when the snapshot diff appears.)
- **Do not add a new third-party dependency.** Use the already-available FastAPI
  `app.openapi()` and the stdlib `json` module; the existing `TestClient`/app
  fixtures are sufficient.
- **Do not edit `testing-standards.md`** unless the repo convention clearly expects
  a new test category to be registered there — prefer test-only. (Contract/DTO
  snapshot testing already falls under the standards' existing "Contract tests for
  DTOs … and estimator tools" bullet.)
- **No production behaviour change** — the production `openapi_url=None` gating
  (FTY-112) is untouched; the test builds the schema in-process via `app.openapi()`.

## Contracts

- **None changed.** This story *protects* the existing `docs/contracts/*` surface;
  it introduces no new contract and modifies none.

## Security / Privacy

- **None new.** The snapshot is the public API schema (paths, shapes, status
  codes) the app already serves in non-production; it contains no secrets, tokens,
  personal data, or machine paths. The test runs in-process against the test app
  and makes no external egress. Verify the committed fixture carries no environment-
  specific or sensitive values before checking it in.

## Acceptance Criteria

- A checked-in `backend/tests/snapshots/openapi.json` (or equivalent) holds the
  canonical generated schema, serialized deterministically (sorted keys, fixed
  indent).
- `test_openapi_snapshot.py` builds the current `app.openapi()` and **fails** when
  it differs from the snapshot, with a message naming the regeneration command.
- The documented regeneration command (env-guarded self-update) rewrites the
  fixture and is described in the test module docstring; running it on an unchanged
  app produces **no diff** (idempotent).
- The test **passes** on the current `main` surface (the committed snapshot matches
  today's schema).
- A deliberate local edit to a router/DTO causes the test to **fail** (drift is
  caught) — exercised manually or noted as the demonstrated behaviour.
- `make verify` passes (the new test is collected by the existing pytest run via
  `verify.sh`).

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`. The snapshot test is
  picked up by the existing pytest invocation — no `verify.sh` change.
- **New test:** equality of `create_app(Settings(environment="test")).openapi()`
  against the committed snapshot; the failure message references the regeneration
  command.
- **Idempotence check:** running the regeneration command on the unchanged app
  yields no fixture diff (deterministic serialization).
- **Drift check (manual, noted in the PR):** a throwaway field/status change makes
  the test fail, proving it guards drift.

## Planning Notes

- **Why a snapshot vs per-endpoint assertions.** A single whole-schema snapshot
  catches *any* surface change — added/removed route, renamed field, changed status
  or type — in one cheap guard, and makes the change show up as a reviewable diff
  rather than requiring a hand-written assertion per endpoint. The cost is a
  regeneration step on intentional changes, which the documented one-command update
  makes trivial.
- **Why the env-guarded self-update over a separate dumper script.** It keeps the
  entire change under `tests/`, needs no new `app/` module, `scripts/` entry, or
  `verify.sh`/Makefile wiring, and co-locates the regeneration logic with the
  assertion so they can never drift apart. A standalone `scripts/dump_openapi.py`
  is a fine alternative if the reviewer prefers it, but it adds wiring this story
  deliberately avoids.
- **Determinism is load-bearing.** FastAPI's schema dict can have incidental key
  ordering; serialize with `sort_keys=True` and a fixed indent so the test never
  fails on ordering and regeneration diffs stay minimal.
- No health/nutrition/behavioural decision is involved, so no evidence research is
  warranted.

## Readiness Sanity Pass

- **Product decision gaps:** none — fixture location, regeneration mechanism, and
  determinism approach are all decided above (with a noted acceptable alternative).
- **Cross-lane impact:** primary backend-core, **no touched lanes.** **Single
  boundary, zero big rocks:** test + fixture only — no public contract change (it
  *guards* the contract), no schema migration / new table, no new untrusted-input
  trust boundary.
- **Size:** `review_focus` = 3, `requires_context` = 3 — one small story.
- **Security/privacy risk:** low — the snapshot is the already-served public schema
  with no secrets/PII; verify the committed fixture is clean. No external egress.
- **Verification path:** `make verify` (collects the new test) + equality,
  idempotence, and manual drift checks.
- **Assumptions safe for autonomy:** yes — additive test-only change, no source/
  migration/contract-shape/UI/provider involvement, deterministic and self-
  documenting regeneration.
</content>
