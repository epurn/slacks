---
id: FTY-137
state: merged
primary_lane: estimator
touched_lanes:
  - security-privacy
review_focus:
  - resolve-once-connect-to-vetted-ip
  - preserve-host-header-and-sni
  - ssrf-policy-still-applies
  - adversarial-rebind-test
  - no-url-or-ip-leak-in-errors
risk: high
tags:
  - estimator
  - hardened-fetch
  - ssrf
  - dns-rebinding
  - security
approved_dependencies: []
requires_context:
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
  - docs/standards/coding-standards.md
autonomous: true
---

# FTY-137: Pin the Vetted IP to Close the Hardened-Fetch DNS-Rebinding TOCTOU (estimator)

## State

ready_with_notes

## Lane

estimator

## Dependencies

- **None to schedule.** `approved_dependencies: []` — `hardened_fetch` and its SSRF
  policy (FTY-044/078/081) are all merged. This story hardens the existing
  check→connect window.
- **Serialization note:** one of four estimator-lane release-audit fix-stories
  (FTY-131/132/135/137) serializing on the estimator lane by changed-file path. This
  story edits `backend/app/estimator/hardened_fetch.py`; the others edit different
  estimator files, so there is no content overlap, but they cannot author
  simultaneously. **Rebase on whatever estimator work merges first** before opening
  the PR.

## Outcome

The hardened fetcher connects to the **same IP it vetted**, closing a DNS-rebinding
time-of-check/time-of-use (TOCTOU) gap in the SSRF defence.

1. **The check and the connect resolve the host independently.**
   `assert_url_allowed` (`backend/app/estimator/hardened_fetch.py` ~102–133) resolves
   the host and requires every resolved IP to be public/globally-routable. But the
   subsequent `director.open(request, ...)` (in `_open_json` ~252–254 and `_open_text`
   ~347–349) re-resolves the **name** at connect time. A name that returns a public
   IP during the check and a private IP at connect (DNS rebinding) would pass the
   policy yet connect inward.
2. **Mitigated today, not eliminated.** The host allowlist still constrains targets
   to operator-configured hosts, so exploitation requires control of DNS for an
   already-allowlisted host — a high bar. This is **hardening of a defence-in-depth
   layer, not a patch for a live hole**: it removes the residual TOCTOU so the IP
   that passed the policy is provably the IP connected to.

After this story, `assert_url_allowed` returns the vetted IP(s), and the fetch
connects to a pinned vetted IP while preserving the `Host` header and TLS SNI
(server name) so virtual-hosting and certificate validation still work.

## Scope

All edits are in `backend/app/estimator/hardened_fetch.py` and its tests.

- **Resolve once, return the vetted address.** Have `assert_url_allowed` (or a small
  sibling it delegates to) return the vetted IP it approved — pick a single address
  from the resolved set that passed `_is_public_address` (e.g. the first public one),
  so the connection target is exactly an address the policy approved. Keep the
  existing fail-closed behaviour: scheme/host-allowlist/resolution-failure/private-
  address refusals are unchanged, and **every** resolved address must still be public
  (no relaxation — the per-address `_is_public_address` loop stays). Returning the
  vetted IP is additive to the current "raise-or-pass" contract.
