---
id: FTY-130
state: ready
primary_lane: governance
touched_lanes: []
review_focus:
  - subprocess-egress-boundary-added
  - claude-config-oauth-asset-added
  - mitigations-match-provider-code
  - no-other-provider-detail-lost
  - public-repo-boundary
risk: low
tags:
  - docs
  - security
  - threat-model
  - claude-code
approved_dependencies: []
requires_context:
  - docs/security/threat-model.md
  - docs/security/security-baseline.md
  - docs/contracts/llm-provider.md
autonomous: true
---

# FTY-130: Reconcile The Threat Model With The `claude_code` Subprocess Provider

## State

ready

## Lane

governance

## Dependencies

- None to schedule. The `claude_code` subprocess provider is **already merged**
  (FTY-087/088/089); this reconciles the threat model with that shipped surface.
  Authors in parallel with FTY-128 (`CHANGELOG.md`), FTY-129
  (`target-calculator.md`), and FTY-142 (`README.md` / `contracts/README.md` /
  `system-overview.md`) — **no file overlap**: this story owns
  **`docs/security/threat-model.md` and nothing else**.

## Outcome

`threat-model.md` covers the `claude_code` subprocess provider it currently
omits. The document opens (~lines 1–8) by asserting it "was last reconciled with
the built v1 surface … through FTY-073" and instructs updating it "when
architecture, data flows, or providers change" — but the `claude_code` provider
(FTY-087/088/089) shipped **after** that reconciliation and is entirely absent
(a grep for `claude` / `subprocess` / `oauth` in the file returns nothing). That
provider introduces a new egress path and a new sensitive credential that the
threat model must account for, given its own update rule.

Two specific gaps to close:

1. **A new trust boundary.** The Trust Boundaries list (~lines 27–34) has only a
   generic "Workers to LLM providers". The `claude_code` provider adds a
   distinct path: **worker → local first-party `claude` CLI subprocess →
   Anthropic over the operator's own OAuth / monthly-plan session**. This is a
   different boundary shape from the HTTP API-key providers (a local process
   invocation, not a keyed HTTPS client) and warrants its own line.
2. **A new sensitive asset.** The Assets list (~lines 11–24) names "Provider API
   keys (LLM, search, nutrition sources)" but the `claude_code` path uses **no
   API key** — it authenticates via the `claude login` session persisted in the
   `claude-config` Docker volume. The README (~:127) and Compose both call this
   volume a **host secret** carrying OAuth session credentials, yet it is not in
   the asset inventory.

## Scope

- **Edit only `docs/security/threat-model.md`.**
- **Add the subprocess egress trust boundary** to the Trust Boundaries list:
  the worker → local `claude` CLI subprocess → Anthropic-over-the-operator's-
  OAuth-session path, noted as distinct from the keyed HTTP LLM-provider
  boundary.
- **Add the `claude-config` OAuth-session credential as an asset** to the Assets
  list: the operator's Claude Code session in the persistent `claude-config`
  Docker volume — a host secret, not baked into the image, shared by `api` and
  `worker`. (The existing "Provider API keys" asset line can stay; this is an
  additional, distinct credential type — a session, not a key.)
- **Note the mitigations** already enforced by the provider code (so the threat
  model records why the new boundary is acceptable, matching the
  reject/control style of the existing Required Controls): the invocation runs
  with a **fixed argv and no shell**, **every Claude Code tool disabled** and **no
  MCP servers** (so a prompt-injection in untrusted log text cannot trigger tool
  use, file access, or host code execution), the **prompt is passed on stdin**,
  and the **only network the invocation performs is Claude Code's own model
  call**; Fatty holds no key and stores/logs no credential. Verify these against
  `backend/app/llm/providers/claude_code.py` (the module docstring + the
  tool-deny list) before asserting them.
- **Fold the prompt-injection control into the existing posture.** The Primary
  Threats list already names "Prompt injection from … provider output" and
  Required Controls names "Strict provider/tool allowlists" and "Structured LLM
  output validation" — note that the `claude_code` path's tools-fully-disabled
  invocation is the concrete realisation of that allowlist for the subprocess
  provider (a one-line tie-in is enough; do not duplicate the whole controls
  list).

## Non-Goals

