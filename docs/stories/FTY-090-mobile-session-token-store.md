---
id: FTY-090
state: ready
primary_lane: mobile-core
touched_lanes:
  - security-privacy
risk: high
tags:
  - mobile
  - auth
  - session
  - secure-store
  - token
  - self-host
approved_dependencies: []
requires_context:
  - docs/contracts/identity-and-profile.md
  - docs/design/ux-design.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/security/security-baseline.md
review_focus:
  - secure-token-storage
  - session-hydration-and-clear
  - server-url-binding
  - userid-from-token-claim
  - non-enumerating-auth-client
autonomous: true
---

# FTY-090: Mobile Session Token Store + Auth Client (Plumbing)

## State

ready

## Lane

mobile-core (+ security-privacy)

## Dependencies

- FTY-020 (backend auth path: `POST /api/auth/register`, `POST /api/auth/login`,
  the HMAC-SHA256 bearer-token shape, and the profile object-level auth rule this
  session feeds — already merged; consumed, not changed)
- FTY-013 (mobile app skeleton: the Expo/expo-router shell this plumbing lives in)
- FTY-021 (profile capture: the existing `useSession()`/`ProfileSession` consumer
  whose seam this completes — not changed beyond making `useSession()` real)
- **Not** dependent on FTY-097 (design system): this is non-visual plumbing — no
  screen, component, or token-styling. The screens that consume this surface
  (FTY-091) carry the design-system dependency, not this story.

## Outcome

The mobile app can **establish, persist, hydrate, and clear** a signed-in session
entirely in code, with no UI yet. Because Fatty is **self-host-first with no hosted
instance** (UX design §4d), a session is **bound to the user's own server**: the
unit that persists is `{ serverUrl, token, userId }`, not a token alone. A token
issued by one self-hosted server is meaningless against another, so the server URL
the user connected to is part of the session and is stored, hydrated, and cleared
atomically with the token. This is the secure plumbing the connect / sign-in /
create-account screens (FTY-091) sit on top of:

1. A typed **auth API client** that, given a **bound server base URL**, calls
   `POST {serverUrl}/api/auth/register` and `POST {serverUrl}/api/auth/login` and
   returns a normalized session `{ serverUrl, token, userId }`.
2. A **secure session store** (OS keychain via `expo-secure-store`) that persists
   the session record (bearer token + bound `serverUrl` + resolved `userId`) as one
   atomic value and can clear it.
3. `state/session.ts` `useSession()` becomes real: it **hydrates from the secure
   store on launch** and returns the stored `{ serverUrl, token, userId }` (or
   `null`), and a session controller exposes `signIn` / `createAccount` / `signOut`
   that the screens drive. The existing `ProfileScreen`/`profile.ts` consumer keeps
   working unchanged — once a session exists, profile persistence works with no edit
   to the form (the seam was built for exactly this in FTY-021), now addressing the
   bound server instead of static config.

After this story, a session set in code survives an app restart and a sign-out
clears it; FTY-091 adds the connect/sign-in screens and routing that drive it.

## Scope