- **Connect to the pinned IP while preserving Host + SNI.** Make the actual
  connection go to the vetted IP rather than re-resolving the name. Concretely, build
  the request against the **pinned IP** for the socket connection while keeping:
  - the original **`Host` header** = the original hostname (so name-based virtual
    hosting resolves the right site), and
  - the **TLS SNI / `server_hostname`** = the original hostname (so certificate
    validation matches the cert's name, not the bare IP).

  The standard-library-only constraint holds (`urllib` / `http.client` / `ssl` /
  `socket`). Implement via a custom `https` handler / `HTTPSConnection` that accepts
  a fixed connect-IP and passes the original hostname as the SSL `server_hostname`
  and sets the `Host` header — wired through the existing `_build_opener` /
  `director.open` seam (the `opener` parameter the functions already accept stays the
  injectable test seam). Redirects remain refused (`_NoRedirectHandler`).
- **Apply uniformly to both JSON and text paths.** `_open_json` and `_open_text`
  (and thus `post_json` / `get_json` / `fetch_text`) all route their connection
  through the pinned-IP opener. The size/content-type/JSON limits, the active-content
  stripping, and the sanitized error messages are unchanged.
- **Add an adversarial rebind test** (see Verification) plus tests proving the Host
  header and SNI carry the original hostname.

## Non-Goals

- **No relaxation of the SSRF policy.** Every resolved IP must still be public; the
  scheme is still HTTPS-only; the host allowlist still applies; redirects are still
  refused; CGNAT/private/link-local/metadata addresses are still blocked
  (FTY-081's `is_global` requirement is untouched). This story only ensures the
  connection lands on a vetted address.
- **No change to the host allowlist mechanism, content-type allowlist, size caps,
  timeout, or active-content stripping.**
- **No new third-party dependency** — standard library only, preserving the
  provider-layer no-deps invariant.
- **No error-message change that could leak the URL, host, vetted IP, headers, or
  bodies.** The pinned IP is **never** placed into an error message, log, or the
  `FetchPolicyError.reason` label (it is non-sensitive but the module's discipline is
  to echo none of the request detail; keep it that way).
- **Do not touch the LLM HTTP transport** (`app/llm/transport.py`) — it is a
  different layer with its own (non-SSRF) policy and is out of scope.

## Contracts

- **None.** `docs/security/security-baseline.md` documents the SSRF/egress boundary
  this strengthens; it is **not** modified. The observable fetch behaviour for a
  legitimate allowlisted host is unchanged (same data returned); only the connect
  target is now provably the vetted IP.

## Security / Privacy

- **This is the entire point of the story.** It closes a DNS-rebinding TOCTOU in the
  SSRF defence-in-depth: the address that passed the public-IP check is the address
  connected to, so a mid-flight rebind to a private IP for an allowlisted host can no
  longer reach an internal target. **No new trust boundary is introduced** — the
  egress path already exists; this tightens it.
- **Preserve fail-closed everywhere:** any failure to obtain a vetted IP, build the
  pinned connection, or match the cert (SNI) must refuse/raise a sanitized error, not
  fall back to name-based connection. A correctness slip here weakens the SSRF
  boundary, so the adversarial test is mandatory, not optional.
- **No leak:** error messages, `reason` labels, and logs continue to carry no URL,
  host, IP, header, or body.

## Acceptance Criteria

- `assert_url_allowed` returns (or a delegate exposes) the vetted public IP it
  approved, while still raising `FetchPolicyError` for scheme/host/resolution/
  private-address violations exactly as before (every resolved address still required
  public).
- `post_json`, `get_json`, and `fetch_text` connect to the pinned vetted IP, not a
  connect-time re-resolution of the name.
- The outbound request carries the **original hostname** in both the `Host` header
  and the TLS SNI (`server_hostname`), so virtual-hosting and certificate validation
  still succeed against a normal allowlisted host.
- **Adversarial rebind test passes:** a resolver that returns a public IP at
  check time and a private IP at connect time results in a **refused** fetch (no
  connection to the private IP) — the connection only ever targets the vetted
  (check-time, public) address.
- The full existing SSRF/adversarial suite still passes (no regression):
  scheme/host-allowlist/private/CGNAT/redirect refusals, size caps, content-type
  allowlist, active-content stripping, sanitized errors.
- No URL/host/IP/header/body appears in any error, `reason` label, or log.
- No new dependency; standard library only. `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **New adversarial DNS-rebind test:** drive the injectable `resolver` (and the
  connection seam) so the host vets to a public IP but the connect step would resolve
  to a private IP; assert the fetch refuses and never opens a socket to the private
  address. Use the existing injectable `resolver`/`opener` seams so no real DNS or
  network is touched.
- **Host/SNI preservation tests:** assert the request sent through the pinned-IP
  opener carries the original hostname in the `Host` header and as the SSL
  `server_hostname`, against a normal (single-address, public) host.
- **Regression:** the full existing `hardened_fetch` SSRF/adversarial suite stays
  green unchanged — scheme/host/private/CGNAT/redirect refusals, oversize/content-
  type rejections, active-content stripping, and the no-leak error assertions.

## Planning Notes

- **`ready_with_notes`, not `ready`:** the work is safe and fully specified, but the
  *implementation technique* — pinning a connect IP through `urllib` while preserving
  `Host` and TLS `server_hostname` — is the load-bearing detail and has more than one
  viable shape. This note is non-blocking guidance, not a missing decision.
- **Recommended technique (standard library only):** subclass
  `http.client.HTTPSConnection` so it `connect()`s to a fixed IP but passes the
  original hostname as `server_hostname` to `ssl_context.wrap_socket` (SNI + cert
  check) and sets the `Host` header to the original hostname; wrap it in a custom
  `urllib.request.HTTPSHandler` (`https_open`) and install it via the existing
  `_build_opener`. The `opener` parameter the public functions already accept stays
  the test seam. This keeps redirects refused (`_NoRedirectHandler`) and changes only
  *where the socket connects*, not the policy.
- **Pick one vetted IP deterministically:** when the host resolves to several public
  IPs (all already required public), connect to the first; do **not** fall back to
  name resolution if that IP fails (fail closed). Document the choice inline.
- **If the pinned-connection approach proves to require deep/brittle `urllib`
  surgery** (e.g. a Python-version-specific private API), **stop and flag it** for an
  alternative (such as a vetted-IP-with-Host-and-SNI request built without a custom
  connection class) rather than shipping something fragile — the SSRF boundary must
  stay robust.
- **No evidence research:** this is a security-correctness change with no
  health/nutrition/behavioural decision.

## Readiness Sanity Pass

- **Product decision gaps:** none — security-correctness only, no
  health/nutrition/behavioural question, so no evidence research applies. The one
  open *implementation* choice (the pinning technique) is captured as a non-blocking
  note with a recommended approach and a stop-and-flag fallback, which is exactly why
  the state is `ready_with_notes` rather than `ready`.
- **Cross-lane impact:** primary **estimator**; **security-privacy** rides along as a
  non-serializing focus lane (the SSRF-hardening intent), which per the scope
  guardrail does **not** count as a second boundary. **Single boundary, zero big
  rocks:** no public contract change, no schema migration / new table, **no new
  untrusted-input trust boundary** — the egress path already exists; this tightens an
  existing one. One serializing estimator-lane file.
- **Size:** `review_focus` = 5 (at the ceiling, not over) — all five facets are the
  one coherent "connect to the vetted IP safely" change in a single file, not a split
  trigger; `requires_context` = 3 (well under 8). One story.
- **Security/privacy risk:** **high** — it is SSRF defence-in-depth, and a subtle
  slip (cert/SNI mismatch, accidental name re-resolution, or a leaked IP) would
  weaken rather than strengthen the boundary. Risk estimated up deliberately: the
  mandatory adversarial rebind test plus the full unchanged SSRF regression suite are
  the required safety net, and the implementation note flags escalation if the urllib
  technique turns brittle. (high → routes to the strongest model under the model
  policy.)
- **Verification path:** `make verify` + a new adversarial rebind test (resolver
  diverges check-time vs connect-time → refused), Host/SNI-preservation tests, and the
  full existing SSRF/adversarial suite green unchanged — all via the injectable
  resolver/opener seams (no real network).
- **Assumptions safe for autonomy:** yes — scoped to one file, the SSRF policy is
  unchanged (only the connect target is pinned), the technique is recommended with a
  fallback, and the adversarial + regression suites bound correctness. No migration,
  contract, UI, or new dependency.
</content>
