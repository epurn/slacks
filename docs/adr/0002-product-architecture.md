# ADR 0002: Initial Product Architecture

## Status

Accepted.

## Context

Fatty needs to support natural language food and exercise logging, async estimation, self-hosting, iOS-first UX, and strict privacy/security boundaries.

## Decision

Use:

- Expo / React Native for iOS-first mobile,
- FastAPI for backend APIs,
- Postgres for persistence,
- Redis and Celery for async estimation jobs,
- Docker Compose for self-hosting,
- provider-configurable LLM integration inspired by Pi's provider model,
- constrained estimator pipeline rather than a user-visible open-ended agent.

The LLM is used for parsing, extraction, source ranking, and structured assumptions. Backend services own validation, deterministic math, storage, auth, and memory mutation.

## Consequences

- Slow estimation does not block mobile requests.
- Polling is enough for v1 pending-entry updates.
- Self-hosters can provide OpenAI, Anthropic, or OpenAI-compatible endpoints.
- The estimator can be agentic inside narrow tool boundaries without gaining broad personal or system access.

