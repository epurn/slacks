---
id: FTY-091
state: ready_with_notes
primary_lane: mobile-core
touched_lanes:
  - security-privacy
risk: high
tags:
  - mobile
  - auth
  - sign-in
  - create-account
  - onboarding
approved_dependencies:
  - FTY-090
  - FTY-097
  - FTY-107
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/identity-and-profile.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - signed-out-routing-and-gating
  - form-validation
  - non-enumerating-error-surface
  - signout-control
  - accessibility-and-light-dark-parity
autonomous: true
---

# FTY-091: Mobile Sign-In / Create-Account Screen + Signed-Out Gating

## State

ready_with_notes

## Lane

mobile-core (+ security-privacy)

## Dependencies

- FTY-107 (connect-to-your-server: establishes and persists the user's chosen
  server base URL — entered or QR-scanned — and exposes the base-URL accessor the
  auth client posts to. This screen signs in / creates an account **on the
  connected server**, so the connection must exist first; routing hands off to
  FTY-107 when no server is connected yet. **Must land first.**)
- FTY-090 (session token store + auth client: this story's screens call its
  `signIn` / `createAccount` / `signOut` and rely on `useSession()` being real and
  persisted — **must land first**)
- FTY-097 (design system: tokens, type ramp, amber accent, light/dark surfaces,
  themed Text/Number/Button/Card primitives — the screen is built and restyled
  against these, replacing today's ad-hoc inline `StyleSheet` hex)
- FTY-013 (mobile app skeleton: the expo-router shell this adds a route to)
- FTY-021 (profile capture: the `<SignInRequired/>` dead-end this replaces with a
  real entry point; also hosts the sign-out control)
- FTY-103 (onboarding) — **soft seam, not a hard blocker.** Per the design, a
  successful first-run auth hands off to onboarding before Today. This story
  routes to onboarding when it exists and the user's goal/profile is unset, and
  otherwise lands on Today (the existing landing); it does not implement
  onboarding.

## Outcome

This is the **sign-in / create-account half** of the self-host-first first-run
(`docs/design/ux-design.md` §4d), sitting on top of FTY-107's server connection
and FTY-090's session plumbing. After it:

- The app gains a **sign-in / create-account screen** (a new expo-router route),
  restyled against the FTY-097 design system (native, calm; amber accent; light
  and dark), that signs you in or creates an account **on the server you connected
  to in FTY-107** (email + password).
- A signed-out launch **routes correctly instead of dead-ending**: no server
  connected → the FTY-107 connect screen; server connected but no session → this
  sign-in screen; a valid persisted session (FTY-090) → straight to Today (with
  the onboarding hand-off in between for a first run, FTY-103).
- After successful auth the user is routed onward (onboarding → Today), never left
  on a blank or signed-out state.
- A **sign-out** control (on Profile, per §4c ACCOUNT & SERVER) clears the stored
  session via FTY-090 and returns the user to the sign-in screen.
- Forms validate sensibly and surface auth failures with friendly, **non-
  enumerating**, never-dead-end copy (§6).

This closes the polish/dogfooding gap where the app opened to a signed-out empty
state with no sign-in or create-account control anywhere, and replaces the
temporary hardcoded-token dogfood shim path with the real signed-out flow.

## Scope

Per `docs/design/ux-design.md` §4d (sign-in & self-host connection), §3
(onboarding), and §6 (sign-in error states):

- Add a **sign-in / create-account screen** as a new expo-router route under
  `mobile/app/` (e.g. `app/signin.tsx`), registered on the existing shell. A
  single screen toggling between "Sign in" and "Create account" is the v1 shape;
  both modes collect email + password. Build it from **FTY-097 primitives**
  (themed Text/Number/Button/Card, amber accent, system-material surfaces) so it
  renders correctly in **both light and dark** — no inline hex.
- **Server-scoped sign-in.** The screen targets the connected server from
  FTY-107: it reads the persisted base URL through FTY-107's accessor (the same
  one `mobile/api/config.ts` resolves) and **shows which server you are signing in
  to** (e.g. a "Signing in to `home.example.net`" line). FTY-090's auth client
  posts `register`/`login` to that base URL. This is also an anti-phishing signal:
  because the target can come from a scanned QR (FTY-107), the user can confirm it
  is their own server before typing credentials.
