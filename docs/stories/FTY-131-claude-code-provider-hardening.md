---
id: FTY-131
state: ready
primary_lane: estimator
touched_lanes:
  - security-privacy
review_focus:
  - subprocess-env-allowlist-no-secret-leak
  - stdout-size-cap-parity
  - transient-exit-retryable
  - auth-marker-anchoring
  - no-stderr-or-secret-leak
risk: medium
tags:
  - llm-provider
  - claude-code
  - security
  - subprocess
  - fail-closed
approved_dependencies: []
requires_context:
  - docs/contracts/llm-provider.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
  - docs/standards/coding-standards.md
autonomous: true
---

# FTY-131: Harden the Claude Code Subprocess Provider (estimator)

## State

ready

## Lane

estimator

## Dependencies

- **None to schedule.** `approved_dependencies: []` — every line this story
  touches is already merged (FTY-087 created `claude_code.py`; FTY-113/114
  established the transport size-cap and the transient/retry taxonomy this story
  mirrors). It edits one estimator file plus its tests.
- **Serialization note:** this is one of four estimator-lane release-audit
  fix-stories (FTY-131/132/135/137) that all serialize on the estimator lane by
  changed-file path. They touch **different** files (`llm/providers/claude_code.py`
  here vs `estimator/official_step.py`, `estimator/evidence_utils.py` +
  `exercise_step.py`/`label_step.py`, and `estimator/hardened_fetch.py`), so there
  is no content overlap — but they cannot author simultaneously. **Rebase on
  whatever estimator work merges first** before opening the PR.

## Outcome

The `claude_code` provider's three stated-but-unenforced safety properties become
real, closing a secret-exposure gap and bringing its failure handling to parity
with the HTTP transport.

1. **The subprocess inherits the full parent environment.** `run_claude_code`
   (`backend/app/llm/providers/claude_code.py` ~120–127) calls `subprocess.run`
   with **no `env=`**, so the `claude` child inherits every variable the API/worker
   process holds — including `FATTY_AUTH_SECRET` (the bearer-token HMAC key),
   `FATTY_FDC_API_KEY`, `FATTY_SEARCH_API_KEY`, `POSTGRES_PASSWORD`, and any other
   provider secret. The module's docstring promises Fatty "holds no key and stores
   no credential" and that a prompt-injection "cannot trigger tool use, file
   access, or code execution" — but if the binary (or anything it spawns) ever read
   its environment, every Fatty secret is sitting there. The least-privilege
   guarantee is asserted, not enforced.
2. **stdout is captured unbounded.** `capture_output=True` reads the child's stdout
   with no size cap, unlike the HTTP transport's `MAX_RESPONSE_BYTES`
   (`backend/app/llm/transport.py` ~35, ~90–91) and `hardened_fetch`'s `max_bytes`.
   A runaway or hostile reply can balloon worker memory.
3. **Transient/busy exits are not retryable.** Any non-zero, non-auth exit maps to
   a non-retryable `LLMResponseError` (~224–230). The HTTP transport already
   reclassifies `429`/`408`/`425`/`5xx` as retryable `LLMTransientError`
   (FTY-113); a `claude` process that exits busy/rate-limited/transient should get
   the same treatment instead of failing the run outright.
4. **The auth-marker set over-matches.** `_AUTH_FAILURE_MARKERS` (~69–77) includes
   the bare substrings `"login"` and `"log in"`, which appear in plenty of
   unrelated stderr ("logging in to…", "see the changelog", words containing
   "login"), so a generic failure can be misclassified as an auth failure and
   surface the wrong remediation.

## Scope

All edits are in `backend/app/llm/providers/claude_code.py` and its test module.

- **Pass a curated `env=` allowlist to the subprocess.** Build the child
  environment from an explicit allowlist of only the variables the `claude` binary
  genuinely needs to find itself, locate its session/config, and run — discover the
  exact set empirically (do **not** guess). The expected floor is `PATH`, `HOME`,
  `CLAUDE_CONFIG_DIR` (the session/credential dir FTY-088 mounts), and the locale
  vars (`LANG`/`LC_ALL`/`LC_CTYPE`); include whatever else a real `claude -p`
  invocation provably requires (e.g. a Node/`NODE_*` or `XDG_*` var if the binary
  needs it) and **nothing else**. Copy each allowed key from the parent env only
  when present (never invent values). The result: `FATTY_*`, `POSTGRES_*`, and
  every other secret are absent from the child's environment by construction.
- **Cap captured stdout.** Add a module constant (e.g. `MAX_STDOUT_BYTES`, sized
  for a schema-constrained JSON object — mirror the transport's intent, value owned
  locally) and reject an oversize capture as a non-retryable `LLMResponseError`
  ("claude code returned an oversized body"), matching `transport.MAX_RESPONSE_BYTES`
  semantics. Because `subprocess.run(..., capture_output=True)` buffers fully before
  returning, enforce the cap on the returned `stdout` length (the runner seam still
  returns a `ClaudeCodeResult`; the size check lives where the result is consumed so
  the injectable runner stays simple). The offending text is never echoed.
