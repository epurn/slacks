---
id: FTY-114
state: merged
primary_lane: estimator
touched_lanes:
  - security-privacy
review_focus:
  - response-size-cap
  - transport-parity
  - tolerant-json-extraction
risk: medium
tags:
  - estimator
  - llm-provider
  - self-host
  - hardening
approved_dependencies: []
requires_context:
  - docs/contracts/llm-provider.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-114: LLM Provider Output Hardening — Bounded Read + Tolerant JSON (estimator)

## State

ready_with_notes

## Lane

estimator

## Dependencies

- None to schedule. This **hardens merged code**: the provider transport +
  config (FTY-041) and the keyless self-host providers — the Claude Code
  subscription adapter and the local/openai-compatible path (FTY-087/088/089) —
  are all landed, and the bounded HTTP fetcher (FTY-078, `hardened_fetch.py`) is
  the parity model. This story changes only the **output-handling seams** inside
  `app/llm/transport.py` and `app/llm/providers/claude_code.py`; it adds no
  contract, no migration, and no config.

## Outcome

Two small, cohesive robustness fixes on the LLM-provider **output** boundary —
the point where a self-host endpoint's response or a local Claude Code's stdout
re-enters Fatty — so neither a misbehaving endpoint nor a chatty CLI can fail a
run that should have succeeded (or, worse, exhaust memory).

1. **The JSON transport reads an unbounded response body.** `transport.post_json`
   does `raw = response.read()` (`transport.py` line 60) with **no size cap** —
   unlike the hardened HTTP fetcher, whose `_open_json` reads `max_bytes + 1` and
   rejects an oversized body (`hardened_fetch.py` lines 256, 269-270, bounded by
   `DEFAULT_MAX_BYTES = 1_000_000`). The OpenAI/Anthropic-compatible providers
   (`openai.py` line 77, `anthropic.py` line 80) POST to an
   **operator/community-configured `base_url`**, so a hostile or broken endpoint
   can stream an unbounded body and OOM the worker. This brings the two transports
   to parity: cap the read, error cleanly when exceeded.