- Wire the screen to FTY-090: "Sign in" calls `signIn(email, password)`, "Create
  account" calls `createAccount(email, password)`. On success the session is
  already persisted by FTY-090; the screen routes the user onward (see routing).
- **Signed-out gating / routing** (three-state, no dead-end):
  - `useSession()` is non-null → the app behaves as today (Today is the landing;
    a first run passes through onboarding first).
  - `useSession()` is null **and a server is connected** → route to this sign-in
    screen.
  - `useSession()` is null **and no server is connected** → route to FTY-107's
    connect-to-server screen.
  - Replace the `<SignInRequired/>` dead-end on the profile path with a path into
    this flow (repurpose the component to deep-link to sign-in, or redirect before
    it renders — keep it coherent, no orphan dead-end).
- **Post-auth routing.** On a successful `signIn`/`createAccount`: route to
  onboarding (FTY-103) when the user's goal/profile is not yet set, otherwise to
  Today. Until FTY-103 exists, land on Today (existing landing). No automatic
  jarring navigation beyond this single post-auth hand-off.
- **Form validation** before any network call: email shape, and password length
  8–128 to mirror the backend (identity-and-profile contract). Show inline,
  nonjudgmental field errors using FTY-097 styles; never block on rules the
  backend does not enforce.
- **Error surface (§6 — clear, retryable, never a dead-end):**
  - Bad credentials → an **inline field error**, non-enumerating: unknown email
    and wrong password show the **same** message ("That email or password doesn't
    match"). No account-existence oracle.
  - `409` on create-account → an "account already exists — sign in instead"
    affordance that switches the toggle to Sign in (not an error dead-end).
  - `422` → a generic "check your details".
  - A `401` from an expired token elsewhere routes back to this screen (re-auth;
    no silent refresh — FTY-090 non-goal).
  - (Server-unreachable during sign-in surfaces FTY-107's "Can't reach `[server]`
    · Retry" treatment; FTY-107 owns the reachability concern and copy, this
    screen reuses it rather than redefining it.)
- **Sign-out control:** a clearly-placed affordance on the Profile screen (§4c
  ACCOUNT & SERVER) that calls FTY-090 `signOut()`, clears the session, and
  returns to sign-in.
- Password input uses **secure text entry**; the password is never rendered to
  logs or surfaced in errors. iOS-first, accessible (Dynamic Type, VoiceOver
  labels, ≥44pt targets, Reduce-Motion-safe), compact, nonjudgmental.
- Honor the pre-v1 clean-break stance: build the clean flow; remove the temporary
  hardcoded-token dogfood path so the signed-out flow is real (FTY-090 already
  replaces `useSession()`); no compat shim for the old always-signed-out
  placeholder.

## Non-Goals

- **Connecting to the server / the server-URL entry + QR scan + persistence +
  reachability check** — all owned by **FTY-107**; this story consumes its
  persisted base URL and hands off to its connect screen when no server is set.
- The secure token store, auth API client, and `useSession()` hydration — all
  owned by **FTY-090**; this story consumes them.
- The **design tokens / primitives / light-dark theming** themselves — owned by
  **FTY-097**; this story consumes them.
- The **onboarding flow** (goal/pace → measurements → target reveal) — owned by
  **FTY-103**; this story only hands off to it after auth.
- Any backend or contract change (no new endpoint, field, or token behavior).
- Sign in with Apple / hosted auth (explicitly deferred by the identity contract),
  password reset / forgot-password, email verification, and biometric unlock —
  all future.
- Token refresh / silent renewal (backend has no refresh endpoint; expiry routes
  to re-auth, per FTY-090).
- Profile-capture changes beyond replacing the `<SignInRequired/>` dead-end with a
  route into sign-in and hosting the sign-out control (FTY-021 owns the form;
  the full Profile redesign is a separate story).

## Contracts

- Introduces no new contract. Consumes the FTY-020 identity-and-profile behavior
  (`register`/`login` status semantics, password 8–128, no user enumeration) only
  through FTY-090's client, FTY-107's persisted base-URL accessor, and FTY-097's
  internal theming convention. The device-side session/connection types are
  internal, not a wire contract.

## Security / Privacy

- **High risk:** this is the auth UI that handles credentials and owns the
  signed-out trust gate / routing. Credentials are entered in a secure-text
  password field, sent only via FTY-090's client to the **FTY-107-validated**
  server base URL, and never logged, persisted on-device, or echoed into errors.
- The error surface preserves the backend's **no-enumeration** property: unknown
  email and wrong password are indistinguishable to the user.
- Because the destination server can originate from a scanned QR (FTY-107), the
  screen **displays the server it is about to authenticate against** so the user
  can confirm it is their own server before entering credentials (anti-phishing).
  URL validation/trust itself is enforced upstream in FTY-107.
- **Sign-out fully clears** the stored token (delegated to FTY-090) so a
  shared/loaned device does not retain a session.
- No provider keys or secrets are involved on the client (security-baseline).
- Credential storage/handling and the wire calls live in FTY-090; the server-URL
  trust boundary lives in FTY-107. This slice is presentation, validation, and
  routing — but it is the surface where the user actually types a password, so it
  is reviewed at high risk.

## Acceptance Criteria

- From a signed-out launch with a connected server, the app shows the sign-in /
  create-account screen (no dead-end empty state), built from FTY-097 primitives,
  and there is a visible control to switch between signing in and creating an
  account.
- From a signed-out launch with **no** connected server, the app routes to
  FTY-107's connect-to-server screen instead of the sign-in screen.
- The screen displays the server it will authenticate against (the FTY-107
  base URL) and posts auth to that base URL via FTY-090's client.
- Creating an account with a valid email + password (8–128) signs the user in and
  routes onward (onboarding when goal/profile is unset, else Today); the session
  persists across restart (via FTY-090).
- Signing in with valid credentials routes onward; signing in with a wrong
  password OR an unknown email shows the **same** non-enumerating inline message.
- Invalid email or a too-short/too-long password is caught by client-side
  validation before any network call, with inline field errors.
- A create-account attempt on an existing email (`409`) surfaces an "already
  exists — sign in instead" affordance (switches to Sign in) rather than an error
  dead-end.
- A sign-out control on Profile clears the session and returns the user to the
  sign-in screen; relaunch then shows sign-in (session gone).
- The screen renders correctly in **both light and dark**; VoiceOver labels on
  email/password fields, the mode toggle, and the submit; ≥44pt targets;
  secure-text on password; a screen-reader-coherent error surface.
- No password or token appears in logs or error output.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), with FTY-090's controller +
  client, FTY-107's base-URL accessor, and FTY-097 tokens mocked/available:
  - Component tests for the screen in both modes: validation (email shape,
    password 8–128) blocks submit and shows inline errors; valid submit calls the
    correct controller method against the connected base URL.
  - Routing/gating tests: `useSession()` null + server connected → sign-in;
    `useSession()` null + no server → FTY-107 connect; non-null → Today (with the
    onboarding hand-off when goal/profile is unset); the profile path no longer
    shows an orphan dead-end.
  - Flow tests: successful `signIn`/`createAccount` routes onward; `401` shows the
    shared non-enumerating message inline; `409` on create surfaces the sign-in
    affordance and flips the toggle; `422` shows the generic message.
  - Sign-out test: invoking the control calls `signOut()` and returns to sign-in.
  - Light/dark render coverage of the screen and its error/affordance states.
  - Accessibility checks (iOS-first): labelled email/password fields, secure text
    entry on password, accessible mode-toggle and submit, Reduce-Motion-safe.
  - Assert no password/token is captured by a log spy.
