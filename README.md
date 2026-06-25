# Fatty

Fatty is an iOS-first, open source calorie and macro tracker for people who hate traditional tracking. Users describe what they ate or did in natural language, and Fatty turns that into structured, editable food and exercise entries with evidence and assumptions.

The product principle is simple: natural input, deterministic math, visible evidence, easy correction.

## Current Status

This repository is in early foundation work. It now has public governance,
security/privacy requirements, contracts, review gates, and a minimal monorepo
scaffold before application behavior is added.

## Product Shape

- iOS-first Expo app
- FastAPI backend
- Postgres, Redis, Celery
- Docker Compose self-hosting
- async estimation jobs
- calories and macros only
- MET-based exercise estimates in v1
- nutrition label photo, barcode, text quick-add, manual edits
- source/evidence icons instead of visible confidence ranges
- privacy and data minimization as core requirements

See `docs/architecture/system-overview.md` for the working architecture.

## Repository Layout

- `apps/backend`: future FastAPI backend package.
- `apps/mobile`: future iOS-first Expo / React Native app package.
- `packages/contracts`: future machine-readable contracts shared across
  backend, mobile, estimator, and infrastructure code.
- `docs/contracts`: public contract principles and human-readable contract
  templates.

## Development

Run the current repository checks:

```sh
make verify
```

More language-specific tooling will be added when the backend and mobile workspaces are scaffolded.

Package-specific verification should be exposed through a package `Makefile`
with a `verify` target. Root `make verify` delegates to those package checks
when they exist.

## Contributing

See `CONTRIBUTING.md`, `AGENTS.md`, and `docs/operations/branching-and-prs.md`.

## License

The project is intended to be open source. The license has not been selected yet.
