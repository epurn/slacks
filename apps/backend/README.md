# Backend

This package is the future home for Fatty's FastAPI backend.

## Ownership

- Path: `apps/backend`
- Story: FTY-010 monorepo scaffold
- Owns API handlers, backend services, deterministic calculators, persistence
  adapters, job enqueueing boundaries, and backend tests once those stories add
  behavior.

## Current State

No runtime services, FastAPI routes, database models, provider integrations, or
user data live here yet. This placeholder exists so backend stories can add
typed Python code without reorganizing the repository.

## Verification

Root `make verify` will call this package automatically after a package
`Makefile` with a `verify` target is introduced. Until then, the root scaffold
check validates that this ownership boundary exists.

## Security And Privacy

Future backend code must validate untrusted inputs at API and job boundaries,
avoid logging sensitive nutrition or body data, and keep secrets outside the
repository.
