# Coding Standards

These standards apply before the repo has app code and become stricter as packages are added.

## General

- Keep changes scoped to the story or contract.
- Prefer explicit types and schemas at boundaries.
- Keep domain math deterministic and covered by tests.
- Use adapters for external providers.
- Do not mix unrelated refactors with behavior changes.
- Add comments only where they clarify non-obvious decisions.
- Document public modules, contracts, and security-sensitive behavior.

## Backend

- Python code must use typing and Pydantic boundary models.
- FastAPI route handlers should delegate behavior to services.
- Database access should be explicit and migration-backed.
- Background jobs should be idempotent and retry-aware.
- Provider integrations should have timeouts, retries, and sanitized logs.

## Mobile

- TypeScript strict mode is expected once the app is scaffolded.
- UI should be iOS-first, accessible, compact, and nonjudgmental.
- Natural language input should produce structured editable entries.
- Evidence/status should use icons with accessibility labels.

## Security

- Validate inputs at trust boundaries.
- Fail closed for authorization, tool permission, and model-output validation.
- Do not log secrets, tokens, raw prompts with unnecessary personal context, or private nutrition history.
- Keep user-specific memory isolated by user.

## Tooling Direction

When packages are scaffolded, add and enforce:

- formatter,
- linter,
- typechecker,
- unit tests,
- integration tests,
- dependency audit,
- secret scanning,
- security static analysis where useful.

