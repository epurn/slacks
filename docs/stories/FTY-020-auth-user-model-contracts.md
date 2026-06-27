---
id: FTY-020
state: merged
primary_lane: contracts
touched_lanes:
  - backend-core
  - security-privacy
  - infra
risk: high
tags:
  - auth
  - migrations
  - contracts
  - privacy
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/README.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
review_focus:
  - object-level-authz
  - migration-rollback
  - secret-hygiene
  - identity-user-separation
autonomous: true
---

# FTY-020: Auth And User Model Contracts

## State

ready_with_notes

## Lane

contracts

## Dependencies

- FTY-012

## Outcome

The canonical identity and profile data model exists, backed by the first Alembic migration, with a minimal secure local-dev authentication path so later stories can operate against a real authenticated, owned user.

## Scope

- Introduce Alembic (deferred from FTY-012) and a baseline migration creating `users`, `auth_identities`, and `user_profiles`, with `auth_identities` kept separate from `users` per the security baseline.
- Define Pydantic boundary DTOs and contract docs (using the contract template) for the user, auth identity, and profile records.
- Implement a minimal secure local self-host auth path: email + password with a strong password hash (e.g. argon2/bcrypt) and a session/token mechanism. This satisfies the "self-hosted auth must support a secure local path" baseline requirement.
- Provide a profile read/write API that persists profile fields and enforces object-level authorization (a user can only read/write their own profile).
- Store canonical units (kilograms, meters); display units are a user preference captured on the profile, not a storage unit.
- Profile fields persisted: height, weight, birth year (or age), metabolic formula preference (see FTY-021 framing), units preference, and timezone.

## Non-Goals

- Sign in with Apple / hosted auth (deferred to a later hosted-auth story).
- Mobile profile capture UI (FTY-021).
- Target/RMR/TDEE/goal calculator and the `goals` / `daily_targets` tables (FTY-022).
- Log events, estimator, saved foods, or any non-identity tables.
- Password reset, email verification, MFA, and account recovery flows.

## Contracts

- `users`, `auth_identities`, `user_profiles` table schemas and the baseline migration become the foundational persistence contract.
- The profile DTO and the profile read/write API request/response shapes become contracts consumed by FTY-021 (mobile) and FTY-022 (calculator).
- Auth identity is modeled separately from the user record; the local-auth session/token shape is a contract.

## Security / Privacy

This story handles sensitive personal data (body metrics) and authentication. Requirements: `auth_identities` separate from `users`; object-level authorization enforced on every profile access path with negative authorization tests proving it fails closed; password hashes never logged; no secrets or tokens in logs; secrets read from environment only. Retention follows the data-retention doc (profile retained until edited or account deletion). Rated high risk: touches auth, migrations, contracts, and privacy.

## Acceptance Criteria

- The baseline migration applies cleanly and has a documented rollback.
- `users`, `auth_identities`, `user_profiles` exist with user-ownership foreign keys at the persistence boundary.
- A user can register and log in via the local-dev auth path; passwords are stored only as strong hashes.
- Profile read/write API enforces object-level authorization; a negative test proves cross-user access fails closed.
- Profile DTOs are schema-validated; invalid input is rejected with a clear error shape.
- Canonical units (kg, m) are stored; unit preference is captured separately.
- `make verify` passes, including auth and migration tests.

## Verification

- Run `make verify` (unit + integration + migration tests).
- Apply and roll back the migration in a test database.
- Run the negative authorization test proving cross-user profile access is denied.

## Planning Notes

- This is a deliberately combined slice (contracts + migrations + local auth) per the product decision. If the implementation PR grows too large, the local email/password auth path is the clean split point and can be carved into a follow-up story; the data model + migrations + DTO contracts should land first regardless.
- Sign in with Apple is explicitly out and will be its own hosted-auth story.
- `goals` and `daily_targets` are intentionally left to FTY-022 so the calculator owns its own contracts.

## Readiness Sanity Pass

- Product decision gaps: none blocking — auth scope (local now, Apple later), identity/user separation, and stored units are resolved.
- Cross-lane impact: foundational; backend persistence + auth + profile API consumed by mobile (FTY-021) and estimator (FTY-022).
- Security/privacy risk: high; auth + body data. Mitigated by identity/user separation, hashed passwords, object-level authz with negative tests, and retention adherence.
- Verification path: `make verify` + migration apply/rollback + negative authz test.
- Assumptions safe for autonomy: yes; scope and security requirements are explicit. Carries notes (Apple deferral, possible local-auth split) hence ready_with_notes.
