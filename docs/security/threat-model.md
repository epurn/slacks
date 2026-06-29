# Threat Model

This threat model is reviewed against the as-built surface at each security gate.
It was last reconciled with the built v1 surface through comprehensive adversarial
testing (FTY-073): the security test suite (`backend/tests/security/`) enforces the
controls below across the estimator pipeline, evidence retrieval (USDA/OFF/label/
official-source), LLM provider transport, and auth/profile/corrections/saved-foods/
weight data. Update it when architecture, data flows, or providers change.

## Assets

- Account identifiers and bearer tokens (v1 auth is stateless HMAC tokens; see
  Open Questions for the revocation gap). The mobile client persists the
  signed-in user's token at rest in the iOS keychain via `expo-secure-store`
  (FTY-090) — written atomically, never logged, and cleared on sign-out; see
  `security-baseline.md` for the on-device-credential-persistence control.
- Body profile data: height, weight, age, formula setting, goals, units.
- Food and exercise logs and their derived (parsed/resolved) items.
- Body-weight time series (canonical-kg entries).
- Attachments such as nutrition label images.
- User-specific memories, recipes, saved foods, aliases, and the append-only
  corrections (edit) history.
- Provider API keys (LLM, search, nutrition sources).
- Claude Code OAuth-session credential: the operator's Claude Code login session
  persisted in the `claude-config` Docker volume (a host secret, not baked into
  the image), shared by `api` and `worker` containers.
- Estimation prompts, evidence, and source metadata.

## Trust Boundaries

- iOS app to backend API.
- Backend API to database.
- Backend API to Redis/Celery workers.
- Workers to LLM providers (HTTP API-key-authenticated).
- Workers to local Claude Code subprocess (first-party CLI, operator's OAuth
  session).
- Workers to search, nutrition, OCR, barcode, and web sources.
- Workers to object storage.
- LLM output back into backend validators.

## Primary Threats

- Account takeover.
- Broken object-level authorization.
- Sensitive data in logs, prompts, analytics, or crash reports.
- Prompt injection from user input, fetched pages, OCR text, nutrition labels, or provider output.
- SSRF through source fetching.
- Memory poisoning through untrusted content.
- Provider key leakage.
- Dependency or GitHub Actions supply-chain compromise.
- Over-retention of attachments or raw prompts.
- Cross-user data leakage through global caches or estimator memory.

## Required Controls

- Object-level auth tests for user-owned resources.
- Rate limiting on auth endpoints (per-IP and per-account on login; per-IP on
  register) to bound online brute-force and credential-stuffing (FTY-118).
- Strict provider/tool allowlists (the `claude_code` subprocess provider enforces
  this by disabling every built-in Claude Code tool and MCP servers, so
  prompt-injection in untrusted input cannot trigger tool use or code execution).
- SSRF-hardened fetcher.
- Structured LLM output validation.
- Sanitized search queries.
- User-isolated memories.
- Redacted logs.
- Required PR review and CI.
- Dependency update automation.
- Explicit retention policies.

## Resolved In V1

The built v1 surface has answered the original open questions:

- **First auth path.** v1 ships **local email + password** auth with stateless,
  HMAC-SHA256-signed bearer tokens (`app/services/auth.py`, `app/security/`).
  Login is constant-time and does not reveal whether an email exists. Sign in with
  Apple / a hosted identity provider is deferred to a hosted-auth story.
- **Uploaded label image retention.** Resolved by `data-retention.md`: an uploaded
  nutrition-label image is **discarded by default** — retained only while needed for
  extraction and persisted (one user-owned `log_attachments` row) only on an
  explicit user save, with `ON DELETE CASCADE` from the user and the owning log
  event. No raw image is stored in the default flow.
- **Telemetry.** v1 ships **no** product telemetry/analytics. Logs are structured,
  redacted, and operational only. Any future telemetry must be opt-in or clearly
  documented before public launch (`security-baseline.md`).

## Open Questions

- **Application-level field encryption.** v1 relies on deployment-level database and
  object-storage encryption (FTY-072) and does not yet apply application-level
  encryption to any field; which fields (if any) warrant it once the data model is
  final is still open.
- **Bearer-token revocation.** v1 tokens are stateless with no server-side session
  or revocation, so a leaked token is valid until expiry. Server-side
  sessions/revocation are deferred to a hosted-auth story (tracked finding).

