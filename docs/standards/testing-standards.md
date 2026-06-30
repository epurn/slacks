# Testing Standards

Tests are part of the feature, not a follow-up.

## Test Types

- Unit tests for calculators, parsers, validators, and pure domain behavior.
- Integration tests for API, database, auth, jobs, provider adapters, and migrations.
- Contract tests for DTOs, LLM schemas, job payloads, and estimator tools.
- Security tests for access control, SSRF defenses, prompt injection, file upload constraints, logging, and memory isolation.
- Mobile tests for navigation logic, state transitions, editing flows, and accessibility-critical components.

## Data

- Use synthetic fixtures.
- Do not use real user logs, real body data, real tokens, or copied private nutrition history.
- If realistic nutrition examples are needed, use public official facts and cite/store source metadata.

## Required Coverage By Change Type

- Calculator change: exact examples, unit conversions, invalid inputs, boundary values.
- API change: request validation, auth failure, success, and error shape.
- Database change: migration test and rollback note.
- Estimator change: structured output validation, adversarial input, failed provider path.
- Privacy/security change: negative test proving the control fails closed.

## Migrations Run Against Postgres Too

Migrations apply by default against a throwaway SQLite database (fast, no
service). SQLite is permissive, though, and silently tolerates DDL that the
deploy target (Postgres) rejects — e.g. a `BOOLEAN` column with an integer
server default (`BOOLEAN DEFAULT 0`). An SQLite-only gate gives false
confidence, so DB-touching code is also exercised against the production
datastore:

- Set **`FATTY_TEST_DATABASE_URL`** to a Postgres URL (e.g. the Compose `db`
  service) and the Postgres migration guard (`tests/test_postgres_migration.py`)
  runs the full chain — `upgrade head` → `downgrade base` → `upgrade head` —
  against it via the `pg_engine` fixture in `tests/conftest.py`.
- When the var is unset the guard **skips cleanly**, so a fresh checkout and the
  default `make verify` stay green with no Postgres dependency. CI supplies a
  real Postgres and exports the var so the guard is enforced on every PR.

