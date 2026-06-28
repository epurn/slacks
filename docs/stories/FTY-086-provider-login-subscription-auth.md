---
id: FTY-086
state: candidate
primary_lane: estimator
touched_lanes:
  - security-privacy
risk: high
tags:
  - llm-provider
  - auth
  - subscription
  - oauth
  - self-host
approved_dependencies: []
requires_context:
  - docs/architecture/system-overview.md
  - docs/security/threat-model.md
  - docs/security/security-baseline.md
---

# FTY-086: Provider Login (Subscription / OAuth Auth) for Self-Host LLM Access

## State

candidate

> **SUPERSEDED — planned (2026-06-28) into FTY-087 / FTY-088 / FTY-089.** This was
> the umbrella idea ("log in with your provider"). A `plan-stories` pass resolved
> the approach and **rejected the OAuth/subscription-bridge route**: per Pi's own
> docs, reusing Claude Code's OAuth credentials from a third-party client is
> ToS-gray, detectable, and **billed per token** (extra usage, not plan-covered) —
> so it does not meet the user's "no extra spend" goal. The resolved design
> instead **wraps the local, first-party Claude Code** (subscription-auth via the
> existing `claude login` session, plan-covered, ToS-clean, tools disabled), plus
> a truly-free **local-model** path. Decomposition:
>
> - **FTY-087** — `claude_code` provider: wrap local Claude Code headless
>   (`claude -p --output-format json --json-schema`), tools fully disabled,
>   subscription auth, no API key. (estimator + security-privacy)
> - **FTY-088** — self-host packaging/setup: install Claude Code + `claude login`
>   + provider selection + health diagnostics. (infra + docs; depends on 087)
> - **FTY-089** — keyless `openai_compatible` for local models (Ollama/LM Studio)
>   + docs — the zero-cost path. (estimator)
>
> This file is kept for history; do not implement it directly. Build 087/088/089.

## Lane

estimator (+ security-privacy)

## Problem / Outcome

A self-hoster with a Claude/ChatGPT **subscription** and no per-token API budget
can authenticate Fatty's estimator against their subscription and run real
estimations — without pasting a paid API key. "Log in with your provider" rather
than "paste an API key."

## Evidence from the v1 manual test (2026-06-28)

Out of the box (`FATTY_LLM_PROVIDER=fake`), logging "2 eggs and a banana, then a
30 minute run" failed: `estimation_runs` recorded `status=failed`,
`error=provider_error`, `trace=[{"step":"parse","status":"failed"}]`. The fake
provider raises on the first LLM call (parse), so **free-text estimation
hard-fails**. This contradicts `.env.example`'s claim that `fake` "degrades
gracefully to model-prior-with-status" — parse needs a real model, so there is no
graceful path for free-text without a provider. (Barcode/OFF paths that don't use
the parse LLM may still work.) Two things fall out: a **short-term docs-accuracy
fix** to `.env.example` (stop claiming graceful degradation for free-text), and
this story (the real fix: let self-host users authenticate a provider without a
paid key).

## Likely Scope (sketch — to be refined)

- A subscription/OAuth-based auth path for the LLM provider config, alongside the
  existing API-key path (don't remove key support).
- Token acquisition + secure local storage + refresh, honoring the discard/
  minimization and secret-handling rules (no token in logs, `SecretStr`, etc.).
- Surface availability via the existing provider/health diagnostics so operators
  see whether subscription auth is configured and valid.
- Self-host docs for the login flow.

## Open Questions (must resolve before `ready`)

- **Which providers / which mechanism?** Anthropic and OpenAI subscriptions do
  not expose a general OAuth "use my Claude/ChatGPT plan via API" path the way
  API keys do. Is the realistic v1.x answer: (a) bridge a **local Claude Code /
  subscription session** via the `openai_compatible` endpoint to a local proxy,
  (b) integrate a **local model** runtime (Ollama / LM Studio) as the
  zero-cost default for self-host, and/or (c) a true OAuth device flow if/where a
  provider supports it? These are very different stories.
- **ToS / licensing** of routing a subscription session through a self-hosted
  server — must be verified per provider before building.
- **Security:** where session tokens live, rotation, blast radius if the box is
  compromised (ties into the threat model).
- Scope split: this is likely **several** stories (a provider-auth contract, the
  proxy/local-model adapter, the mobile/setup UX), not one.

## Non-Goals (for now)

- Not a v1 blocker — v1 ships API-key + `fake` providers; this is v1.x.
- No removal of the existing API-key provider path.

## Security / Privacy

High: introduces a new credential type (subscription/session tokens) and a new
auth/egress path. Must extend the threat model and obey secret-handling +
data-minimization before any implementation.

## Why candidate, not ready

The core mechanism is undecided (subscription-bridge vs local-model vs OAuth) and
has ToS/security questions that make autonomous implementation unsafe. Needs a
`plan-stories` pass to pick an approach and split into scoped, verifiable stories.
