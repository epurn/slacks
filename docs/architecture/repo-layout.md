# Repository Layout

Slacks is a monorepo. This document is the layout contract that later backend,
mobile, infra, and contract stories build on. The goal of the FTY-010 scaffold
is predictable, empty package homes — not product behavior.

## Top-Level Packages

| Path | Owns | First implementing story |
| --- | --- | --- |
| `backend/` | FastAPI app, settings, services, jobs, migrations, provider adapters. | FTY-012 |
| `mobile/` | Expo / React Native iOS-first app shell and screens. | FTY-013 |
| `contracts/` | Shared contract code (DTOs, LLM schemas, job/estimator payloads) imported by backend and mobile. | FTY-040 and later |

Supporting top-level paths already in the repo:

- `docs/` — architecture, standards, security, operations, and the
  human-readable contract specs (`docs/contracts/`).
- `scripts/` — repository-level tooling (`verify-governance.py`,
  `package-verify.sh`).
- `Makefile` — the root verification entry point.

`docs/contracts/` holds the *specifications*; the `contracts/` package holds the
*machine artifacts* (schemas / generated types) those specs describe.

## Root Verification Contract

`make verify` is the single verification entry point for CI and local use. It
runs:

1. `governance` — `scripts/verify-governance.py`, the dependency-free public
   repository governance gate. It also runs `scripts/verify-code-shape.py`,
   which scans first-party source for new over-threshold files and backend /
   estimator boundary imports against the explicit
   `scripts/code-shape-baseline.json` baseline.
2. `packages` — each package's optional verify hook.

### How a package plugs into `make verify`

A package opts into root verification by adding an **executable `verify.sh` at
its package root**. `scripts/package-verify.sh <package>` runs that hook from the
package directory if it exists and is executable, and otherwise prints a skip
line and exits 0. This keeps a fresh checkout green before any package toolchain
is installed, while letting each later story wire real checks in without
changing the root contract.

A package `verify.sh` should run that package's own formatter, linter,
typechecker, and tests, and exit non-zero on failure.

Package hooks may skip only their dependency-install step when
`FATTY_VERIFY_SKIP_INSTALL` is set to a truthy value (`1`, `true`, `yes`, or
`on`, case-sensitive variants accepted by the hook). This signal is for
pre-provisioned author environments where locked dependencies are already
installed and network dependency installation is intentionally unavailable. The
signal is explicit opt-in only: hooks must not infer it from the presence or
absence of `node_modules`, `.venv`, or other local artifacts. With the signal
unset, package hooks must keep installing exactly what their lockfiles pin before
running checks so CI and fresh checkouts remain reproducible.

## Notes For Upcoming Stories

- **FTY-011 (infra / Docker Compose):** add compose and infra config at the repo
  root or under an `infra/` area; do not move the package directories.
- **FTY-012 (backend skeleton):** add the FastAPI app and a `backend/verify.sh`
  that runs backend type checks and tests.
- **FTY-013 (mobile skeleton):** add the Expo app and a `mobile/verify.sh` (or
  document why mobile checks are not yet wired) per the story's acceptance
  criteria.
- New third-party dependencies require a planning PR that updates the relevant
  story's `approved_dependencies` first.
