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
  is preserved. Fails open — a Redis blip allows the request rather than locking
  users out — and emits a warn-level log. Per-account keys use sha256(email) so no
  raw PII is stored in Redis. The source IP is the real TCP peer by default;
  `X-Forwarded-For` is trusted only behind exactly one known proxy
  (`FATTY_RATE_LIMIT_TRUSTED_PROXY=true`) and then read rightmost so a
  client-spoofed hop cannot bypass the per-IP limit. FTY-118.)*
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

- Logs must not contain secrets, auth tokens, raw sensitive prompts, full food histories, or unnecessary body data. *(v1: structured single-line JSON logs with a `RedactionFilter` that scrubs secret/header-shaped fields; the LLM layer logs only provider/attempt/error-count — never the prompt, key, image, or raw response. Proven by `tests/security/test_secret_no_disclosure.py`.)*
- Use request IDs and event IDs instead of personal values where possible.
- Redact sensitive fields in errors and provider traces. *(v1: transport and fetch errors are content-free — no URL, headers, request body, or response body.)*
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