- Add a typed, injectable **auth client** (mirror the `mobile/api/profile.ts`
  style: a thin `fetch` wrapper with an injected `fetchImpl`, errors carrying only
  HTTP status + action, never the request body or credentials). Each call takes the
  **bound server base URL** (the user's own server) as an explicit argument:
  - `createAccount(serverUrl, email, password)` → `POST {serverUrl}/api/auth/register`,
    reads `{ user: { id }, token: { access_token } }`, returns
    `{ serverUrl, token, userId }` with `userId = user.id`.
  - `signIn(serverUrl, email, password)` → `POST {serverUrl}/api/auth/login`, reads
    `{ access_token }`. **Login does not return the user id** — derive `userId` from
    the token's `sub` claim (see below).
  - Normalize the supplied `serverUrl` the same way `resolveApiBaseUrl()` does
    (trim, strip trailing slashes) before use and before it is stored, so the bound
    URL is canonical. Deep URL-format UX validation (scheme required, reachability,
    QR scan) is FTY-091's connect screen, not this story.
  - Map auth failures to plain, **non-enumerating** messages: `401` (unknown email
    OR wrong password — identical message, no account-existence oracle), `409`
    (email already registered — only meaningful on the register path), `422`
    (malformed email / weak password). No status maps to a message that reveals
    whether an account exists.
- **Derive `userId` from the bearer token.** The profile API is addressed by
  `{serverUrl}/api/users/{userId}/profile`, but `login` returns only the token. The
  token is `<payload_b64url>.<signature_b64url>` where the payload is
  `{ "sub": <user id>, "iat", "exp" }` (identity-and-profile contract). Decode the
  base64url payload and read `sub` for addressing only. Do **not** verify the
  signature or trust any claim for an authorization decision client-side — the
  server re-validates the token on every request and fails closed; `sub` is used
  purely to build the owner-scoped URL.
- Add a **secure session store** wrapper over `expo-secure-store` with
  `save(session)`, `load(): session | null`, and `clear()`. Persist the whole
  `{ serverUrl, token, userId }` record as **one atomic value** (a JSON string under
  a single key). The bearer token is a credential and must live in the OS
  keychain/keystore via `expo-secure-store` — **never** `AsyncStorage`, plain files,
  or app state alone, and never logged. Co-locating the (non-secret) `serverUrl` and
  `userId` in the same record is deliberate: it keeps the token and the server it is
  valid against from ever drifting out of sync across a torn read, and avoids a
  second storage key. Treat a missing/corrupt/partial stored record as "no session"
  (return `null`) — never hydrate a half session.
- Make `state/session.ts` real: `useSession()` hydrates from the secure store on
  launch and returns the persisted `{ serverUrl, token, userId }` or `null`; expose
  a session controller (context/provider + hook) with `signIn(serverUrl, email,
  password)`, `createAccount(serverUrl, email, password)`, and `signOut()` that
  persist via the store and update the in-memory session.
- **Bind the API base URL to the session, not to static config.** Extend the
  internal `Session` type to `{ serverUrl, token, userId }` and have
  `toApiSession`/`toProfileSession` source `baseUrl` from `session.serverUrl`
  instead of `resolveApiBaseUrl()`. The returned `ApiSession`/`ProfileSession`
  **shape is unchanged** (`{ baseUrl, token, userId }`), so `profile.ts` and
  `ProfileScreen` consume it unchanged — only the *source* of `baseUrl` moves from
  global config to the bound session. `resolveApiBaseUrl()`/`DEFAULT_API_BASE_URL`
  remain as the dev-default seed FTY-091's connect field pre-fills; they are no
  longer the runtime source of truth once a session is bound.
- Honor the pre-v1 clean-break stance: build the clean version of the seam (session
  carries its bound server; no hosted-instance assumption). **Remove the temporary
  dogfood shim** currently hard-coding a token in `useSession()` (the
  `⚠️ TEMP DOGFOOD SHIM` block) — its real replacement is exactly this story. No
  backward-compat shim for the old always-`null` placeholder is needed.

## Non-Goals

- Any connect / sign-in / create-account screen, QR scan of the server URL, route,
  or signed-out gating — that is FTY-091, which depends on this. This story only
  *accepts* a server URL as an argument and persists it inside the session.
- Remembering a "last server URL" across sign-out to pre-fill the connect field —
  sign-out clears the whole session record; whether to retain a last-server hint for
  re-entry is a FTY-091 connect-screen UX choice, out of scope here.
- Any backend or contract change. `register`/`login`/profile are consumed exactly
  as published; no new endpoint, field, or token shape.
- Token refresh / silent renewal. The backend issues a stateless ~7-day token with
  no refresh endpoint; on expiry the app re-authenticates (FTY-091 routes a `401`
  back to sign-in). No refresh logic here.
- Sign in with Apple / hosted auth (explicitly deferred by the identity contract),
  password reset, and biometric unlock — all future, out of scope.

## Contracts

- Introduces no new contract. Consumes the FTY-020 identity-and-profile contract:
  the `register`/`login` request/response shapes, the `{ "sub", "iat", "exp" }`
  HMAC-SHA256 token, and the `/api/users/{userId}/profile` ownership keying. The
  device-side `Session`/`ApiSession`/`ProfileSession` types are internal, not a wire
  contract; extending the internal `Session` to carry `serverUrl` does not touch the
  HTTP contract or the `ProfileSession` consumer shape.

## Security / Privacy

- The bearer token is a credential. The session record (token + bound `serverUrl` +
  `userId`) is stored only in the OS secure keychain/keystore via `expo-secure-store`,
  never in `AsyncStorage`, plain storage, or logs (security-baseline: secrets/tokens
  never logged; credentials least-privilege). The `serverUrl` and `userId` are not
  secrets but ride in the same secure record for atomicity.
- The password is held only long enough to send the auth request; it is never
  persisted on-device and never logged or echoed (mirrors `profile.ts` and the
  contract's password-is-secret rule).
- `userId` is derived from the unverified token payload **for addressing only**;
  authorization remains server-side and fails closed (`404`) on mismatch — the
  client never makes a trust decision from the decoded claim.
- The token is bound to its issuing server: requests built from a session always use
  the `serverUrl` the token was minted by, so a token can never be replayed against a
  different self-hosted server by a config swap. A torn/partial stored record is
  treated as no session rather than a token paired with the wrong/empty server.
- The auth client's error mapping is non-enumerating: a wrong password and an
  unknown email return the same `401` message, preserving the backend's
  no-user-enumeration property at the UI boundary.
- High risk: this is the credential-storage + token-handling + server-binding seam —
  the highest-stakes plumbing on the device. It is bounded and exactly specified over
  a first-party Expo keychain library with no new contract, schema, or untrusted-input
  trust boundary, but auth/session correctness has real cost if wrong, so it routes to
  opus-grade review. See the Readiness Sanity Pass for the risk call.

## Acceptance Criteria

- `createAccount(serverUrl, email, password)` posts to `{serverUrl}/api/auth/register`
  and returns `{ serverUrl, token, userId }` with `userId` from the response
  `user.id`; `signIn(serverUrl, email, password)` posts to
  `{serverUrl}/api/auth/login` and returns `{ serverUrl, token, userId }` with
  `userId` decoded from the token's `sub` claim. The persisted/returned `serverUrl`
  is the normalized (trimmed, no trailing slash) form of the supplied URL.
- A session established via `signIn`/`createAccount` is persisted in
  `expo-secure-store` as one record; after an app restart (store reload),
  `useSession()` rehydrates and returns the same `{ serverUrl, token, userId }`.
- `toApiSession`/`toProfileSession` build `baseUrl` from the session's `serverUrl`
  (not `resolveApiBaseUrl()`), so an authenticated profile call addresses the bound
  server; the returned `{ baseUrl, token, userId }` shape is unchanged and
  `profile.ts`/`ProfileScreen` consume it without edit.
- `signOut()` clears the session record from the secure store; `useSession()` then
  returns `null`.
- With no stored session, `useSession()` returns `null`, and the existing
  `ProfileScreen` still renders `<SignInRequired/>` unchanged; a missing, corrupt, or
  partial stored record also yields `null` (never a half-hydrated session).
- Auth errors map to non-enumerating messages: `401` for unknown-email and
  wrong-password is identical; nothing reveals account existence.
- No token, password, server URL credential, or auth response body is written to
  logs or error messages.
- The token is never read from or written to `AsyncStorage` or non-secure storage;
  the temp dogfood shim in `useSession()` is removed.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), against a mocked `fetchImpl`
  and a mocked `expo-secure-store`:
  - `createAccount` / `signIn` happy paths return the normalized
    `{ serverUrl, token, userId }`; the supplied `serverUrl` is normalized; the
    request URL targets the bound server; the login path derives the correct
    `userId` from a fixture token's `sub` claim.
  - Persistence round-trip: save via the controller, simulate restart by reloading
    from the (mocked) store, assert `useSession()` rehydrates the full session
    including `serverUrl`; `signOut` clears it and `useSession()` returns `null`.
  - Binding: assert `toApiSession`/`toProfileSession` produce `baseUrl ===
    session.serverUrl` (not the static default) for a session bound to a non-default
    server.
  - Resilience: a missing key, malformed JSON, or a record missing a field hydrates
    as `null` (no half session).
  - Error mapping: `401` unknown-email and `401` wrong-password produce the same
    message; `409`/`422` map to their messages; assert no message is an
    account-existence oracle.
  - Assert no test captures a token/password/response body in a log spy, and that
    the session is written only through the `expo-secure-store` mock.
- Run the mobile package checks (`npm run typecheck`, `npm run lint`, `npm run
  test` in `mobile/`, via `make verify` where wired).

## Planning Notes

- **New dependency:** `expo-secure-store` is **not** currently in
  `mobile/package.json` (only `expo`, `expo-camera`, `expo-constants`,
  `expo-linking`, `expo-router`, `expo-status-bar`). It must be added — install via
  `npx expo install expo-secure-store` to pin the SDK-compatible version — and
  declared per FTY-013's dependency rule (update story metadata first, justify in
  the PR). It is a first-party Expo package, so supply-chain risk is low, but it is
  a real add, not a pre-existing dependency.
