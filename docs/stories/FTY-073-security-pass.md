---
id: FTY-073
state: ready_with_notes
primary_lane: security-privacy
touched_lanes:
  - estimator
  - backend-core
  - contracts
risk: high
tags:
  - security
  - privacy
  - prompt-injection
  - ssrf
  - data-minimization
  - secret-handling
  - authorization
  - audit
  - v1-gate
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/security/threat-model.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/architecture/evidence-retrieval.md
  - docs/contracts/llm-provider.md
  - docs/stories/FTY-044-generic-food-calculator.md
  - docs/stories/FTY-045-evidence-retrieval-contract.md
  - docs/stories/FTY-060-barcode-lookup.md
  - docs/stories/FTY-061-nutrition-label-extraction.md
  - docs/stories/FTY-062-official-source-search.md
  - docs/stories/FTY-020-auth-user-model-contracts.md
  - docs/stories/FTY-051-corrections-audit.md
  - docs/stories/FTY-052-saved-foods-aliases.md
  - docs/standards/testing-standards.md
review_focus:
  - threat-model-currency
  - prompt-injection-resistance
  - ssrf-egress-hardening
  - query-sanitization-data-minimization
  - secret-no-log-no-return
  - fail-closed-authorization
  - findings-filed-not-fixed-inline
autonomous: true
---

# FTY-073: Security Pass

## State

ready_with_notes

## Lane

security-privacy

## Dependencies

- FTY-020
- FTY-044
- FTY-045
- FTY-051
- FTY-052
- FTY-060
- FTY-061
- FTY-062

## Outcome

The v1 security gate. The now-built v1 surface — estimator, evidence retrieval
(USDA/OFF/label/official-source), LLM providers, and auth/profile/corrections/
saved-foods data — is audited against the threat model, retention defaults, and
secret-handling baseline, and is backed by a concrete, repeatable **adversarial
test suite** proving the untrusted-input trust boundary holds. The security docs
are updated where they have drifted from what was actually built, every
non-trivial vulnerability or hardening gap is captured as a filed follow-up
story (not patched inline), and `make verify` passes including the new
adversarial tests. After this story, the v1 surface has a documented,
test-enforced security posture and a tracked backlog of remediation work.

## Scope

This story delivers three things and only three things: a review pass, an
adversarial test suite, and a filed list of findings.

1. **Review pass (docs may change).** Confirm the threat model
   (`docs/security/threat-model.md`), retention defaults
   (`docs/security/data-retention.md`), and secret-handling baseline
   (`docs/security/security-baseline.md`) are current and complete for the
   as-built v1 surface: estimator pipeline, evidence retrieval (FTY-044/060/061/
   062), LLM provider transport (`docs/contracts/llm-provider.md`), and auth/
   profile/corrections/saved-foods (FTY-020/051/052). Update those docs where
   they have drifted from what was built — including resolving stale Open
   Questions in the threat model that the built v1 has answered, and confirming
   each newly stored field/cache/trace has a documented retention behavior. Doc
   edits only; no behavior changes in this scope.

2. **Adversarial test suite (the deliverable).** Add a security test suite that
   proves the boundaries below hold. These are test-only additions exercising
   the existing built surface; they do not change product behavior.
   - **Prompt-injection resistance.** Injection payloads in user free text
     **and** in untrusted evidence — fetched-page text (FTY-062), OCR / vision
     label text (FTY-061), and search-result text (FTY-062) — must not be
     followed as instructions: no data exfiltration, no privilege/scope
     escalation, no open-ended tool/network use, and injected "nutrition facts"
     are never treated as trusted facts. They survive only as data that must
     pass the Pydantic schema + deterministic calculators before persistence.
   - **SSRF / egress hardening on the fetcher.** Private/loopback/link-local
     (incl. cloud metadata `169.254.169.254`)/multicast/reserved/unspecified
     IPs, `file:`/non-HTTPS schemes, non-allowlisted hosts, redirect-to-private,
     oversize bodies, and disallowed content-types are all blocked and fail
     closed.
   - **Query sanitization / data minimization.** No personal or profile/history
     context (profile, weight, body data, food/exercise history, memories,
     event metadata) egresses to search or other external providers; only a
     sanitized product/restaurant name leaves the system.
   - **Secret non-disclosure.** Provider keys, prompts, raw provider responses,
     and model weights/identifiers-beyond-label are never logged and never
     returned in API responses or error messages; transport errors are
     content-free.
   - **Fail-closed object-level authorization.** Cross-user / unauthenticated /
     missing-resource access to user-owned records (log events, derived items,
     corrections, saved foods, aliases, evidence sources, attachments, profile,
     weight) fails closed across endpoints with the correct not-found/forbidden
     shape — never leaking another user's data or its existence.
   - Treat fetched pages, search results, OCR/vision text, and LLM output as
     **untrusted until schema-validated** throughout the suite.

