# Contract: Identity and Profile

## Purpose

Define the canonical identity and profile data model and the minimal local
authentication path, so later stories operate against a real authenticated,
owned user. This contract covers three things:

1. the persistence schema (`users`, `auth_identities`, `user_profiles`) and its
   baseline migration;
2. the local email+password auth path (register / login) and the bearer-token
   shape it issues;
3. the profile read/write API and its object-level authorization rule.

It deliberately excludes hosted auth (Sign in with Apple), the
target/RMR/goal calculator and its tables (FTY-022), and the mobile profile
capture UI (FTY-021).

## Owner

backend-core / contracts lane (`backend/app/models/`, `backend/app/security/`,
`backend/app/services/`, `backend/app/routers/`, `backend/alembic/`).

## Version

1 (introduced in FTY-020).

## Inputs

### Persistence

`Base.metadata` (SQLAlchemy) defines the schema; Alembic owns the migrations.
The baseline migration (`0001`) creates:

- **`users`** — canonical account row. Columns: `id` (UUID, PK), `created_at`,
  `updated_at`. Holds identity, never credentials.
- **`auth_identities`** — authentication credentials, kept separate from
  `users`. Columns: `id` (UUID, PK), `user_id` (UUID, FK → `users.id`,
  `ON DELETE CASCADE`), `provider` (string, `local` in v1), `identifier`
  (string; the login email, stored lower-cased), `password_hash` (string,
  nullable), `created_at`, `updated_at`. Unique on `(provider, identifier)`.
- **`user_profiles`** — body metrics and display preferences. Columns: `id`
  (UUID, PK), `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`, unique),
  `height_m` (float, nullable), `weight_kg` (float, nullable), `birth_year`
  (int, nullable), `metabolic_formula` (string), `units_preference` (string),
  `timezone` (string), `created_at`, `updated_at`.

Canonical units only: `height_m` in metres, `weight_kg` in kilograms.
`units_preference` is a display choice and never changes what is stored.

### HTTP requests

- `POST /api/auth/register` — `{ "email": str, "password": str }`. Password
  8–128 chars. Creates the user, a `local` auth identity, and an empty profile.
- `POST /api/auth/login` — `{ "email": str, "password": str }`.
- `GET /api/users/{user_id}/profile` — bearer token required.
- `PUT /api/users/{user_id}/profile` — bearer token required. Body is a partial
  update; only provided fields are written:
  `{ height_m?, weight_kg?, birth_year?, metabolic_formula?, units_preference?, timezone? }`.

Authenticated requests carry `Authorization: Bearer <token>`.

## Outputs

- **Register** → `201` `{ "user": { "id": UUID, "created_at": datetime },
  "token": { "access_token": str, "token_type": "bearer", "expires_in": int } }`.
- **Login** → `200` `{ "access_token": str, "token_type": "bearer",
  "expires_in": int }`.
- **Profile read/write** → `200` `{ "user_id": UUID, "height_m": float|null,
  "weight_kg": float|null, "birth_year": int|null, "metabolic_formula": str,
  "units_preference": "metric"|"imperial", "timezone": str,
  "updated_at": datetime }`.

The bearer token is an HMAC-SHA256-signed claim
`{"sub": <user id>, "iat", "exp"}`, encoded `<payload_b64url>.<signature_b64url>`.
It is stateless (no server-side session table in v1). A password hash is never
part of any response.

## Validation

- Email: normalized (trimmed, lower-cased) and shape-checked at the boundary.
- Password: 8–128 characters; carried as a secret value, never logged or echoed.
- `height_m` ∈ (0, 3], `weight_kg` ∈ (0, 1000], `birth_year` ∈ [1900, 2100].
- `metabolic_formula` ∈ {`mifflin_st_jeor`}; `units_preference` ∈
  {`metric`, `imperial`}; `timezone` must be a known IANA name.
- Invalid input is rejected with `422` and a field-level error shape; unknown
  body keys are rejected.

## Authorization

- Authentication: every profile request must present a valid, unexpired bearer
  token; otherwise `401`.
- Object-level authorization: a user may read or write **only their own**
  profile. `{user_id}` must equal the authenticated user's id. A mismatch fails
  closed as `404` (no existence oracle for other users' profiles). This is
  covered by negative authorization tests for both read and write.

## Privacy and Retention

- Sensitive personal data: body metrics (height, weight, birth year) and
  authentication credentials.
- Password hashes are strong (scrypt, salted, self-describing) and live only in
  `auth_identities`; they are never logged or returned.
- The token signing secret (`FATTY_AUTH_SECRET`) is read from the environment
  only and never logged; a production app refuses to start on the dev default.
- Retention (per `docs/security/data-retention.md`): account data retained until
  account deletion; profile data retained until edited or account deletion.
  `ON DELETE CASCADE` on `user_id` removes a user's identities and profile when
  the account is deleted.

## Errors

| Status | When |
| --- | --- |
| `401` | Login with unknown email or wrong password (same generic error); missing/invalid/expired bearer token. |
| `404` | Accessing a profile the caller does not own (fail closed). |
| `409` | Registering an email that already has a local identity. |
| `422` | Malformed body, invalid email, weak password, out-of-range metric, unknown timezone, unknown field. |

Login returns the same `401` for an unknown email and a wrong password so the
API does not reveal whether an account exists.

## Examples

Register, then read your profile:

```sh
curl -sX POST :8000/api/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"a-good-password"}'
# → 201 { "user": {...}, "token": { "access_token": "<t>", "token_type": "bearer", "expires_in": 604800 } }

curl -s :8000/api/users/<user_id>/profile -H 'authorization: Bearer <t>'
# → 200 { "user_id": "...", "height_m": null, ..., "units_preference": "metric", "timezone": "UTC" }
```

## Migration / Compatibility

- The baseline migration applies cleanly (`alembic upgrade head`) and is fully
  reversible (`alembic downgrade base`), verified by a migration apply/rollback
  test against a throwaway database.
- This is the first migration; there is no prior schema to be compatible with.
- Future changes (e.g. hosted-auth providers) add new `auth_identities` rows
  against the same `users` record and ship as new migrations; consumers
  (FTY-021 mobile, FTY-022 calculator) depend on the profile DTO and the table
  ownership keys defined here.
