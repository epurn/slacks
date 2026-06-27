---
id: FTY-010
state: merged
primary_lane: contracts
touched_lanes:
  - backend-core
  - mobile-core
  - infra
risk: low
tags:
  - scaffold
  - tooling
  - contracts
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - scope-control
  - verify-command
  - dependency-hygiene
autonomous: true
---

# FTY-010: Monorepo Scaffold

## State

ready_with_notes

## Lane

contracts

## Dependencies

- FTY-000

## Outcome

Fatty has a minimal monorepo skeleton that can host the backend, mobile app, shared contracts, and root verification commands without committing to product behavior too early.

## Scope

- Create package directories for backend, mobile, and shared contract code.
- Add root commands that delegate to package checks when package tooling exists.
- Add lightweight placeholder contract documentation or package metadata where needed.
- Keep scaffold decisions documented enough for the next backend, mobile, and infra stories.

## Non-Goals

- Implement FastAPI routes beyond package-level placeholders.
- Implement the Expo UI shell.
- Add Docker Compose services.
- Add auth, persistence, estimator jobs, or external providers.
- Choose final hosted deployment infrastructure.

## Contracts

- Root repository layout becomes the contract for subsequent stories.
- Root `make verify` must remain the verification entry point.
- Package-specific tooling should plug into root verification when introduced.

## Security / Privacy

No user data should be stored or processed in this story. The scaffold must not include secrets, real credentials, or example private data.

## Acceptance Criteria

- Backend, mobile, and shared-contract areas exist in predictable paths.
- Root verification still works from a fresh checkout.
- Placeholder files explain what each package owns.
- Follow-up stories can add backend, mobile, infra, and estimator behavior without reorganizing the repo.

## Verification

- Run `make verify`.

## Planning Notes

- Exact package manager and backend/mobile toolchain details may be finalized in the implementation PR if the choice is standard and reversible.
- New third-party packages are not approved for this story unless the story metadata is updated in a planning PR first.

## Readiness Sanity Pass

- Product decision gaps: none for repository layout.
- Cross-lane impact: creates placeholders for backend, mobile, and infra without implementing behavior.
- Security/privacy risk: low; no user data, credentials, or runtime services.
- Verification path: `make verify`.
- Assumptions safe for autonomy: yes; package choices must remain minimal and reversible.