- Run the mobile package checks via `make verify` (`mobile/verify.sh`: `npm ci` →
  `npm run typecheck` → `npm run lint` → `npm test`).
- On an iOS simulator: from a clean state, connect a server (FTY-107), create an
  account, confirm routing onward; kill and relaunch to confirm the session
  persists; sign out and confirm return to the sign-in screen — in light and dark.

## Planning Notes

- `mobile/app/_layout.tsx` is being migrated to the FTY-097 tab shell; add this
  route to that shell (it is built to host new screens without restructuring).
- `state/session.ts` currently carries a **TEMP DOGFOOD SHIM** that hardcodes a
  bearer token (flagged "REVERT BEFORE COMMIT"). FTY-090 replaces `useSession()`
  with the real hydrated session; this story must ensure the signed-out flow is
  genuinely signed-out (no hardcoded-token path remains reachable).
- `mobile/api/config.ts` resolves the API base URL today from build-time
  `expo-constants` `extra.apiBaseUrl` (default `http://localhost:8000`). FTY-107
  turns that into a **runtime, persisted, user-connected** value; this screen
  reads it through FTY-107's accessor, not by reintroducing build-time config.
- The exact routing primitive (a guard/redirect in the shell vs. redirects from
  index/profile) is an implementation choice; keep it coherent so there is no
  reachable dead-end and the three signed-out states route correctly.

