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

Run the current repository checks:

```sh
make verify
```

More language-specific tooling will be added when the backend and mobile workspaces are scaffolded.

## Contributing

See `CONTRIBUTING.md`, `AGENTS.md`, and `docs/operations/branching-and-prs.md`.

## License

The project is intended to be open source. The license has not been selected yet.

