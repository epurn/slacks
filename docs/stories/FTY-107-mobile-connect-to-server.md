---
id: FTY-107
state: merged
primary_lane: mobile-core
touched_lanes:
  - security-privacy
risk: high
tags:
  - mobile
  - self-host
  - server-connection
  - qr
  - onboarding
approved_dependencies:
  - FTY-097
requires_context:
  - docs/design/ux-design.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/security/security-baseline.md
review_focus:
  - url-validation-and-untrusted-qr
  - server-reachability-error-state
  - base-url-persistence-and-accessor
  - first-run-routing
  - accessibility-and-light-dark-parity
autonomous: true
---

# FTY-107: Mobile Connect-to-Your-Server (URL Entry + QR Scan)

## State

ready_with_notes

## Lane

mobile-core (+ security-privacy)

## Dependencies

- FTY-097 (design system: tokens, amber accent, themed Button/Card/Text, light/dark
  surfaces — the connect screen and its error/retry states are built against these)
- FTY-063 (mobile barcode scanner: the reusable camera scaffold — `CameraCapture`,
  `cameraPermission` state — this story reuses for QR scanning; `expo-camera` is
  already a declared dependency)
- FTY-013 (mobile app skeleton: the expo-router shell this adds a route to)

## Related

<!-- Reverse reference only — NOT a scheduling dependency (FTY-091 depends on
     THIS story, not the other way around). Kept out of Dependencies so the
     parser does not read it as a blocker. -->

- **FTY-091 (sign-in / create-account) depends on this story** — it reads the
  persisted base URL exposed here and hands off to this connect screen when no
  server is connected. Build this first.

## Outcome

This is the **connect-to-your-server step** of the self-host-first first-run
(`docs/design/ux-design.md` §4d), the first thing a new user sees. After it:

1. The app has a **"Connect to your Fatty server"** screen (a new expo-router
   route) where the user **enters or scans** the server URL. Manual entry is the
   fallback; the **setup QR carries the server URL only** (no embedded secret) —
   scanning just fills in the URL, the user still creates the account manually
   later (FTY-091).
2. The entered/scanned URL is **validated and probed for reachability**, then
   **persisted**, so subsequent launches and every API client target the user's
   own server. `mobile/api/config.ts`'s `resolveApiBaseUrl()` becomes the accessor
   that prefers this persisted connection over the build-time default.
3. First-run routing is correct: **no server connected → this screen**; a server
   is connected → on to sign-in (FTY-091). Reachability failures are clear and
   retryable, never a dead-end.

Built against the FTY-097 design system (native, calm, light + dark).

## Scope

Per `docs/design/ux-design.md` §4d (self-host connection) and §6 (states & edges):

- Add a **"Connect to your Fatty server"** screen as a new expo-router route under
  `mobile/app/` (e.g. `app/connect.tsx`), built from **FTY-097 primitives** (themed
  Text/Button/Card, amber accent) and rendering correctly in **both light and
  dark**. Two input affordances:
  - **Manual URL entry** (a text field; the primary/fallback path).
  - **Scan QR** — reuse the FTY-063 `CameraCapture` scaffold + `cameraPermission`
    state to read a QR whose payload is **the server URL only**. The scan fills the
    URL field; it never carries or stores a secret/token.
- **URL validation (untrusted input).** Treat both the typed string and the
  scanned QR payload as untrusted: require a well-formed absolute `http(s)` URL,
  reject non-`http(s)` schemes (e.g. `javascript:`, `file:`, deep links),
  normalize (trim, strip trailing slash like `resolveApiBaseUrl` does today), and
  surface a clear inline error for anything malformed **before** any network call
  or persistence. A scanned QR that is not a valid server URL is rejected with a
  gentle "that QR isn't a Fatty server URL" message, not silently accepted.
- **Reachability probe.** Before persisting/advancing, probe the candidate server
  (e.g. `GET {base}/healthz`, the documented health endpoint) with a timeout:
  - reachable → persist and advance to sign-in (FTY-091);
  - unreachable / timeout / non-Fatty response → **"Can't reach `[server]` ·
    Retry"** (§6), retryable, never a dead-end; the URL stays editable so the user
    can fix a typo.
- **Persist the connection.** Store the validated base URL in **on-device app
  storage** (e.g. `AsyncStorage` / a small connection store). The base URL is
  **non-secret configuration** (the existing `config.ts` docstring says so), so it
  does **not** require `expo-secure-store` — that is reserved for the FTY-090
  bearer token. Never store a secret here.
