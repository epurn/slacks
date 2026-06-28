---
id: FTY-089
state: merged
primary_lane: estimator
touched_lanes: []
risk: medium
tags:
  - llm-provider
  - self-host
  - local-model
  - openai-compatible
  - keyless
  - zero-cost
  - contracts
  - docs
  - v1.x
approved_dependencies: []
requires_context:
  - docs/contracts/llm-provider.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
review_focus:
  - keyless-openai_compatible-allowed-but-base-url-and-model-still-required
  - no-empty-bearer-header-when-keyless
  - keyed-providers-unchanged-no-regression
  - local-model-path-documented
autonomous: true
---

# FTY-089: Keyless local-model (OpenAI-compatible) path

## State

ready

## Lane

estimator

## Dependencies

- _(none)_

## Outcome

A self-hoster can run a **local model runtime** — Ollama, LM Studio, or vLLM —
and point Fatty at it with **no API key**, as the truly-free, zero-per-token,
ToS-clean estimator path. The `openai_compatible` provider already speaks the
exact OpenAI Chat Completions wire format these runtimes expose locally; the only
friction today is that `LLMSettings._check_provider_requirements` requires
`FATTY_LLM_API_KEY` for **every** non-`fake` provider, forcing a user pointing at
a keyless local endpoint to invent a dummy key — and nothing documents the path.

After this story:

- `openai_compatible` validates and runs **without** `FATTY_LLM_API_KEY`, while
  still requiring `FATTY_LLM_BASE_URL` and `FATTY_LLM_MODEL` (fail-closed on
  either missing).
- When no key is configured, the OpenAI adapter sends **no** `Authorization`
  header (never `Bearer ` with an empty value).
- The keyed path (real OpenAI, Anthropic, Together, and a keyed
  `openai_compatible`) is **unchanged** — if a key is provided it is still sent.
- The local-model path is documented end-to-end (provider contract, self-host
  `README`, `.env.example`) as the zero-cost option.

## Scope

One vertical slice in the estimator lane (`backend/app/llm/`) plus the docs that
describe its config contract.

1. **Relax the validator for keyless `openai_compatible`.** In
   `backend/app/llm/config.py`, `_check_provider_requirements` currently rejects
   any non-`fake` provider that has no key. Change it so that **only**
   `openai_compatible` may run keyless, while every other non-`fake` provider
   (`openai`, `anthropic`) still requires a key. For `openai_compatible`:
   - `FATTY_LLM_BASE_URL` is **still required** (fail closed if missing),
   - `FATTY_LLM_MODEL` is **still required** (fail closed if missing),
   - `FATTY_LLM_API_KEY` is **optional** (allowed to be absent/empty).
   Keep the existing message/precedence behavior so a misconfigured keyed
   provider still fails the same way. Do not change the `fake` short-circuit.

2. **Omit the auth header when keyless.** Thread the optional key through the
   factory and adapter so a keyless build does not emit a blank credential:
   - In `backend/app/llm/factory.py`, stop hard-failing on a `None` key for the
     OpenAI/`openai_compatible` branch. The anthropic branch keeps requiring a
     key (it already cannot be reached keyless after step 1). Pass the key
     through as optional (e.g. `api_key=settings.api_key.get_secret_value() if
     settings.api_key else None`).
   - In `backend/app/llm/providers/openai.py`, accept `api_key: str | None` and,
     when it is falsy, send the request with **no** `Authorization` header rather
     than `{"Authorization": "Bearer "}`. When a key is present, send
     `Bearer <key>` exactly as today. This is the only wire-behavior change and
     it is gated on "no key configured".
   - `AnthropicProvider` is untouched.

3. **Document the local-model path (the user-facing deliverable).**
   - `docs/contracts/llm-provider.md`: update the config table and the
     "Invalid or inconsistent configuration" note so `openai_compatible` no
     longer requires a key (key is optional; base URL + model still required),
     and bump the contract Version with a one-line changelog entry. Add a short
     note that a keyless `openai_compatible` endpoint is the intended **local /
     LAN** use (Ollama/LM Studio/vLLM), and that the existing base-URL scheme
     expectations still apply.
   - `README.md` (self-host section + the LLM bullet): add the zero-cost local
     option — run Ollama/LM Studio/vLLM, set
     `FATTY_LLM_PROVIDER=openai_compatible`,
     `FATTY_LLM_BASE_URL=http://localhost:11434/v1` (Ollama style),
     `FATTY_LLM_MODEL=<local model>`, **no key needed**.
   - `.env.example`: amend the `openai_compatible` lines to state the key is
     optional for keyless local endpoints, with the Ollama-style example
     (`http://localhost:11434/v1`) and a local model name; keep the keyed
     examples intact.

