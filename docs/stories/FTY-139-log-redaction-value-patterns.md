---
id: FTY-139
state: ready
primary_lane: backend-core
touched_lanes:
  - security-privacy
  - docs
review_focus:
  - value-pattern-redaction
  - exc-info-redaction
  - conservative-no-false-positives
  - field-name-redaction-preserved
risk: medium
tags:
  - logging
  - redaction
  - security
  - privacy
approved_dependencies: []
requires_context:
  - docs/security/security-baseline.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-139: Redact Token-Shaped Values in Log Messages and Exceptions (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. Self-contained hardening of `app/logging.py`. Nothing blocks
  it; no other in-flight backend-core story is known to touch the logging module,
  but as always **rebase on whatever backend-core work merges first** to avoid a
  churn conflict.

## Outcome

`app/logging.py`'s `RedactionFilter` only redacts log record fields whose **name**
matches `_SENSITIVE_KEY` (~23–26, ~35–41). A sensitive **value** that arrives any
other way slips through unredacted:

1. a secret embedded in a **formatted message string** (e.g.
   `logger.info("calling %s with %s", url, token)` or an f-string) — the message
   is rendered by `JsonFormatter` (~58 `record.getMessage()`) without any
   value-level scrubbing;
2. an **exception arg** carrying a secret, surfaced through
   `JsonFormatter.format`'s `exc_info` branch (~58–59), which emits the full
   `formatException(...)` traceback **unredacted**.

Today the codebase **deliberately keeps secrets and PII out of message strings**
(verified — the LLM layer logs only provider/attempt/error-count, transport/fetch
errors are content-free, and `tests/security/test_secret_no_disclosure.py` proves
it), so this is a **latent footgun, not a current leak**. The fix adds a
**conservative value-pattern redaction** of token-shaped strings to the rendered
message and the serialized `exc_info`, on top of the existing field-name
redaction, so a future careless log line or a third-party exception message cannot
quietly print a credential.

## Scope

- **Add a conservative value-pattern redactor** in `app/logging.py`:
  - A compiled `_SENSITIVE_VALUE` pattern (compiled once at import) matching only
    **token-shaped** strings with a low false-positive rate:
    - `Authorization`/`Bearer` header values: `Bearer\s+<token>`;
    - JWTs: three base64url segments joined by dots
      (`eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+`);
    - common provider key shapes: `sk-…`, `xox[baprs]-…` (Slack),
      `gh[pousr]_…` (GitHub), `AKIA[0-9A-Z]{16}` (AWS);
    - an inline `key=value` / `key: value` form where the key matches the existing
      `_SENSITIVE_KEY` set (e.g. `token=…`, `api_key: …`) — redact the value only;
    - optionally a **high-threshold** generic secret (a contiguous run of
      base64url/hex of length ≥ 40 with no separators) — include only if it can be
      shown not to scrub the normal-text corpus below.
  - A small helper `_redact_values(text: str) -> str` applying
    `_SENSITIVE_VALUE.sub(REDACTED, text)` (reusing the existing `REDACTED`
    sentinel and the existing `_SENSITIVE_KEY` for the inline key=value form).
- **Apply it where the strings are rendered**, in `JsonFormatter.format`:
  - wrap the message: `payload["message"] = _redact_values(record.getMessage())`;
  - wrap the exception trace: when `record.exc_info`,
    `payload["exc_info"] = _redact_values(self.formatException(record.exc_info))`.
- **Keep the field-name redaction unchanged.** `RedactionFilter` and
  `_SENSITIVE_KEY`'s field-name behaviour (~35–41) stay exactly as today; this
  story is **additive** value-level defense layered on top.
- **Stay conservative — no false-positive scrubbing of normal text.** Tune the
  patterns so ordinary log content (UUIDs, request/event IDs, ISO-8601
  timestamps, file paths, ordinary sentences, numbers, emails-as-identifiers in
  non-secret contexts) is **not** redacted. If the generic high-threshold pattern
  cannot clear that bar, omit it and ship only the specific token shapes.
- **Update the docs ride-along:** extend the `security-baseline.md` logging bullet
  (currently: a `RedactionFilter` that scrubs secret/header-shaped **fields**) to
  note that token-shaped **values** in messages and exception traces are also
  redacted. Non-serializing docs/security ride-along, not a contract change.

## Non-Goals

- **No change to field-name redaction** (`RedactionFilter`, `_SENSITIVE_KEY`
  field matching) or to the JSON log shape/keys.
- **No removal of the "keep secrets out of messages" convention.** Value-pattern
  redaction is defense-in-depth, not a license to start logging secrets; the
  existing discipline and `test_secret_no_disclosure.py` remain authoritative.
- **No blanket "redact any long string" rule** — that would scrub UUIDs, hashes,
  request IDs, and paths and make logs useless. Only specific token shapes (and an
  optional, corpus-validated high-threshold generic) are redacted.
- **No scrubbing of arbitrary `extra` field values beyond message + exc_info.**
  Named sensitive fields are already covered by the existing filter; this story
  targets exactly the two finding sites (rendered message, serialized exc_info).
- **No new endpoint, migration, or contract.** No change to `configure_logging`'s
  wiring beyond what the formatter needs.

## Contracts

- **None.** No contract doc is modified. `security-baseline.md` (a security policy
  doc, not a contract) is updated as a ride-along to keep the documented redaction
  posture accurate. The structured-log JSON keys are unchanged.

## Security / Privacy

- **This is the privacy/security fix.** It closes a latent path by which a
  bearer token, API key, or JWT embedded in a message string or an exception
  message/traceback would reach stdout logs unredacted — a defense-in-depth backstop
  behind the existing "no secrets in messages" convention.
- **Conservative by design.** Over-redaction would hide operational data and erode
  trust in logs; the patterns are specific token shapes, and the normal-text corpus
  test (below) is a hard gate against false positives.
- **No new data is logged**, no PII is added, and the existing field-name redaction
  is preserved. `REDACTED` continues to be the single redaction sentinel.
- **Performance note (non-blocking):** value scrubbing runs a compiled regex over
  every emitted message (and exc_info when present). Compile the pattern once at
  import; the per-record cost is a single `sub` over a short string, negligible
  relative to JSON serialization. Flagged so the reviewer can confirm no hot-path
  concern.

## Acceptance Criteria

- A token-shaped value embedded in a **formatted message** (e.g. a `%s`/f-string
  carrying a `Bearer …` token, a `sk-…`/`gh…_…` key, or a JWT) is rendered as
  `[REDACTED]` (in whole or for the token substring) in the JSON `message` field.
- A secret embedded in an **exception arg** is `[REDACTED]` in the serialized
  `exc_info` traceback when the record carries `exc_info`.
- The existing **field-name** redaction is unchanged: a sensitive-named `extra`
  field is still redacted exactly as before.
- **No false positives:** a representative normal-log corpus — a UUID, a
  request/event ID, an ISO-8601 timestamp, a file path, an ordinary sentence, a
  bare integer/float, and a non-secret email-as-identifier — passes through
  **unredacted**.
- The JSON log shape (keys, single-line) is unchanged; `REDACTED` is the only
  sentinel used.
- `security-baseline.md`'s logging bullet notes value-pattern redaction of
  messages and exception traces.
- `make verify` passes (ruff check + ruff format --check + mypy + pytest).

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh`, i.e. root
  `make verify`.
- **New unit tests for `JsonFormatter` / value redaction:**
  - a message formatted with a `Bearer …` token, an `sk-…`/`gh…_…`/`AKIA…` key,
    and a JWT each yields `[REDACTED]` for the secret in the JSON `message`;
  - a `key=value` / `key: value` form with a sensitive key redacts the value;
  - an exception whose arg contains a secret yields a redacted `exc_info`;
  - a **normal-text corpus** (UUID, request ID, ISO timestamp, file path, plain
    sentence, number, identifier-email) is emitted **verbatim** — the false-positive
    gate;
  - an existing sensitive-named `extra` field is still redacted (no regression to
    field-name behaviour).
- **Reuse / extend `tests/security/test_secret_no_disclosure.py`** so the
  value-level guarantee joins the existing field-level one.

## Planning Notes

- **Where to apply the scrub — formatter, not filter:** the message and `exc_info`
  are rendered inside `JsonFormatter.format` (the filter runs earlier, before args
  are resolved into a final string), so the formatter is the natural, single place
  to scrub both. Keep `_redact_values` a module-level helper so the formatter (and
  any future consumer) shares one implementation; reuse the existing `REDACTED`
  and `_SENSITIVE_KEY`.
- **Conservative pattern set is the core judgment call** and is decided above:
  ship the **specific** token shapes (bearer/JWT/provider-key prefixes + the
  sensitive-key inline form), and include the generic high-threshold base64/hex
  rule **only if** it clears the normal-text corpus test; otherwise drop it. The
  false-positive corpus test is the arbiter — prefer missing an exotic
  hand-rolled secret to scrubbing every UUID.
- **Why not redact all `extra` values:** named sensitive fields are already
  handled, and blanket value scrubbing of structured fields risks corrupting
  legitimate operational data; the finding is specifically about messages and
  exc_info, so the fix stays scoped there.
- **Decision basis:** a logging/security hardening decision, not a
  health/nutrition/behavioural one, so no evidence research is warranted; it is
  grounded in `docs/security/security-baseline.md` ("Logs must not contain secrets,
  auth tokens…" and "Redact sensitive fields in errors and provider traces").

## Readiness Sanity Pass

- **Product decision gaps:** none. The redaction surface (message + exc_info), the
  conservative pattern set, and the false-positive gate are all decided above.
- **Cross-lane impact:** primary backend-core; **security-privacy and docs ride
  along** (the redaction posture + the `security-baseline.md` edit) and do not
  count as a second boundary. **Single boundary, zero blocking big rocks:** no
  public contract change, no schema migration / new table, no new untrusted-input
  trust boundary — the change is confined to `app/logging.py` and its tests.
- **Size:** `review_focus` = 4 (under the 5 ceiling); `requires_context` = 3
  (under 8). One story.
- **Security/privacy risk:** medium — it changes how logs are rendered on a
  security-sensitive path (hence the rating and the security-privacy ride-along),
  but it is additive (field-name redaction preserved), conservative (corpus-gated
  against false positives), and fully test-covered. The risk to manage is
  over-redaction, which the normal-text corpus test fences off.
- **Verification path:** `make verify` + new formatter/value-redaction unit tests
  (token shapes redacted, exc_info redacted, normal corpus untouched, field-name
  redaction intact) + the extended `test_secret_no_disclosure.py`.
- **Assumptions safe for autonomy:** yes — the log shape and field-name behaviour
  are preserved, the pattern set and the false-positive gate are pinned, and the
  change is a self-contained, additive hardening of one module.