## Readiness Sanity Pass

- **Sizing / split decision (the headline change):** the design's first-run flow
  (§4d) is connect-to-server → sign-in/create → onboarding → Today. Folding the
  **connect-to-server + QR scan + URL validation + reachability + base-URL
  persistence** into this story would push it to ~7–8 review concerns (well over
  the ceiling of 5 / split-signal of 6) **and** bundle a **new untrusted-input
  trust boundary** (camera-scanned QR → a network target the app then sends
  credentials to) on top of credential-handling — a boundary bundle the guardrail
  splits regardless of counts. So connect-to-server is pulled into its own
  prerequisite story, **FTY-107** (created alongside this refinement), and this
  story is narrowed to the **auth screens + signed-out routing/gating + restyle**.
  That keeps FTY-091 at `review_focus` 5 (at the ceiling) and `requires_context`
  4 (well under 8) — one clean mobile-core boundary. FTY-091 depends on FTY-107.
- **Product decision gaps:** resolved by the design doc. (1) one combined
  toggle screen (§4d implies a single sign-in/create surface) — confirmed as the
  v1 shape; (2) sign-out lives in Profile → ACCOUNT & SERVER (§4c) — confirmed;
  (3) error copy/tone is fixed by §6 (clear, retryable, non-enumerating, never a
  dead-end); (4) password validation mirrors the backend 8–128 with no extra
  complexity rules (identity-and-profile contract); (5) `401`/expiry routes back
  to sign-in, no silent refresh (FTY-090). Post-auth onboarding hand-off (FTY-103)
  is a soft seam: route to onboarding when present and goal/profile unset, else
  Today.
- **Evidence basis:** no research warranted — this is auth/connection UI and
  routing, not a health/nutrition/behavioural decision. The design doc's
  evidence-backed calls (e.g. weigh-in cadence, §4b) live in other stories.
- **Cross-lane impact:** single boundary — **mobile-core** only, with a
  security-privacy facet (credential entry + the signed-out trust gate). No
  backend, contract, or schema change; consumes FTY-020 as published through
  FTY-090.
- **Security/privacy risk:** **high** — this is where the user types a password
  and where the signed-out trust gate routes. Secure-text entry, non-enumerating
  errors, full session clear on sign-out, the connected-server confirmation
  (anti-phishing), and no secret in logs. Heavier credential storage/handling is
  in FTY-090; the server-URL trust boundary is in FTY-107. Raised from medium to
  high per the "estimate big" rule for an auth surface.
- **Verification path:** mobile component/routing/flow/sign-out/a11y tests with
  FTY-090 + FTY-107 mocked and FTY-097 tokens available, light/dark coverage, plus
  a simulator connect→create→restart→sign-out smoke check and `make verify`.
- **Assumptions safe for autonomy:** yes, with the ordering note — **FTY-107,
  FTY-090, and FTY-097 must land first** (this story builds against FTY-107's
  base-URL accessor + connect hand-off, FTY-090's `signIn`/`createAccount`/
  `signOut`/`useSession()`, and FTY-097's tokens/primitives). Until then those
  surfaces are mocked against their published shapes. Captured as
  `ready_with_notes` for the FTY-103 soft seam and the dependency ordering.