3. **Findings filed, not fixed.** Any non-trivial vulnerability or hardening gap
   discovered during the pass is **filed as a new follow-up story** (or GitHub
   issue) and recorded in this story's Findings notes as
   `finding → tracked story/issue` — it is **not** remediated inline. This keeps
   the story bounded and verifiable. Trivial **test-only** additions (the suite
   itself, fixtures) are in-scope; any **behavior change** (code fix, contract
   tightening, new control) is a follow-up.

## Non-Goals

- Open-ended remediation or refactors — every behavior-changing fix becomes its
  own follow-up story; this story only audits, tests, and files.
- Production / deployment-infrastructure hardening (TLS termination, secret
  manager wiring, network policy, branch-protection/CI/supply-chain config) —
  that is FTY-072 territory.
- A live penetration test of a deployed environment.
- Adding new product features, new providers, or new endpoints.
- Changing any contract. Findings that require a contract change are filed as
  follow-up stories, not made here.

## Contracts

- **None changed.** This is an audit + test story. The adversarial suite may add
  or tighten **test fixtures** only. Any finding that requires a contract change
  (e.g. tightening `llm-provider`, evidence, or auth contracts) is filed as a
  follow-up story rather than applied here.

## Security / Privacy

This **is** the v1 security story; it is centered on the untrusted-input trust
boundary and the threat-model controls.

- **Untrusted-input boundary.** Per `evidence-retrieval.md` and the
  `llm-provider` contract, fetched pages, search results, OCR/vision text, and
  LLM output are untrusted until validated by backend schemas and recomputed by
  deterministic calculators. The suite asserts this boundary holds for every
  evidence channel built in v1.
- **Prompt injection.** Covers the threat-model "Prompt injection from user
  input, fetched pages, OCR text, nutrition labels, or provider output" and
  "Memory poisoning through untrusted content" — injected instructions are data,
  never commands; injected facts never become trusted nutrition facts.
- **SSRF.** Covers "SSRF through source fetching" — the fetcher's allowlist /
  public-IP-only / scheme / redirect / size / content-type policy fails closed.
- **Data minimization.** Covers "Cross-user data leakage" and the
  data-minimization baseline — sanitized queries, no personal context to
  external providers.
- **Secret handling.** Covers "Provider key leakage" and "Sensitive data in
  logs, prompts, analytics" — keys/prompts/raw responses never logged or
  returned; content-free errors.
- **Authorization.** Covers "Broken object-level authorization" — negative tests
  prove every user-owned access path fails closed.
- **Retention.** Confirms no raw pages / raw OCR / raw images / raw prompts are
  over-retained; evidence and derived data follow the documented
  `ON DELETE CASCADE` ownership and snapshot-only storage.

Rated **high**: this is the v1 security gate and it spans the auth, privacy,
estimator, and evidence trust boundaries simultaneously. When risk is ambiguous,
estimate big — this is unambiguously the highest-stakes review surface.

## Acceptance Criteria

- The adversarial suite exists and passes, with explicit coverage for each
  boundary:
  - prompt-injection in user text **and** in untrusted evidence (fetched page,
    OCR/vision label text, search result) does not exfiltrate, escalate, or get
    treated as trusted nutrition facts;
  - SSRF/egress negatives (private/loopback/link-local/metadata IPs, file/
    non-HTTPS schemes, non-allowlisted hosts, redirect-to-private, oversize,
    disallowed content-type) all fail closed;
  - query-sanitization proves no personal/profile/history context egresses to
    external providers;
  - no provider key, prompt, raw response, or weight appears in logs or
    responses, and transport errors are content-free;
  - object-level authorization fails closed across user-owned endpoints
    (cross-user, unauthenticated, missing-resource).