4. **(Optional) Surface availability in diagnostics.** Only if the codebase
   already has a health/sources provider-status surface that other providers
   report through, extend it to reflect the configured `openai_compatible`
   endpoint **consistently with the existing pattern** (label only — never the
   URL host internals beyond what other providers already expose, never a key).
   If no such surface exists, skip this — do not invent one.

## Non-Goals

- The `claude_code` provider (FTY-087) and its setup/onboarding (FTY-088).
- Adding a **new** provider selector or runtime auto-detection — reuse the
  existing `openai_compatible` selector; do not add an `ollama`/`lmstudio` value.
- Changing the keyed providers' behavior in any way (OpenAI, Anthropic, Together,
  or a keyed `openai_compatible` must be byte-for-byte unchanged).
- Auto-installing or managing Ollama/LM Studio/vLLM, or shipping a bundled local
  model — docs only point at the user's own runtime.
- Weakening the egress/scheme/SSRF expectations for **remote** `FATTY_LLM_BASE_URL`
  values; the local/LAN case is the documented intended use, not a relaxation of
  remote checks.
- Any change to secret storage/logging — keyless means there is no secret to
  protect, and the keyed `SecretStr` handling is untouched.

## Contracts

- **`docs/contracts/llm-provider.md` (changed).** A small, backward-compatible
  config-contract change: `openai_compatible` no longer requires
  `FATTY_LLM_API_KEY` (key optional; `FATTY_LLM_BASE_URL` and `FATTY_LLM_MODEL`
  still required). Bump the contract Version and add the changelog line. This is
  the single "big rock" in the story (a public config-contract change) and is the
  reason the slice stays narrow — no schema change, no new trust boundary, no new
  provider.
- The `FATTY_LLM_` env-var names and the `structured_completion(...)` signature
  are **unchanged**; existing keyed deployments behave exactly as before.

## Security / Privacy

- **Intended use is local / LAN.** A keyless endpoint is appropriate for a
  loopback or LAN model runtime that does not authenticate. Document this as the
  intended use; do **not** present keyless as a way to reach a remote/public
  endpoint.
- **No weakening of egress checks.** The existing base-URL scheme handling in the
  transport (and any SSRF/egress posture in `security-baseline.md`) is unchanged.
  Keyless only affects whether an `Authorization` header is sent — it does not
  change which URLs are reachable.
- **No empty credential on the wire.** The adapter must never send
  `Authorization: Bearer ` with an empty value; it sends a real `Bearer <key>` or
  no header at all. This avoids a malformed/ambiguous credential being logged or
  rejected by upstreams.
- **No secret-handling change.** No key means nothing to protect; the keyed path
  keeps `SecretStr` (never logged, never returned, never serialized). Per the
  provider contract, keys/prompts/responses remain unlogged.
- Rated **medium**: it edits a security-relevant validator and the auth-header
  wire path, but it neither broadens egress nor introduces a new trust boundary;
  the change is a fail-closed relaxation confined to one provider plus docs.

## Acceptance Criteria

- A keyless `openai_compatible` config (`FATTY_LLM_PROVIDER=openai_compatible`,
  `FATTY_LLM_BASE_URL` set, `FATTY_LLM_MODEL` set, **no** `FATTY_LLM_API_KEY`)
  **validates** (no `ValidationError`).
- A keyless `openai_compatible` request sends **no** `Authorization` header (and
  in particular never `Bearer ` with an empty key).
- `openai_compatible` **without** `FATTY_LLM_BASE_URL` still fails closed at load.
- `openai_compatible` **without** `FATTY_LLM_MODEL` still fails closed at load.
- `openai` and `anthropic` without a key **still fail closed** at load (keyless is
  allowed only for `openai_compatible`).
