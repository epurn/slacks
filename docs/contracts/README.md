# Contracts

Contracts define boundaries before implementation details leak across systems.
Human-readable contract guidance lives here. Machine-readable schemas and
generated contract artifacts belong in `packages/contracts` once specific
contracts are introduced.

Use contracts for:

- HTTP APIs,
- mobile/backend DTOs,
- database tables and migrations,
- Celery job payloads,
- estimator tool inputs and outputs,
- LLM structured outputs,
- provider adapters,
- source evidence records,
- memory writes,
- event status state machines.

## Contract Template

```md
# Contract: <Name>

## Purpose

## Owner

## Version

## Inputs

## Outputs

## Validation

## Authorization

## Privacy and Retention

## Errors

## Examples

## Migration / Compatibility
```

## Current Contract Principles

- Store canonical units: kcal, grams, milliliters, seconds, meters, kilograms.
- Display units are user preferences, not storage units.
- LLM output is never trusted until schema-validated.
- User-owned data must carry user ownership at the persistence boundary.
- Global source facts must not contain user-specific habits.
