# Fatty

Fatty is an iOS-first, open source calorie and macro tracker for people who hate traditional tracking. Users describe what they ate or did in natural language, and Fatty turns that into structured, editable food and exercise entries with evidence and assumptions.

The product principle is simple: natural input, deterministic math, visible evidence, easy correction.

## Current Status

This repository is in Milestone 0: project operating system. The first checked-in work establishes agent guidance, development standards, security/privacy requirements, contracts, and review gates before application code is added.

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

## Development

The monorepo is laid out as `backend/` (FastAPI), `mobile/` (Expo / React
Native), and `contracts/` (shared contract code), with documentation in `docs/`.
See `docs/architecture/repo-layout.md` for the layout and verification contract.

Run the current repository checks:

```sh
make verify
```

`make verify` is the single entry point: it runs repository governance and then
each package's verification hook. Packages are scaffolded empty for now, so their
checks are skipped until a package adds an executable `verify.sh`. Language-specific
tooling arrives with the backend and mobile skeleton stories.

Bring up the full local backend stack (Postgres, Redis, the FastAPI API, and a
Celery worker) over plain HTTP with Docker Compose:

```sh
cp .env.example .env
docker compose up
```

See `docs/operations/local-dev-stack.md` for the service contract and details.

## Contributing

See `CONTRIBUTING.md`, `AGENTS.md`, and `docs/operations/branching-and-prs.md`.

## License

The project is intended to be open source. The license has not been selected yet.