2. **Claude Code stdout is parsed with a bare `json.loads`.** `_parse_object`
   (`claude_code.py` line 259) calls `json.loads(stdout)` on the raw CLI output.
   `claude --print` can still emit a leading prose line or a ```json fence despite
   the explicit no-fences instruction in `_build_stdin` (lines 242-244); any stray
   text makes `json.loads` raise, which becomes `LLMResponseError` and **fails the
   whole step even though a valid object is right there**. Add tolerant extraction
   (strip fences / take the first balanced top-level object) before parsing — kept
   strict enough to still **reject trailing junk after the object**. This protects
   the merged keyless self-host path (FTY-087/088/089), exactly where output
   discipline is least guaranteed.

## Scope

- **Cap the transport read (parity with `hardened_fetch`).** In
  `transport.post_json`, read at most a bound (`response.read(max_bytes + 1)`) and,
  when the result exceeds `max_bytes`, raise the existing non-retryable
  `LLMResponseError` with a content-free message (e.g. "provider returned an
  oversized body") — never the body. Mirror `hardened_fetch._open_json`'s shape so
  the two transports read identically. **Reuse the existing
  `hardened_fetch.DEFAULT_MAX_BYTES` (1 MB)** as the cap rather than minting a new
  constant (see Planning Notes). The cap is a module default; the existing
  scheme-validation, transport-error mapping, and JSON/`dict` checks are unchanged.
- **Tolerant JSON extraction from Claude Code stdout.** In `_parse_object`, before
  `json.loads`: trim whitespace, strip a leading/trailing ```json / ``` fence if
  present, and extract the **first balanced top-level `{...}` object** from the
  remaining text. Parse that. Keep the current `LLMResponseError` mappings for a
  non-JSON / non-object result, and **reject trailing non-whitespace after the
  object** (do not silently trust junk that follows a valid object — that signals a
  malformed/garbled emission). Clean stdout (a bare object) still parses exactly as
  today.
- **Tests for both** (see Verification): over-cap response errors cleanly; fenced /
  prose-prefixed stdout parses; trailing-junk stdout is rejected; clean paths
  unchanged.

## Non-Goals

- **No 429 / backoff / retry handling.** Rate-limit classification and retry
  policy on provider responses is a separate estimator story (**FTY-113**). This
  story only bounds the read and tolerates output prose — it adds no new retry
  branch and does not reclassify any status code.
- **No FDC/OFF evidence-client changes.** Hardening the third-party food-data
  clients is **FTY-110**; `fdc.py`/`off.py`/`hardened_fetch.py` are untouched here
  (the fetcher is referenced only as the parity model for the cap).
- **No schema or provider-config change.** The structured-output schema
  (`json_schema_for`), the provider selection/config (FTY-041), and the
  per-provider request shapes are unchanged. This is read-side hardening only.
- **No loosening of downstream validation.** The extracted object is still handed
  to the base class for strict Pydantic validation against the caller's schema;
  tolerant extraction makes parsing more forgiving of *wrapping prose*, never of a
  *non-conforming object*.

## Contracts

- **None.** Both changes are internal to the provider layer. `LLMResponseError`
  already exists and is already the non-retryable fail signal the base class and
  callers consume; the transport and Claude Code adapter keep their public
  shapes. `docs/contracts/llm-provider.md` needs no version bump (it documents the
  provider contract, not the transport's internal read bound).

## Security / Privacy

- **Hardens a robustness / DoS surface on an operator-configured boundary.** The
  unbounded `response.read()` lets a misbehaving or hostile self-host endpoint
  (whose `base_url` is operator/community-supplied, not Fatty-controlled) exhaust
  worker memory; the cap bounds it to the same 1 MB ceiling the SSRF-hardened
  fetcher already enforces. The **cap error must stay content-free** — never
  include the oversized body, its length-beyond-bound, or the URL in the message or
  exception chain, matching the existing transport discipline (the module docstring
  already promises failures are safe to log).
- **Tolerant extraction must not become a log/echo leak.** Claude Code stdout can
  carry untrusted food-log text; the `LLMResponseError` mappings already avoid
  echoing it, and the new extraction path must keep that — classify and fail
  without placing stdout (or the rejected trailing junk) into a message or log.
- **Not a new trust boundary.** Both are existing untrusted inputs (a provider
  response body; CLI stdout) being hardened — no new image/fetch/OCR/upload
  surface, no new big rock. The tolerant parse stays strict on the object itself
  (downstream Pydantic validation is unchanged), so it widens *what wrapping is
  tolerated*, not *what objects are accepted*.
- **Rated medium:** provider transport/output hardening on the estimation path,
  no contract and no migration. The cost of the current state is an OOM on hostile
  input and spurious run failures on valid-but-wrapped output; the fix is bounded
  and local to two files.

## Acceptance Criteria

- **Bounded read:** a `post_json` response larger than the cap raises
  `LLMResponseError` (the non-retryable type) — never reads the body unbounded,
  never OOMs, and never includes the body in the message. A response at or under
  the cap parses exactly as today.
- **Transport parity:** `transport.post_json` and `hardened_fetch._open_json` use
  the same read-and-check shape and the same `DEFAULT_MAX_BYTES` ceiling; the
  existing transport-error mapping (timeout/5xx → `LLMTransientError`, 4xx /
  non-JSON / non-object → `LLMResponseError`) is unchanged.
- **Fence / prose tolerance:** a Claude Code stdout that wraps a valid object in a
  ```json fence, and one with a leading prose line before the object, both parse to
  the correct `dict` (no `LLMResponseError`).
- **Trailing-junk rejection:** a stdout with non-whitespace text *after* a valid
  object raises `LLMResponseError` — the parser does not silently accept the leading
  object and discard the trailing garbage.
- **Clean paths unchanged:** a bare single-object stdout still parses to the same
  `dict`; truly non-JSON / non-object output still maps to `LLMResponseError`; the
  downstream Pydantic validation seam is unchanged.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **Transport cap test** (`tests/` for the LLM transport, with a faked
  `urlopen`/response): an over-cap body raises `LLMResponseError`, asserting the
  read is bounded (no OOM) and the message contains none of the body; an at/under-cap
  body parses to the expected `dict`. The existing timeout/5xx/4xx/non-JSON mapping
  tests stay green.
