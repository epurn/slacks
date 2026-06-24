# Threat Model

This is the initial threat model. Update it when architecture, data flows, or providers change.

## Assets

- Account identifiers and sessions.
- Body profile data: height, weight, age, formula setting, goals.
- Food and exercise logs.
- Attachments such as nutrition label images.
- User-specific memories, recipes, aliases, and corrections.
- Provider API keys.
- Estimation prompts, evidence, and source metadata.

## Trust Boundaries

- iOS app to backend API.
- Backend API to database.
- Backend API to Redis/Celery workers.
- Workers to LLM providers.
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
- Strict provider/tool allowlists.
- SSRF-hardened fetcher.
- Structured LLM output validation.
- Sanitized search queries.
- User-isolated memories.
- Redacted logs.
- Required PR review and CI.
- Dependency update automation.
- Explicit retention policies.

## Open Questions

- Which hosted auth provider will be used first?
- Which fields require application-level encryption in v1?
- What exact retention period applies to uploaded nutrition label images?
- What telemetry, if any, is acceptable for hosted users?

