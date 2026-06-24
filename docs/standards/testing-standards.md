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