- **No code change** — the provider already ships with these mitigations; this
  documents the boundary and asset, it does not alter `backend/`.
- **Do not remove or rewrite** the existing assets, boundaries, threats,
  controls, Resolved-in-V1, or Open-Questions content — this is **additive**.
  In particular, do not touch the bearer-token-revocation or field-encryption
  Open Questions (documented deferrals).
- **Do not document the OAuth/subscription-bridge route** — that approach was
  **rejected** (ToS-gray, per-token billed); the shipped path wraps the
  first-party CLI. The threat model must describe the *shipped* `claude_code`
  subprocess provider only, not the rejected bridge.
- **Do not** add private automation detail, host paths, or credential contents —
  `threat-model.md` is in the **public** repo; describe the asset class (the
  session volume is a host secret) without exposing any secret or machine path.
- No changes to `security-baseline.md` or `llm-provider.md` (referenced for
  consistency only).

## Contracts

- **None.** No request/response or schema change. `llm-provider.md` is
  referenced to keep the boundary description consistent with the documented
  provider adapter contract, but is **not modified**.

## Security / Privacy

- This **is** a security-doc edit, and its purpose is to make the security
  posture honest: the threat model currently under-describes the as-built
  surface (a missing egress boundary and a missing credential asset), which its
  own update rule forbids. Closing the gap is a net security-documentation
  improvement. The risk in the change itself is leaking the credential or a host
  path into the public repo — explicitly fenced off in Non-Goals (describe the
  asset class, never its contents). Rated **low**.

## Acceptance Criteria

- The Trust Boundaries list includes the worker → local `claude` CLI subprocess
  → Anthropic-over-operator-OAuth egress path as a distinct boundary.
- The Assets list includes the `claude-config` OAuth-session credential (the
  Claude Code session volume) as a host secret, distinct from API keys.
- The new boundary records the provider's mitigations (fixed argv, no shell, all
  tools disabled, no MCP, prompt on stdin, sole network is the model call,
  no key/credential stored or logged), and these match
  `backend/app/llm/providers/claude_code.py`.
- The prompt-injection / tool-allowlist tie-in for the subprocess provider is
  noted without duplicating the existing controls list.
- All existing threat-model content (assets, boundaries, threats, controls,
  resolved items, open questions) is preserved — the change is additive.
- No credential contents, host paths, or private automation detail appear (public
  repo boundary intact).
- `make verify` passes (governance boundary + docs checks).

## Verification

- `make verify` (governance boundary + docs/link checks); public-repo boundary
  check stays green.
- Manual diff confirming the two additions (boundary + asset) and the mitigation
  note, cross-checked against `claude_code.py` (the tool-deny list, the
  fixed-argv/no-shell/stdin invocation), and confirming nothing existing was
  dropped.

## Planning Notes

- **Source of truth for the mitigations** is `claude_code.py` — its module
  docstring states the tools-fully-disabled, no-MCP, fixed-argv-no-shell
  posture, and `_BUILTIN_TOOLS` is the explicit deny list. The author asserts
  only what the code enforces.
- **Asset framing:** the session is a *session credential*, materially different
  from an API key (no key exists on this path); state it as such so the
  inventory is accurate rather than collapsing it into the API-keys line.
- **No evidence research warranted** — this reconciles a security doc with
  shipped code; it settles no health/nutrition/behavioural question.

## Readiness Sanity Pass

- **Product decision gaps:** none — the provider and its mitigations are shipped;
  this documents the boundary and asset they introduce.
- **Cross-lane impact:** governance (security docs) only, **no touched lanes**.
  **Single boundary, zero big rocks:** the new untrusted-input/egress *boundary*
  it describes already shipped in FTY-087 — this story only **documents** it (no
  new code boundary is introduced here), no migration, no contract change. Owns
  `threat-model.md` exclusively — no overlap with FTY-128/129/142.
- **Size:** `review_focus` = 5 (at ceiling), `requires_context` = 3 (under 8).
  One story.
- **Security/privacy risk:** low — additive security-doc accuracy; the only
  hazard (leaking the credential / host path) is fenced off.
- **Verification path:** `make verify` + a code-cross-checked, additive-only
  read-through diff.
- **Assumptions safe for autonomy:** yes — the two gaps, their list locations,
  the mitigation source file, and the additive-only constraint are all explicit.
