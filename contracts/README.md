# contracts

Shared contract code consumed across the backend and mobile packages.

## Owns

- Language-shared contract definitions (for example JSON Schema or generated
  types) for HTTP DTOs, LLM structured outputs, job payloads, and estimator tool
  inputs/outputs.
- The single source of truth that keeps backend and mobile boundary types in
  sync.

This is the *code* home for contracts. The human-readable contract specs,
principles, and template live in
[`docs/contracts/`](../docs/contracts/README.md); this package holds the machine
artifacts those specs describe.

This directory is an intentionally empty scaffold. Concrete shared contracts are
added by the stories that introduce them (for example
**FTY-040: Evidence Retrieval Contract**).

## Root verification

A package opts into root `make verify` by adding an executable `verify.sh` at the
package root. Until that script exists, the package is skipped cleanly so the
scaffold verifies from a fresh checkout. See
[`docs/architecture/repo-layout.md`](../docs/architecture/repo-layout.md).
