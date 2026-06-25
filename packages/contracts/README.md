# Shared Contracts

This package is the future home for machine-readable contracts shared by the
backend, mobile app, estimator, and infrastructure checks.

## Ownership

- Path: `packages/contracts`
- Story: FTY-010 monorepo scaffold
- Owns DTO schemas, API request/response shapes, job payload schemas, estimator
  structured-output schemas, and generated contract artifacts once those stories
  add behavior.

## Current State

No generated clients, package manager metadata, runtime validators, or user data
live here yet. Public contract principles and templates remain in
`docs/contracts` until specific versioned contracts are introduced.

## Verification

Root `make verify` will call this package automatically after a package
`Makefile` with a `verify` target is introduced. Until then, the root scaffold
check validates that this ownership boundary exists.

## Security And Privacy

Future schemas must validate untrusted LLM output, API input, and job payloads
before backend code stores or acts on them. Contracts must document retention and
authorization expectations for user-owned data.
