---
id: FTY-087
state: merged
primary_lane: estimator
touched_lanes:
  - security-privacy
risk: high
tags:
  - llm-provider
  - claude-code
  - subscription
  - subprocess
  - prompt-injection
  - self-host
approved_dependencies: []
requires_context:
  - docs/contracts/llm-provider.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/standards/testing-standards.md
review_focus:
  - all-tools-disabled-sandboxed-subprocess
  - subscription-auth-via-local-cc-session-no-api-key
  - json-schema-structured-output-validated-against-pydantic
  - error-mapping-cc-missing-unauthed-nonjson
  - no-prompt-or-response-logging
autonomous: true
---

# FTY-087: Claude Code Subscription LLM Provider

## State

ready

## Lane

estimator (with a non-serializing security-privacy review focus)

## Dependencies

- none

## Outcome

A self-hoster who already pays for a Claude monthly plan can run the estimator
through their **locally installed, first-party Claude Code** session — paying
nothing per token — by setting `FATTY_LLM_PROVIDER=claude_code`. No
`FATTY_LLM_API_KEY` is required: Claude Code owns its own authentication
(`claude login`) and supplies the model from the active session/plan.

This story adds one new provider adapter behind the existing
`structured_completion(prompt, schema) -> validated object` contract. The adapter
invokes the local Claude Code in headless mode with **all tools disabled and
sandboxed**, requests JSON output constrained to the caller's schema, and returns
the raw dict for the base class to validate against the caller's Pydantic model —
exactly like every other provider. All existing BYO-API-key providers
(`openai`, `anthropic`, `openai_compatible`, `fake`) are unchanged.

This is the deliberately ToS-clean path: it wraps the first-party Claude Code
binary authenticated through the existing local session, rather than reusing
Claude Code's OAuth credentials in a homemade API client (that route is
ToS-gray, detectable, and billed per token as "extra usage" per Anthropic's own
docs). Wrapping the local binary is first-party, plan-covered, and incurs no
per-token billing.

## Scope

In `backend/app/llm/`:

1. **Config (`config.py`).**
   - Add `claude_code` to the `ProviderName` literal.
   - Relax `_check_provider_requirements` so `claude_code` is allowed **without**
     `FATTY_LLM_API_KEY`. Claude Code authenticates via its own local session, so
     a Fatty-side key is meaningless for it (and must not be required).
   - **Model is optional for `claude_code`.** Claude Code selects the model from
     the active session/plan, so `FATTY_LLM_MODEL` is not required. If a model is
     supplied, pass it through to the invocation (`--model`); if empty, let Claude
     Code use its session default. Document this in the contract and the field
     comment. (The existing requirement that `openai`/`anthropic`/
     `openai_compatible` need both key and model is unchanged.)
   - Keep `extra="forbid"`, `frozen=True`, and the existing tunables
     (`timeout_seconds`, `max_retries`) applying to `claude_code` too.

2. **Provider adapter (`providers/claude_code.py`).** A new `ClaudeCodeProvider`
   subclassing `Provider`, implementing `_complete(...)`. It invokes the local
   Claude Code in headless mode (e.g.
   `claude -p --output-format json --json-schema <schema-from json_schema_for(schema)>`,
   or the Claude Agent SDK equivalent), reads the structured JSON from stdout,
   and returns it as a `dict`. It reuses `json_schema_for(schema)` for the schema
   and never validates or logs the result itself — the base class owns validation
   and sanitized logging, identical to the OpenAI/Anthropic adapters.
   - **All tools disabled / sandboxed (security-critical, see below).** The
     invocation must run with every Claude Code tool turned off (no bash, no
     file read/edit, no web/fetch), no filesystem access, and no network beyond
     the model call itself. A prompt-injection inside untrusted food-log text
     must never be able to trigger tool use or code execution on the host.
   - **Subprocess invocation is a seam.** Factor the actual Claude Code
     invocation behind a small injectable callable/object (mirroring how
     `app.llm.transport.post_json` is the network seam for the HTTP providers),
     so unit tests drive success/failure deterministically with no real
     subprocess or live Claude Code. The default seam shells out to the real
     binary; tests inject a fake.
   - Honor `timeout_seconds` per attempt and let the base class's
     `_complete_with_retries` apply `max_retries` to transient failures.

3. **Factory (`factory.py`).** Wire `settings.provider == "claude_code"` to
   construct `ClaudeCodeProvider` **before** the `api_key is None` guard (that
   guard must not reject `claude_code`, which legitimately has no key). Pass
   `model` (possibly empty), `timeout_seconds`, and `max_retries`.