- **Make `resolveApiBaseUrl()` connection-aware.** Update `mobile/api/config.ts`
  (and/or expose a small accessor) so the resolved base URL prefers the persisted
  connection, falling back to the build-time `extra.apiBaseUrl` / `localhost`
  default when none is set. Keep the existing trailing-slash normalization and the
  "non-secret config" contract. All existing API clients keep calling
  `resolveApiBaseUrl()` unchanged.
- **First-run routing.** When no server is connected, the signed-out flow routes
  here (FTY-091 consumes the connected state for its three-state gate). Provide a
  way to **change the connected server** later (the design's §4c ACCOUNT & SERVER
  surface owns the settings entry; this story exposes the connect screen + a
  "change server" affordance/clear, not the full Profile UI).
- Accessible (Dynamic Type, VoiceOver labels on the URL field / Scan / Retry,
  ≥44pt targets, Reduce-Motion-safe), iOS-first, compact, calm.
- Honor the pre-v1 clean-break stance: build the clean connection flow; no compat
  shim for the build-time-only base URL beyond keeping it as the no-connection
  fallback.

## Non-Goals

- **Sign-in / create-account / the signed-out auth gate** — owned by **FTY-091**,
  which depends on this and reads the persisted base URL.
- **Token / credential storage** — owned by **FTY-090** (`expo-secure-store`).
  Nothing secret is stored here; the server URL is non-secret config.
- The **design tokens / primitives / theming** themselves — owned by **FTY-097**.
- The full **Profile → ACCOUNT & SERVER** settings screen — a separate Profile
  story owns it; this story exposes the connect screen + a change/clear affordance
  it can link to.
- **TLS pinning, certificate trust customization, or self-signed-cert handling** —
  out of scope for v1; the probe uses the platform's default TLS trust. (Noted as
  a follow-up consideration, not built here.)
- Embedding any secret/token in the QR (explicitly rejected by the design — URL
  only) or pairing/provisioning beyond the server URL.
- Any backend or contract change. `/healthz` is consumed as published.

## Contracts

- Introduces no new wire contract. Consumes the existing `/healthz` health
  endpoint for the reachability probe (documented in the system overview /
  operations docs). The persisted connection and the base-URL accessor are
  **internal mobile conventions**, not a cross-package contract. The QR payload
  format is "a bare server URL string" — a local convention with the self-host
  setup docs, not an app-to-server contract.

## Security / Privacy

- **High risk:** this screen establishes the **network target every subsequent
  request (including credentials in FTY-091) is sent to**, and one of its inputs is
  an **untrusted QR scanned from a camera**. A malicious QR pointing the app at an
  attacker-controlled host is the primary threat. Mitigations:
  - Treat the typed string and QR payload as untrusted: strict `http(s)`-only URL
    validation, scheme/format rejection, normalization, and a clear error on
    anything malformed — before any network call or persistence.
  - The persisted base URL is surfaced to the user (and shown again on the FTY-091
    sign-in screen) so they can confirm it is their own server before entering
    credentials (anti-phishing; defense continues in FTY-091).
- The server URL is **non-secret configuration** and is stored in normal on-device
  storage, **never** in the secure token store and **never** logged as a secret.
  No token, password, or credential is handled or stored by this story.
- The reachability probe sends **no personal data** — only an unauthenticated
  `GET /healthz` to the candidate base URL.
- Camera use reuses FTY-063's permission flow; no image/QR payload is persisted
  beyond reading the URL.

## Acceptance Criteria

- A first launch with no connected server shows the "Connect to your Fatty server"
  screen (built from FTY-097 primitives, correct in light **and** dark), offering
  manual URL entry and a Scan-QR affordance.
- Scanning a QR whose payload is a valid server URL fills the URL field; the user
  still proceeds to create an account / sign in manually (no auto-auth, no secret
  consumed).
- A malformed or non-`http(s)` URL (typed or scanned) is rejected with a clear
  inline error before any network call; a QR that is not a valid server URL is
  rejected with a gentle message.
- A reachable server (`/healthz` OK within the timeout) is persisted and the flow
  advances to sign-in (FTY-091).
- An unreachable / timed-out / non-Fatty server shows **"Can't reach `[server]` ·
  Retry"**, keeps the URL editable, and is retryable — never a dead-end.
- After a successful connect, `resolveApiBaseUrl()` returns the persisted server
  URL (normalized, no trailing slash); existing API clients target it unchanged;
  the value survives an app restart.
- The persisted server URL is in normal app storage, never the secure token store,
  and is never logged as a secret; no credential is handled here.