- A **keyed** `openai_compatible` request and a **keyed** `openai` request still
  send `Authorization: Bearer <key>` exactly as before (no regression).
- `docs/contracts/llm-provider.md`, `README.md`, and `.env.example` document the
  keyless local-model path (Ollama/LM Studio/vLLM, `openai_compatible`,
  base URL + model, no key) as the zero-cost option, and the contract Version is
  bumped with a changelog line.
- `make verify` passes.

## Verification

- `make verify` from the backend (lint, type-check, tests).
- New/updated unit tests in `backend/tests/llm/` (config + provider):
  - keyless `openai_compatible` settings **validate** (base URL + model present,
    no key);
  - the OpenAI adapter built keyless sends a request with **no** `Authorization`
    header (assert the header is absent / not `Bearer ` + empty) — assert against
    the `transport.post_json` call args (e.g. monkeypatch/spy), no live egress;
  - keyless `openai_compatible` **missing base URL** raises `ValidationError`;
  - keyless `openai_compatible` **missing model** raises `ValidationError`;
  - keyless `openai` and keyless `anthropic` still raise `ValidationError`;
  - a **keyed** `openai_compatible` and a **keyed** `openai` adapter still send
    `Authorization: Bearer <key>` (regression guard).
- Docs check: the provider contract, README, and `.env.example` reflect the
  keyless local path and the contract Version is bumped.

## Planning Notes

- **Reuse `openai_compatible`; do not add a selector.** The wire format is
  identical to what Ollama/LM Studio/vLLM expose; the whole value of the story is
  that no new provider is needed. Resist adding an `ollama` value.
- **Smallest viable wire change.** The only behavioral code change is "omit the
  auth header when keyless." Thread the optional key from validator → factory →
  adapter; everything else (payload, schema, retries, error mapping) is
  unchanged.
- **Keep the validator precedence intact.** Step 1 must not change how a keyed
  provider with a missing model/base-URL fails — only carve out keyless
  `openai_compatible`. The existing tests in `backend/tests/llm/test_config.py`
  for keyed providers should keep passing untouched.
- **Diagnostics are optional and pattern-matched.** Only extend an existing
  provider-status surface if one exists; do not introduce new health endpoints in
  this slice.

## Readiness Sanity Pass

- **Product decision gaps:** none. All design decisions are resolved — reuse
  `openai_compatible` (no new selector), keyless allowed only for that provider,
  base URL + model still required, omit the auth header when keyless, keyed paths
  unchanged, docs cover Ollama/LM Studio/vLLM. Held as `candidate` **only** for
  release sequencing. Promoted to `ready` and pulled **into v1** (2026-06-28,
  user decision); the v1 tag gates on it. Independent of FTY-087/088.
- **Cross-lane impact:** none beyond the primary `estimator` lane.
  `touched_lanes: []` (well under the 2-beyond-primary ceiling). The only public
  surface touched is the LLM provider config contract — one "big rock" (a public
  contract change), so it is **not** bundled with any other big rock (no schema
  migration, no new trust boundary, no new provider). Sizing is comfortably
  inside all limits: `touched_lanes` 0, `review_focus` 4 (ceiling 5),
  `requires_context` 3 (ceiling 8) — a single-slice story, no split needed.
- **Security/privacy risk:** medium. It edits a security-relevant validator and
  the auth-header wire path, but it is a fail-closed **relaxation scoped to one
  provider** (base URL + model still required), introduces no new egress path or
  trust boundary, and leaves keyed secret handling and remote SSRF expectations
  unchanged. The keyless case never puts an empty credential on the wire.
- **Verification path:** `make verify` plus targeted unit tests — keyless config
  validates; keyless adapter sends no auth header; missing base URL/model fails
  closed; keyless `openai`/`anthropic` still fail; keyed `openai`/
  `openai_compatible` still send `Bearer` (regression guard). All offline (spy on
  `transport.post_json`; no live egress).
- **Assumptions safe for autonomy:** yes. The contract, code touch-points
  (`config.py`, `factory.py`, `providers/openai.py`), docs targets (contract,
  README, `.env.example`), and the test matrix are all specified; the optional
  diagnostics step is explicitly skip-if-absent. No interview needed; the only
  reason this is not yet `ready` is v1 release sequencing.
