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
- Codex auth/session/cache state: Codex CLI state under `CODEX_HOME`, mounted in
  the `codex-config` Docker volume (a host secret, not baked into the image),
  shared by `api` and `worker` containers. This asset is distinct from provider
  API keys and from the Claude Code OAuth-session volume; it may contain saved
  Codex auth, sessions, logs, caches, and other CLI-owned state.
- Estimation prompts, evidence, and source metadata.

## Trust Boundaries

- iOS app to backend API.
- Backend API to database.
- Backend API to Redis/Celery workers.
- Workers to LLM providers (HTTP API-key-authenticated).
- Workers to local Claude Code subprocess (first-party CLI, operator's OAuth
  session).
- Workers to local Codex subprocess (first-party `codex exec` CLI, saved Codex
  auth under `CODEX_HOME` or an optional child-only `CODEX_API_KEY`) and then to
  the OpenAI/ChatGPT/Codex service egress performed by the CLI. This is separate
  from direct HTTP API-key providers, OpenAI-compatible/OpenRouter endpoints,
  local-model runtimes, and the `claude_code` provider. The adapter constrains
  the boundary by using fixed argv with no shell; putting the prompt on stdin,
  not argv; running from a dedicated empty temp workdir; using an ephemeral run
  with JSON Schema output; setting the Codex sandbox to read-only with approvals
  disabled/fail-closed; avoiding web search, user/project config, rules, and MCP
  servers; forwarding only an explicit child environment allowlist; forwarding no
  Slacks secrets except the optional child-only `CODEX_API_KEY`; deleting temp
  schema and image files after the call; and logging no prompt, image data, raw
  output, raw stderr, key, auth material, or `CODEX_HOME` contents. The
  `codex-config` volume is a host secret and is not baked into the image.
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
  prompt-injection in untrusted input cannot trigger tool use or code execution;
  the `codex` subprocess provider enforces the same control class with
  config/rules/MCP/web-search avoidance, read-only sandboxing, approvals disabled
  fail-closed, fixed no-shell argv, stdin-only prompt delivery, and a child env
  allowlist).
- SSRF-hardened fetcher.
- Structured LLM output validation, including subprocess provider JSON Schema
  output followed by local JSON parsing and Pydantic validation before any LLM
  result is trusted.
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
  event. No raw image is stored in the default flow. The unified text+image log
  submission (FTY-374) reaches the **same retained-only-while-needed rule via a
  transient DB row instead of an in-request buffer** — required because the
  async worker's ids-only job payload forbids putting image bytes on the queue:
  images are persisted at create marked `transient`, fail-closed validated
  (size/type/signature, at most 4 per submission) before any persistence or
  model call, sent to the LLM/vision provider only (never search/fetch, logs,
  queue, or run traces), and hard-deleted by the worker in the same transaction
  as the event's terminal estimation status unless the user explicitly chose
  `save=true`.
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