- Accessibility: VoiceOver labels on the URL field, Scan, and Retry; ≥44pt
  targets; Dynamic Type; Reduce-Motion-safe.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), against a mocked `fetchImpl`,
  a mocked persistence store, and the FTY-063 camera scaffold mocked:
  - **URL validation:** valid `http(s)` URLs accepted+normalized; non-`http(s)`
    schemes, malformed strings, and empty input rejected with inline errors;
    scanned-QR payloads run the same validation (a bad QR is rejected).
  - **Reachability:** `/healthz` OK → persists + advances; timeout / error / non-OK
    → "Can't reach `[server]` · Retry", URL stays editable, retry re-probes.
  - **Persistence + accessor:** a connected URL is persisted and
    `resolveApiBaseUrl()` returns it (normalized) on reload; with none set it falls
    back to the build-time default; assert the value is written to normal storage,
    not the secure store, and never to a log spy.
  - **Routing:** no-connection state routes to this screen; connected state hands
    off to sign-in (FTY-091's gate consumes it).
  - **QR scan:** a valid-URL QR fills the field and does not auto-authenticate or
    persist any secret.
  - **Light + dark** render coverage; accessibility labels and tap targets.
- Run mobile typecheck, lint, and tests via `make verify` (`mobile/verify.sh`).
- On an iOS simulator: connect via manual entry to a running local backend
  (reachable → advances); enter a bogus URL (unreachable → Retry); scan a QR
  carrying the server URL; relaunch and confirm the connection persists — in light
  and dark.

## Planning Notes

- `mobile/api/config.ts` today resolves the base URL from build-time
  `expo-constants` `extra.apiBaseUrl` (default `http://localhost:8000`) and
  normalizes the trailing slash. This story makes it **connection-aware**: prefer
  the persisted runtime connection, keep the build-time value as the no-connection
  fallback, preserve normalization and the "non-secret config" docstring. Because
  the accessor may become async (reading persisted storage), check whether call
  sites resolve it synchronously and provide a hydrated/cached accessor so existing
  clients don't need rewiring — keep the change minimal and backward-shaped.
- Reuse FTY-063's `CameraCapture` / `cameraPermission`; QR decoding uses
  `expo-camera`'s barcode/QR scanning (already a declared dependency) — confirm the
  QR `barcodeTypes` config; no new camera dependency expected. Any added dependency
  follows the FTY-013 rule (declare in the PR with justification, update metadata
  first).
- `/healthz` is the documented health endpoint used for the reachability probe;
  confirm its path against the operations docs at implementation time.

## Readiness Sanity Pass

- **Why this story exists (split from FTY-091):** the §4d first-run is
  connect-to-server → sign-in/create → onboarding → Today. Bundling connect +
  sign-in in one story breached the size ceiling (~7–8 review concerns) **and**
  bundled two distinct trust boundaries — the **untrusted QR/URL network-target
  boundary** (here) and the **credential-entry** boundary (FTY-091). The guardrail
  splits a second trust boundary out regardless of counts, so connect-to-server is
  this dedicated prerequisite. It carries the untrusted-input concern cleanly and
  gets its own focused (high-risk) review.
- **Product decision gaps:** none blocking — §4d fixes the design (enter or scan;
  QR is URL-only, no secret; manual entry is the fallback) and §6 fixes the error
  state ("Can't reach `[server]` · Retry", never a dead-end). One implementation
  choice flagged in Notes: whether `resolveApiBaseUrl()` stays sync (hydrated
  cache) or becomes async — kept minimal/backward-shaped, hence `ready_with_notes`.
- **Evidence basis:** no research warranted — connection/onboarding plumbing, not a
  health/nutrition/behavioural decision.
- **Cross-lane impact:** single boundary — **mobile-core** only, with a
  security-privacy facet (the untrusted QR/URL → network-target boundary). No
  backend, contract, or schema change; `/healthz` consumed as published.
- **Sizing call:** `review_focus` 5 (at the ceiling) and `requires_context` 4
  (well under 8) — one limit reached, not two, so it stays one story. The five
  concerns (URL validation, reachability, persistence/accessor, routing,
  a11y/light-dark) are tightly coupled around one screen.
- **Security/privacy risk:** **high** — it sets the network target for all later
  credentialed traffic and ingests an untrusted scanned QR; strict `http(s)`
  validation, no secret stored/logged, an unauthenticated-only `/healthz` probe,
  and a user-visible server confirmation are the mitigations. (TLS pinning /
  self-signed handling is an explicit v1 non-goal/follow-up.)
- **Verification path:** mobile tests for URL validation, reachability + retry,
  persistence + connection-aware accessor, routing, QR scan, and light/dark a11y,
  with the camera scaffold + fetch + store mocked; plus `make verify` and an iOS
  simulator connect/persist smoke check.
- **Assumptions safe for autonomy:** yes, with the dependency note — FTY-097
  (tokens) and FTY-063 (camera scaffold) should be available; FTY-091 depends on
  this story's persisted base URL + connect hand-off, so build this first.
