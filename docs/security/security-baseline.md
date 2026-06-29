# Security Baseline

Fatty handles sensitive personal data. The baseline is privacy by design, least privilege, and explicit trust boundaries.

## Standards

This project uses the following as design references:

- NIST Secure Software Development Framework SP 800-218.
- OWASP Application Security Verification Standard.
- OWASP Software Assurance Maturity Model.
- OWASP AI Agent Security Cheat Sheet.
- OWASP LLM Prompt Injection guidance.
- NIST Privacy Framework.
- OpenSSF Scorecard and SLSA for supply-chain direction.

## Data Minimization

- Collect only data needed for logging, estimation, targets, exercise burn, correction learning, and account operation.
- Do not store raw fetched pages, raw OCR, raw prompts, or attachments longer than needed unless there is a product reason.
- Store source facts separately from user-specific habits.
- Keep personal memories inspectable, editable, and deletable.
- On-device persistence of sensitive personal data must be scoped to the
  signed-in user and cleared on sign-out. *(v1: the FTY-104 offline outbox stores
  queued raw log text on-device in a per-user file while the device is offline.
  It holds only the signed-in user's own captures, is never written to logs or
  analytics, drains over the same authenticated/TLS log-events endpoint, and is
  purged for that user on sign-out so a queued entry never leaks to another user
  of the device.)*
- On-device persistence of a *credential* must use the OS keychain/keystore, be
  written atomically, never be logged, and be cleared on sign-out. *(v1: the
  FTY-090 mobile session store persists the signed-in user's bearer token — the
  `{serverUrl, token, userId}` record — as one atomic JSON value under a single
  key in the iOS keychain via `expo-secure-store` (`mobile/state/sessionStore.ts`).
  The token never touches `AsyncStorage`, plain files, or logs; a missing, corrupt,
  or partial record fails closed to no session rather than a half-hydrated one; and
  the record is deleted on sign-out. The signature is never trusted client-side —
  the server stays authoritative.)*

## Encryption and Secrets

- Require TLS in hosted and production-like deployments.
- Use database and object-storage encryption where supported by the deployment.
- Consider application-level encryption for highly sensitive fields once the data model is finalized.
- Store provider keys and app secrets in environment variables or secret managers.
- Never expose LLM/search/nutrition provider keys to clients.
- Never commit `.env`, tokens, private keys, or production credentials.

## Authentication and Authorization

- Keep authentication identities separate from users. *(v1: `AuthIdentity` rows are
  distinct from `User`; the local path uses email + a hashed password.)*
- Prefer Sign in with Apple for iOS hosted auth when available. *(Deferred; v1 ships
  the local path only.)*
- Self-hosted auth must support a secure local path. *(v1: local email + password
  with stateless, HMAC-SHA256-signed bearer tokens; login is constant-time and does
  not reveal whether an email exists. Tokens are not yet revocable — tracked
  finding.)*
- Rate-limit the auth endpoints to bound online brute-force and credential-stuffing.
  *(v1: `POST /api/auth/login` is throttled per source IP and per account (hashed
  email); `POST /api/auth/register` is throttled per source IP. Backed by the
  existing Redis so the limit holds across worker processes. Thresholds are
  configurable via `FATTY_RATE_LIMIT_*` env vars. The limiter runs before the
  credential check so a throttled request pays no hash/DB cost and equalized timing
  is preserved. Per-account keys use sha256(email) so no raw PII is stored in Redis.
  The source IP is the real TCP peer by default; `X-Forwarded-For` is trusted only
  behind exactly one known proxy (`FATTY_RATE_LIMIT_TRUSTED_PROXY=true`) and then
  read rightmost so a client-spoofed hop cannot bypass the per-IP limit. FTY-118.)*
  *(Fail-mode — FTY-138: when the limiter raises (e.g. Redis unavailable) the
  effective fail-mode is environment-defaulted: **fail-open** (allow + warn log) in
  `development` and `test`, **fail-closed** (deny with `503 Service Unavailable` +
  `Retry-After` + warn log) in `production`. Fail-closed is the correct default for
  production: a Redis outage silently disabling the only online brute-force
  protection is a worse outcome than briefly rejecting auth requests until Redis
  recovers. The `503` response is intentionally transient so the mobile
  reconnect/retry path backs off and retries rather than treating it as a
  credential failure. The fail-mode can be forced in either direction via
  `FATTY_RATE_LIMIT_FAIL_OPEN_OVERRIDE=true|false`, independent of environment
  (e.g. a production self-host that prefers availability can opt back into
  fail-open). No new PII is added to logs in either branch.)*