4. **Error mapping.** Map Claude Code outcomes onto the existing taxonomy
   (`errors.py`):
   - Binary not installed / not found on PATH, or not logged in / unauthenticated
     → `LLMConfigurationError` (not retryable) with a clear, content-free message
     pointing the operator at `claude login` (no prompt/response content).
   - Per-attempt timeout / spawn or transport hiccup → `LLMTransientError`
     (retryable, bounded by `max_retries`).
   - Non-zero exit with an error, or stdout that is not valid JSON / not a JSON
     object → `LLMResponseError` (not retried).
   - Schema-invalid (but well-formed JSON) output → handled by the base class as
     `StructuredOutputValidationError`, as for every provider.

## Non-Goals

- **Self-host packaging / install / `claude login` docs / health diagnostics** —
  that is **FTY-088**. This story does not document how to install Claude Code or
  add operator-facing setup/health checks.
- **Local-model / Ollama ergonomics** — that is **FTY-089**.
- **Vision / image input through `claude_code`** — text parse path only for this
  story; the `images` argument support for this provider is a deliberate
  follow-up non-goal. (`structured_completion` still accepts the keyword for
  contract compatibility; supplying images to `claude_code` is out of scope here
  and should fail fast rather than silently dropping them — treat as a follow-up.)
- **Any change to the existing `openai`/`anthropic`/`openai_compatible`/`fake`
  providers' behavior.**
- **No Fatty-managed OAuth, token DB, or credential storage** — Claude Code owns
  its own auth. Fatty stores nothing.

## Contracts

Touches the **LLM provider contract** (`docs/contracts/llm-provider.md`) — this
is the single big rock:

- Add `claude_code` to the `FATTY_LLM_PROVIDER` selector table/value list.
- Document that `claude_code` requires **no `FATTY_LLM_API_KEY`** (authenticated
  via the local Claude Code session) and that `FATTY_LLM_MODEL` is **optional**
  for it (Claude Code picks the model from the session/plan; supplied models are
  passed through).
- Keep the rest of the `FATTY_LLM_*` env contract and the
  `structured_completion(prompt, schema, *, images=None) -> validated object`
  signature **stable and unchanged**.
- Note the trust boundary is identical: Claude Code output is an untrusted
  analyst's output, trusted only after it validates against the caller's schema.
- Bump the contract version and note it is backward-compatible (a new opt-in
  provider value; existing providers and env vars behave exactly as before).

## Security / Privacy

Rated **high**: this provider executes a local subprocess, processes untrusted
food-log text, and crosses an authentication boundary (the operator's Claude
subscription). The controls:

