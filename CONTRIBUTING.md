# Contributing

Fatty is built with security, privacy, consistency, and review as first-order requirements.

## Workflow

1. Start from a story, bug, contract, ADR, or security note.
2. Create a branch:
   - `story/<id>-<slug>`
   - `fix/<id>-<slug>`
   - `security/<id>-<slug>`
   - `chore/<slug>`
3. Keep changes scoped to one behavior or one foundation.
4. Update contracts, docs, tests, and migrations with the code they describe.
5. Run `make verify`.
6. Open a PR using the template.
7. Wait for CI and a separate reviewer approval before merge.

## Standards

- Prefer clear, boring code over clever code.
- Reuse local helpers and established patterns.
- Add tests for new behavior and regressions.
- Keep API and data contracts explicit.
- Document security and privacy impact in every PR.
- Never commit secrets or real user data.

## Review

Authoring and reviewing are separate phases. A PR cannot be merged on self-review. See `docs/review-policy.md`.