- Enforce object-level authorization on every user-owned record. *(v1: every
  user-owned service authorizes the owner and scopes the query to the owner, failing
  closed as `404`; proven by the FTY-073 `tests/security/test_authz_fail_closed.py`
  sweep.)*
- Add negative authorization tests for new data access paths.

## LLM and Agent Safety

- Treat the LLM as an untrusted analyst.
- Use structured outputs and schema validation.
- Keep tools allowlisted and parameter-validated.
- Sanitize search queries so personal context is not sent to search providers.
- Use a hardened fetcher with SSRF protections.
- Do not allow open-ended code execution, shell, filesystem, email, calendar, or broad personal tools in the estimator.
- Memory writes require validation and user isolation.

## Logging and Telemetry

- Logs must not contain secrets, auth tokens, raw sensitive prompts, full food histories, or unnecessary body data. *(v1: structured single-line JSON logs with a `RedactionFilter` that scrubs secret/header-shaped **fields** by name; a second pass via `_redact_values` scrubs token-shaped **values** — Bearer tokens, JWTs, provider API keys (`sk-…`, `gh…_…`, Slack `xox…`, AWS `AKIA…`), and inline `key=value` / `key: value` forms — from rendered messages and serialised exception traces. The LLM layer logs only provider/attempt/error-count — never the prompt, key, image, or raw response. Proven by `tests/security/test_secret_no_disclosure.py`.)*
- Use request IDs and event IDs instead of personal values where possible.
- Redact sensitive fields in errors and provider traces. *(v1: transport and fetch errors are content-free — no URL, headers, request body, or response body; exception traces carrying token-shaped secrets are also scrubbed by `_redact_values` before serialisation.)*
- Telemetry must be opt-in or clearly documented before public launch. *(v1 ships no product telemetry.)*

## HTTP Security Headers

Every API response carries baseline defense-in-depth headers applied by a
dedicated middleware in `app/main.py` (FTY-112):

- `X-Content-Type-Options: nosniff` — blocks MIME-confusion attacks.
- `X-Frame-Options: DENY` — blocks clickjacking; the API is consumed by a
  native client and is never framed.
- `Referrer-Policy: no-referrer` — limits referrer leakage on redirects.

`Strict-Transport-Security` (HSTS) is intentionally omitted: TLS termination
is the self-hoster's reverse-proxy concern, not the application's.
`Content-Security-Policy` is omitted because this is a JSON API consumed by a
native client, making a CSP low-value.

## API Schema Exposure

In `production`, the interactive docs (`/docs`, `/redoc`) and the raw OpenAPI
schema (`/openapi.json`) are disabled (`404`) to prevent the full API surface
from being publicly enumerable on a self-host (FTY-112). This is a
reconnaissance reduction, not a substitute for authorization. In `development`
and `test` the docs remain available.

## Container Security

- The backend image runs as a dedicated non-root system user (`fatty`, UID/GID
  10001) rather than root (FTY-116). A fixed UID/GID keeps ownership stable
  across rebuilds and named-volume mounts.
- All runtime paths owned by the `fatty` user: `/app` (app source + `.venv`),
  `/home/fatty` (CLI scratch / cache), and `/claude-config` (Claude Code session
  volume mountpoint — inherits owner on first use).
- `HOME` is set to `/home/fatty` so the `claude` CLI has a writable home
  directory without falling back to root-owned paths.
- Future hardening (read-only root filesystem, `cap_drop`, `no-new-privileges`,
  seccomp) is deferred to dedicated stories and is not yet applied.

## Supply Chain

- Use pinned or locked dependencies.
- Enable dependency update automation.
- Use GitHub branch protection and required checks.
- Add SBOM/provenance work before public releases.