- **All tools disabled / sandboxed.** This is the primary review focus. Claude
  Code ships with bash/read/edit/web tools. The invocation MUST disable every
  tool and deny filesystem and network access beyond the model call. Treat the
  prompt as untrusted (Fatty's "LLM is an untrusted analyst" principle): a
  prompt-injection in food-log text must be incapable of triggering tool use,
  file access, or code execution on the server. Tests must assert no tools are
  enabled in the constructed invocation.
- **No prompt or response logging.** Reuse the base class's sanitized logging —
  the adapter never logs the prompt, the raw stdout/response, or any model
  identifier beyond the stable `name` label. Error messages stay content-free
  (per `errors.py` and the security baseline): no prompt text, no response body,
  no stderr dump that could echo untrusted input.
- **Auth boundary.** No Fatty-managed credential: Claude Code authenticates via
  its own local session. Fatty never reads, stores, or logs the operator's
  Claude credentials or token. The "missing/unauthed" case maps to a
  content-free `LLMConfigurationError`.
- **Untrusted-output trust boundary unchanged.** Output is returned only after
  Pydantic validation by the base class; invalid output is rejected, never
  trusted.

## Acceptance Criteria

- `FATTY_LLM_PROVIDER=claude_code` loads valid `LLMSettings` with **no**
  `FATTY_LLM_API_KEY` and **no** `FATTY_LLM_MODEL`; supplying a model is accepted
  and passed through. Supplying a key is not required (and is not used) for
  `claude_code`.
- `build_provider` returns a `ClaudeCodeProvider` for `claude_code` and does not
  trip the `api_key is None` guard.
- A successful Claude Code invocation (via the injected seam) returns a
  schema-validated object through `structured_completion`, identical in shape to
  the other providers.
- The constructed invocation has **all Claude Code tools disabled** and no
  filesystem/extra-network access — asserted by a unit test inspecting the
  invocation the adapter builds.
- Error mapping holds: Claude Code missing/unauthed → `LLMConfigurationError`;
  per-attempt timeout/spawn failure → `LLMTransientError` (retried up to
  `max_retries`); non-zero/non-JSON/non-object stdout → `LLMResponseError`;
  well-formed-but-schema-invalid JSON → `StructuredOutputValidationError`.
- No prompt or raw response text appears in logs or error messages — asserted by
  a test capturing logs/exceptions for a failing call.
- The existing BYO-key providers are unchanged and their tests stay green.
- `docs/contracts/llm-provider.md` is updated (new selector value, no-key /
  optional-model semantics, version bump) and the rest of the `FATTY_LLM_*`
  contract is unchanged.

## Verification

- `make verify` from the backend passes (lint, types, tests).
- New unit tests for `ClaudeCodeProvider` with the Claude Code invocation
  **injected as a seam** (no real subprocess, no live Claude Code):
  - success → validated object out;
  - Claude Code missing / not-logged-in → `LLMConfigurationError`;
  - per-attempt timeout → `LLMTransientError` and the bounded-retry behavior;
  - non-JSON / non-object / error-exit stdout → `LLMResponseError`;
  - well-formed-but-invalid-against-schema JSON → `StructuredOutputValidationError`;
  - **assert no tools are enabled** in the constructed invocation;
  - **assert nothing sensitive is logged** (no prompt, no raw response) and error
    messages are content-free.
- Config tests: `claude_code` loads without key/model; key/model requirement for
  the other providers is unchanged.
- Existing provider tests remain green (no regression).

## Reference (for the author — not requires_context)

These are external references the author may consult; they are not Fatty docs and
must not be added to `requires_context`:

- Claude Code headless mode: https://code.claude.com/docs/en/headless
  (`claude -p`, `--output-format json`, structured/JSON output, tool-permission
  and sandbox flags).
- The Claude Agent SDK structured-outputs documentation (schema-constrained JSON
  output) as an alternative to shelling out to the binary.
- Anthropic's note that authenticating "through an existing local Claude Code
  session instead of ANTHROPIC_API_KEY" is supported for Claude Code monthly
  plans (the subscription, no-per-token path this story relies on).
- Pi's open-source prior art for context on the OAuth-reuse alternative (which we
  deliberately reject): `github.com/badlogic/pi-mono` and the `earendil-works/pi`
  `pi-claude-auth` work. We wrap the first-party binary instead.

## Readiness Sanity Pass

- **Product decision gaps:** none. The design is fully resolved — new
  `claude_code` selector, wrap the local first-party Claude Code in headless mode
  with all tools disabled, auth via the existing local session (no key, optional
  model), structured JSON validated by the existing base class, and the error
  mapping onto the existing taxonomy. No open product decisions remain.
- **Cross-lane impact:** primary lane estimator (`backend/app/llm/`). The
  security-privacy focus is a non-serializing review concern, not a second
  serializing lane — there is one touched lane beyond the primary, well under the
  ceiling. The one contract touched is `llm-provider.md`.
- **Security/privacy risk:** high — subprocess execution plus untrusted input
  plus an auth boundary. Mitigated by: invoking Claude Code with **all tools
  disabled and sandboxed** (no bash/file/web, no extra network), treating the
  prompt as untrusted, reusing the base class's sanitized no-prompt/no-response
  logging and content-free errors, storing no operator credentials, and keeping
  the untrusted-output trust boundary (Pydantic validation) intact. The
  all-tools-disabled assertion is an explicit test.
- **Verification path:** `make verify` plus new seam-injected unit tests covering
  success, CC-missing/unauthed → `LLMConfigurationError`, timeout → transient,
  non-JSON/invalid → response/validation errors, an assertion that no tools are
  enabled, and an assertion that nothing sensitive is logged — with existing
  providers staying green.
- **Assumptions safe for autonomy:** yes. The seam keeps the adapter unit-testable
  without a real Claude Code install (matching how the HTTP providers are tested
  against the `transport` seam), the scope is one cohesive vertical slice, and
  the contract change is additive and backward-compatible.
- **Sizing:** one cohesive slice with a single big rock — the LLM provider
  contract boundary (new selector value + relaxed key/model rules). It sits at
  the `review_focus` ceiling (5) but stays one author run: 4 `requires_context`
  docs and only one touched lane beyond the primary, both well under their limits.
  No split warranted; the three follow-ups (FTY-088 packaging/health, FTY-089
  local-model ergonomics, vision-via-claude_code) are explicitly carved out as
  non-goals to hold the line.
- **Release scope:** promoted to `ready` and pulled **into v1** (2026-06-28, user
  decision) — the v1 tag now gates on this story merging. It is the riskiest v1
  story (subprocess + auth + security), so expect close review.
