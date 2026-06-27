---
id: FTY-041
state: ready_with_notes
primary_lane: estimator
touched_lanes:
  - backend-core
  - security-privacy
review_focus:
  - secret-hygiene
  - structured-output-validation
  - provider-adapter-isolation
  - timeout-retry
risk: high
tags:
  - estimator
  - llm
  - providers
  - config
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/adr/0002-product-architecture.md
  - docs/security/security-baseline.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-041: LLM Provider Config

## State

ready_with_notes

## Lane

estimator

## Dependencies

- FTY-012

## Outcome

A Pi-inspired, config-driven provider layer lets a self-hoster point the estimator at OpenAI, Anthropic, or any OpenAI-compatible endpoint, exposing a schema-validated structured-completion call the pipeline can rely on.

## Scope

- Implement a provider-adapter abstraction supporting OpenAI, Anthropic, and OpenAI-compatible endpoints, selected and configured via environment/config (Pi-inspired provider model, implemented natively in Python).
- Expose a single `structured_completion` capability: given a prompt and a JSON schema, return schema-validated structured output (never trusted until validated). Per-provider implementation uses each provider's structured-output/tool-calling mechanism.
- Read provider keys and endpoints from environment/secret config only; never expose keys to clients; never log keys, full prompts, or raw responses with unnecessary personal context.
- Add timeouts, bounded retries, and sanitized logging to every provider call (coding standard).
- Provide a fake/in-memory provider for tests so CI makes no live model calls.

## Non-Goals

- The parse prompt and candidate schema (FTY-042) — this story provides the transport, not the estimator logic.
- Tool/function execution, search, or fetching (later estimator stories).
- A bundled default API key or default hosted provider.
- Streaming or chat/conversational interfaces (the app is not a chatbot).

## Contracts

- The provider adapter interface and the `structured_completion(prompt, schema) -> validated object` signature become an estimator contract consumed by FTY-042.
- The provider configuration env var names become a contract for self-host docs (FTY-072).

## Security / Privacy

The LLM is treated as an untrusted analyst: outputs are schema-validated before use. Keys live in env/secret managers, never in the repo, never sent to clients, never logged. Prompts and responses are logged only in sanitized form without unnecessary personal context. Provider calls are timed out and retried with redacted traces. Rated high: secret handling + untrusted-output trust boundary.

## Acceptance Criteria

- Configuring OpenAI, Anthropic, or an OpenAI-compatible endpoint via env selects the right adapter.
- `structured_completion` returns output validated against the supplied schema; schema-invalid output is rejected (negative test) and never returned as trusted.
- No keys, full prompts, or raw responses appear in logs; redaction is tested.
- Calls enforce timeouts and bounded retries.
- The fake provider drives all tests; CI makes no live calls.
- `make verify` passes.

## Verification

- Run `make verify` with the fake provider, including a negative test for schema-invalid output and a logging-redaction test.
- Optionally, a manually-run, key-gated smoke test against a real provider (excluded from CI).

## Planning Notes

- The precise structured-output mechanism per provider (JSON mode vs tool calling) is an implementation detail; the contract is "schema-validated object out."
- Default timeout/retry values are documented tunables.

## Readiness Sanity Pass

- Product decision gaps: none blocking — provider set, structured-output contract, and mocked-test approach resolved.
- Cross-lane impact: provides the LLM transport FTY-042 depends on; defines self-host provider config.
- Security/privacy risk: high; secrets + untrusted output, mitigated by env-only keys, schema validation, and redacted logging.
- Verification path: `make verify` with fake provider + redaction/negative tests.
- Assumptions safe for autonomy: yes; per-provider structured-output mechanics and timeouts are documented tunables (notes).
