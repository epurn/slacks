# backend

The Fatty backend package area (FastAPI, Python).

## Owns

- The FastAPI application, settings, and request/response boundary models.
- Service-layer domain behavior (deterministic calorie, macro, and target math).
- Database access, migrations, and background job entrypoints (added in later stories).
- Provider adapters for evidence retrieval and LLM estimation (added in later stories).

This directory is an intentionally empty scaffold. The first backend code arrives
in **FTY-012: Backend App Skeleton**.

## Root verification

A package opts into root `make verify` by adding an executable `verify.sh` at the
package root. Until that script exists, the package is skipped cleanly so the
scaffold verifies from a fresh checkout. See
[`docs/architecture/repo-layout.md`](../docs/architecture/repo-layout.md).