- **Session shape change:** the existing `Session` is
  `Pick<ProfileSession, "token" | "userId">` and `toApiSession` injects
  `resolveApiBaseUrl()` (`state/session.ts`, lines ~20–53). This story widens
  `Session` to `{ serverUrl, token, userId }` and moves `baseUrl`'s source to the
  session, per UX design §4d self-host binding. The `toApiSession`/`toProfileSession`
  **return** shape (`{ baseUrl, token, userId }`) stays stable so FTY-021's
  `profile.ts`/`ProfileScreen` consumers don't change. The comment in `session.ts`
  ("once the sign-in story provides a `{ token, userId }`, persistence works with no
  change to the form") is fulfilled here — update it to note the bound server.
- **Remove the dogfood shim:** `useSession()` currently returns a hard-coded
  throwaway token (`⚠️ TEMP DOGFOOD SHIM` block). Replace it wholesale with the real
  hydrating implementation; no token literal remains in source.
- `resolveApiBaseUrl()`/`DEFAULT_API_BASE_URL` in `api/config.ts` stay as the dev
  default the connect field (FTY-091) seeds from — do not delete them; just stop
  using them as the runtime base-URL source once a session exists.

## Readiness Sanity Pass

- Product decision gaps: resolved. (1) `userId` is derived from the token's `sub`
  claim client-side for addressing only — the alternative (returning `user.id` from
  `login`) is a backend/contract change and explicitly out of scope, so
  token-decode-for-addressing is the chosen path. (2) `expo-secure-store` is the
  approved security-correct store and a justified new dependency. (3) v1 wants no
  token refresh (re-auth on expiry). (4) Per UX design §4d the session binds to the
  user's own server URL (no hosted instance), so the persisted/returned session
  carries `serverUrl`; the connect-screen UX that supplies and validates that URL
  (incl. QR) is FTY-091.
- Cross-lane impact: mobile-core (one boundary) plus the non-serializing
  security-privacy lane (credential storage + token handling). No backend, contract,
  or schema change; consumes FTY-020 as published.
- Security/privacy risk: high — credential storage in the OS keychain, server-bound
  token (no cross-server replay via config swap), no token in logs/`AsyncStorage`,
  non-enumerating error mapping, atomic session record (no torn/half hydration), and
  token-claim used for addressing only with server-side fail-closed authorization.
  Rated high (was medium): auth/session is the highest-stakes device seam and being
  wrong has real cost, so it routes to opus-grade review even though the slice adds
  no new contract, table, or untrusted-input trust boundary and authoritative
  authorization stays server-side.
- Verification path: mobile unit/integration tests against mocked `fetch` and mocked
  `expo-secure-store` (auth happy paths, login `userId`-from-claim, server-URL
  binding, persistence round-trip across simulated restart with `serverUrl`,
  resilience to partial/corrupt records, sign-out clear, non-enumerating errors,
  no-secret-in-logs), plus `make verify`.
- Sizing decision: one story, one boundary (mobile-core). Split from FTY-091 (the
  connect/sign-in/sign-out UI + routing): keeping the credential + server-binding
  seam separate gives it a focused, independently-verifiable security review and
  leaves FTY-091 a pure UI/flow slice. `review_focus` 5 (at the ceiling, not over) and
  `requires_context` 5 — within guardrails. No big-rock rule forces a further split:
  no contract change, no new table, and the server URL is user-supplied *configuration
  pointing at the user's own server*, not an untrusted-input trust boundary (no
  parsing of fetched/uploaded content into the trust domain). The split is a
  sizing + security-review choice, not a hard guardrail breach.
- Assumptions safe for autonomy: yes. Dependency note: FTY-091 depends on this
  story's `useSession()` / session-controller surface (`signIn`, `createAccount`,
  `signOut` taking a server URL) and the bound-`serverUrl` session shape; build this
  first.