- **Claude Code extraction tests** (`tests/` for the claude_code provider, driving
  `_parse_object` or the runner seam): (a) ```json-fenced object → correct `dict`;
  (b) leading prose line + object → correct `dict`; (c) object + trailing
  non-whitespace junk → `LLMResponseError`; (d) bare object → unchanged correct
  `dict`; (e) non-JSON / non-object → `LLMResponseError` as today.
- Behaviour-preserving: a known-good response / stdout produces the same parsed
  object as before the change.

## Planning Notes

- **Reuse `DEFAULT_MAX_BYTES` vs a provider-specific cap (the first small,
  reversible call).** Recommend **reusing `hardened_fetch.DEFAULT_MAX_BYTES`
  (1 MB)**: it is the team's already-vetted "JSON-from-an-untrusted-HTTP-endpoint"
  ceiling, a structured LLM object is comfortably under it, and a single shared
  constant is the whole point of bringing the two transports to parity. A
  provider-specific constant is only worth minting if a real provider response
  legitimately exceeds 1 MB — not anticipated for the schema-constrained objects
  here, and trivially changed later if it does.
- **How strict the extraction is (the second small, reversible call).** Recommend
  **first balanced top-level object, reject trailing non-whitespace.** That tolerates
  the realistic `claude --print` deviations (a fence, a leading "Here is the JSON:"
  line) while refusing to trust output that keeps going after the object — which
  usually signals a garbled/double emission rather than a clean answer. Whitespace
  after the object is fine; non-whitespace is not. Both calls are local and reversible
  with no contract impact.
- **Why these two ride together.** Both are one-file output-handling hardenings on
  the same boundary (provider/CLI output re-entering Fatty), both map to the same
  existing `LLMResponseError`, and both protect the keyless self-host path where
  output discipline is weakest — a cohesive quick win, not two unrelated changes.
- **Parity model, not a shared call.** `_open_json` is in the estimator's
  `hardened_fetch` and `post_json` is in `app/llm/transport`; mirror the
  read-and-check *shape* and reuse the *constant*, but do not refactor the two into a
  shared helper here — that would pull in the fetcher's SSRF/content-type concerns
  and widen the slice.

## Readiness Sanity Pass

- **Product decision gaps:** none load-bearing. The two judgment calls — reuse the
  existing 1 MB cap, and first-balanced-object / reject-trailing-junk extraction —
  are decided and justified above; `ready_with_notes` only for those reversible
  defaults. No health/nutrition/behavioural question is involved (this is
  output-robustness, not user guidance), so no evidence research is warranted.
- **Cross-lane impact:** primary estimator; security-privacy rides along
  (non-serializing) since both fixes harden untrusted-output handling. **Single
  boundary, zero big rocks:** no public contract change, no schema migration, no new
  untrusted-input trust boundary (both are existing untrusted inputs being
  hardened). Stays wholly in the estimator lane.
- **Size:** `review_focus` = 3 (response-size-cap, transport-parity,
  tolerant-json-extraction); `requires_context` = 5. Well under both ceilings — a
  deliberately small two-fix quick win, kept as one story.
- **Security/privacy risk:** medium — provider transport/output hardening on the
  estimation path; the cap removes an OOM-on-hostile-input DoS on an
  operator-configured endpoint and the extraction removes spurious run failures, both
  with content-free errors and no new surface.
- **Verification path:** `make verify` + transport over-cap fail-clean test (no OOM,
  no body in message) + Claude Code fenced/prose/trailing-junk/clean extraction tests
  + behaviour-preserving good-output test; existing transport-mapping tests stay green.
- **Assumptions safe for autonomy:** yes — a local change to two provider-layer files
  with both judgment calls pinned here, no contract, no migration, no config change,
  and the transport/runner faked in tests (no real network or subprocess).