- **Make transient/busy exits retryable.** Introduce a small marker set (e.g.
  `_TRANSIENT_FAILURE_MARKERS`) for non-zero exits whose stderr/stdout indicates a
  retryable condition (rate limit / "try again" / overloaded / busy / temporarily
  unavailable — derive the exact phrases from how Claude Code reports throttling).
  On a non-zero exit, classify in order: auth failure → `LLMConfigurationError`
  (unchanged); transient marker → `LLMTransientError`; otherwise the existing
  non-retryable `LLMResponseError`. The matched text is used only for
  classification and is **never** logged or placed in a message (same discipline as
  `_looks_like_auth_failure`).
- **Anchor the auth markers.** Tighten `_AUTH_FAILURE_MARKERS` so the login phrases
  match the actual Claude Code "not logged in / please run claude login"
  wording rather than the bare substrings `"login"`/`"log in"`. Replace the two
  over-broad entries with anchored/whole-phrase forms (e.g. the full
  "not logged in" and "please log in" / "run `claude login`" style phrases Claude
  Code emits) while keeping the genuinely specific markers (`"unauthorized"`,
  `"authenticat"`, `"credential"`, `"session expired"`). The classification stays
  case-insensitive and content-free.
- **Add focused unit tests** for each of the four fixes (see Verification), driving
  the injectable `runner` seam so no real subprocess is spawned.

## Non-Goals

- **No contract change.** `docs/contracts/llm-provider.md` describes the
  provider/error taxonomy this story conforms to; it is **not** modified — the
  observable `structured_completion` contract (validated dict out, the three
  `LLMConfigurationError`/`LLMResponseError`/`LLMTransientError` types) is unchanged.
- **No change to the tools-disabled invocation.** `build_invocation`, the
  empty-allow / full-deny tool list, `--permission-mode default`, and the MCP
  lockdown stay exactly as they are. This story hardens the *environment, output
  size, and failure mapping* — not the command line.
- **No new env var surface.** Do not add a `FATTY_*` setting to configure the
  allowlist; the allowlist is a fixed, code-owned constant. (If a self-host genuinely
  needs an extra var, that is a separate story.)
- **Do not touch the HTTP transport or `hardened_fetch`.** This is parity *with*
  them, not a refactor *of* them; the shared-constant temptation is explicitly
  declined (the transport already documents why it owns its own cap).
- **No vision/image work** — image input remains an explicit non-goal of this
  provider.

## Contracts

- **None modified.** `docs/contracts/llm-provider.md` is referenced for the error
  taxonomy and provider behaviour the changes must conform to; the wire/return
  contract is unchanged by construction (a busy exit now raises the already-defined
  transient type instead of the response type — both are existing contract members).

## Security / Privacy

- **Primary intent.** This story closes a real **secret-exposure** gap: today every
  Fatty secret in the process environment (`FATTY_AUTH_SECRET`, DB password, FDC /
  search API keys) is handed to the `claude` child. The `env=` allowlist removes
  them from the subprocess by construction, making the module's documented
  no-credential-leak guarantee true. This is the security-privacy focus of the story
  (hence the touched lane).
- **No new input or stored field.** No endpoint, schema, or migration. The stdout
  cap is a denial-of-service guard (bounded worker memory). The retry reclassification
  must **not** widen what is logged: classification text (auth or transient) is
  inspected only to pick an error type and is never logged or surfaced — preserve the
  existing "never echo stderr (it may carry untrusted input)" discipline across all
  new branches.
- **Fail-closed posture preserved.** Misclassification only ever changes *which*
  clean error is raised; no path is added that would persist or surface untrusted
  child output.

## Acceptance Criteria

- `run_claude_code` passes an explicit `env=` allowlist; with the parent process
  holding `FATTY_AUTH_SECRET` / `POSTGRES_PASSWORD` / `FATTY_FDC_API_KEY` /
  `FATTY_SEARCH_API_KEY`, **none** of them appears in the environment the subprocess
  receives, while the binary still finds its session and runs (the allowlist
  includes exactly the vars a real invocation needs — `PATH`, `HOME`,
  `CLAUDE_CONFIG_DIR`, locale, and any empirically-required extras — and no more).
- A stdout capture exceeding the new cap raises a non-retryable `LLMResponseError`
  with a content-free message; the offending text is not echoed.
- A non-zero exit whose output carries a transient/busy marker raises
  `LLMTransientError` (retryable); a non-auth, non-transient non-zero exit still
  raises `LLMResponseError`; an auth-marked exit still raises `LLMConfigurationError`.