- The threat model, data-retention defaults, and secret-handling baseline
  reflect the built v1 surface; drift is corrected and stale Open Questions the
  built v1 has answered are resolved (doc edits only).
- Every discovered non-trivial finding has a **filed follow-up story or issue**,
  referenced in this story's Findings notes as `finding → tracked item`. No
  non-trivial vulnerability is fixed inline.
- `make verify` passes **including** the new adversarial tests (using fake/
  stubbed providers and a stubbed fetcher — no real external calls in tests).

## Verification

- Run `make verify` from the backend, including the new security suite, with
  fake/stubbed LLM + search providers and a stubbed fetcher (no live egress):
  - **prompt-injection** tests against user text and each untrusted evidence
    channel (fetched page, OCR/vision label, search result) asserting injected
    instructions are not followed and injected facts are rejected/untrusted
    until schema-validated;
  - **SSRF/egress** negative suite asserting every blocked target/scheme/
    redirect/size/content-type fails closed;
  - a **query-sanitization** test asserting no personal context leaves the
    system;
  - **secret-handling** tests asserting keys/prompts/raw responses never appear
    in logs or responses and errors are content-free;
  - **fail-closed authorization** negatives across user-owned endpoints.
- Review-pass output: a diff to the three security docs (or an explicit "no
  drift" confirmation per doc) reflecting the as-built v1.
- Findings output: the Findings notes list each non-trivial finding with its
  filed follow-up story/issue reference; confirm none were fixed inline (the PR
  diff is tests + docs only).

## Planning Notes

- **Audit-only, fixes are follow-ups.** The single most important constraint:
  this story does not remediate. Discovering a real vulnerability is a
  *success* of this story and results in a filed follow-up, not a code change
  here. The author should resist the urge to "just fix it" — that breaks the
  story's bound and verifiability.
- **Reuse existing negative suites.** FTY-062 already mandates the heavy SSRF/
  allowlist negative suite and the query-sanitization test; FTY-061 mandates
  the untrusted-image/oversize negatives; FTY-044 owns `hardened_fetch` and the
  serving math. This story consolidates and *extends* those into one
  cross-cutting adversarial suite and fills gaps — it does not duplicate or
  re-decide their boundaries.
- **Findings ledger lives here.** Record discovered findings in a "Findings"
  section appended to this story (or in the PR description) as
  `finding → filed story/issue`, so the steward and reviewer can see the audit
  result without the fixes being in this PR.
- **Depends on the audited surface being merged.** This is why state is
  `ready_with_notes`: the audit is only meaningful once FTY-044/045/060/061/062,
  FTY-020, and FTY-051/052 are merged. If any are still in flight when this is
  scheduled, scope the suite to the merged subset and note the deferred channels
  as a follow-up rather than blocking.
- **No production-infra work.** TLS, secret-manager wiring, and supply-chain
  hardening belong to FTY-072 and are explicit non-goals here.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking — scope is fixed to audit + adversarial
  tests + filing findings; the boundaries to cover (injection, SSRF/egress,
  sanitization, secret-no-log/return, fail-closed authz) and the
  fixes-become-follow-ups rule are all decided.
- **Cross-lane impact:** spans estimator, backend-core, and contracts surfaces
  but changes none of them — it adds tests and edits security docs. Findings that
  would change behavior or contracts are filed as separate stories, so no
  unmanaged cross-lane churn lands in this PR.
- **Security/privacy risk:** high — this is the v1 security gate touching auth,
  privacy, estimator, and evidence trust boundaries; mitigated by being
  audit/test-only (no behavior change), using fake/stubbed providers and a
  stubbed fetcher (no live egress), and routing every real fix to a tracked
  follow-up.
- **Verification path:** `make verify` including the new adversarial suite
  (injection-resistance, SSRF/egress-block, query-sanitization, no-secret-
  logging, fail-closed authz) plus a security-docs diff and a filed-findings
  ledger.
- **Assumptions safe for autonomy:** yes — the bounded scope (review + tests +
  filing, no inline remediation) is autonomy-safe; the only non-blocking caveat
  is that the audited surface must be merged first, and the audit scopes to the
  merged subset if not (carried as a `ready_with_notes` note, with discovered
  findings becoming follow-up stories).