- `_AUTH_FAILURE_MARKERS` no longer contains the bare `"login"` / `"log in"`
  substrings; an unrelated failure whose stderr merely contains the word "login"
  (e.g. inside another word or an unrelated sentence) is **not** classified as an
  auth failure, while a genuine "not logged in / run claude login" message still is.
- No stderr/stdout content, secret, or untrusted text appears in any raised message
  or log across all branches.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **New unit tests, driving the injectable `runner`/subprocess seam:**
  - **Env allowlist:** monkeypatch the process env to hold `FATTY_AUTH_SECRET`,
    `POSTGRES_PASSWORD`, `FATTY_FDC_API_KEY`, `FATTY_SEARCH_API_KEY`; capture the
    `env=` dict actually passed to `subprocess.run` (patch `subprocess.run`) and
    assert none of those keys is present and the required keys (`PATH`, `HOME`,
    `CLAUDE_CONFIG_DIR`, a locale var) are forwarded when set in the parent.
  - **Stdout cap:** a runner returning an over-cap stdout → `LLMResponseError`,
    message content-free; an at/under-cap valid object still parses.
  - **Transient mapping:** a non-zero exit with a busy/rate-limit marker →
    `LLMTransientError`; a non-zero exit with a generic error →
    `LLMResponseError`; an auth-marked exit → `LLMConfigurationError`.
  - **Marker anchoring:** stderr containing only an unrelated "…login…" string →
    **not** auth-classified (falls to response/transient as appropriate); the real
    "not logged in" / "run claude login" phrasing → auth-classified.
  - **No leak:** assert the raised exception messages contain none of the injected
    stderr/stdout/secret text.
- **Existing `claude_code` provider tests stay green** — the tools-disabled
  invocation, JSON/fence parsing, timeout/`FileNotFoundError`/`OSError` mapping are
  unchanged.

## Planning Notes

- **Discover the env floor empirically — do not guess.** The one real judgment call
  is the exact allowlist. A too-narrow list silently breaks the provider (the binary
  can't find its session and every call fails auth); a too-wide list re-leaks
  secrets. Determine the minimal set by running a real `claude -p` with a scrubbed
  env and adding back only what it provably needs. Document the chosen keys inline
  with a one-line rationale each. If a needed var turns out to be host-specific in a
  way the allowlist can't cleanly express, **stop and flag it** rather than
  forwarding the whole environment.
- **Where the size check lives.** `subprocess.run(capture_output=True)` fully
  buffers stdout before returning, so the cap is enforced on the returned string
  length (the runner seam stays a thin process wrapper; the check sits with the
  other result handling in `_complete`/`_parse_object`'s caller). This keeps the
  injectable runner simple and the cap unit-testable without a subprocess.
- **Transient markers are derived, not invented.** Base the busy/rate-limit phrase
  set on how Claude Code actually reports throttling/overload; keep it small and
  specific to avoid the same over-match problem the auth set had.
- **Parity, not consolidation.** The transport (`MAX_RESPONSE_BYTES`) deliberately
  owns its own cap to avoid a circular import; this story likewise owns
  `MAX_STDOUT_BYTES` locally rather than importing across layers.

## Readiness Sanity Pass

- **Product decision gaps:** none requiring evidence research — this is a security
  and failure-handling hardening with no health/nutrition/behavioural decision. The
  one judgment call (the env allowlist contents) is an empirical discovery task,
  fully specified above with a documented floor and a "stop and flag if a needed var
  resists the allowlist" escape hatch.
- **Cross-lane impact:** primary **estimator**; **security-privacy** rides along as
  a non-serializing focus lane (the secret-isolation fix), which per the scope
  guardrail does **not** count as a second boundary. **Single boundary, zero big
  rocks:** no public contract change, no schema migration / new table, no new
  untrusted-input trust boundary (the subprocess and its untrusted output already
  exist; this *narrows* their blast radius). All code edits are in one file in the
  one serializing estimator lane.
- **Size:** `review_focus` = 5 (at the ceiling, not over) — all five facets live in
  the one file and one error-mapping function, so they are one coherent review, not a
  split trigger; `requires_context` = 4 (well under 8). One story.
- **Security/privacy risk:** medium — it removes a genuine secret-exposure path
  (good), but a wrong env allowlist could silently break the provider for all
  self-hosters, so the allowlist must be discovered empirically and the env-isolation
  test is the required safety net. No new input/endpoint/stored field.
- **Verification path:** `make verify` + targeted unit tests for the env allowlist,
  stdout cap, transient/auth/response classification, marker anchoring, and the
  no-leak assertion, all via the injectable runner (no real subprocess).
- **Assumptions safe for autonomy:** yes — bounded to one file, conformant to the
  existing error taxonomy and the FTY-113/114 precedent, with the only open choice
  (the allowlist) pinned to an empirical procedure and a stop-and-flag rule. No
  contract, migration, UI, or new external dependency.
</content>
</invoke>
