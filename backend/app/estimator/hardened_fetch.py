"""Hardened outbound HTTP for backend evidence lookups (FTY-044).

The estimator never gets open-ended network access: every external call goes
through this module, which enforces the evidence-retrieval security boundary
(``docs/architecture/evidence-retrieval.md`` and ``docs/security/security-baseline.md``):

- **HTTPS only.** ``http``/``file``/anything else is rejected before a socket opens.
- **Host allowlist.** Only hosts the caller explicitly allowlists (the configured
  provider host) may be contacted; everything else fails closed.
- **SSRF / private-network blocking.** The host is resolved and every resolved IP
  must be a public, globally-routable address — loopback, private, link-local
  (incl. the cloud metadata service ``169.254.169.254``), multicast, reserved, and
  unspecified addresses are refused, so a DNS entry that points inward cannot be used.
- **No redirects.** A 3xx is refused rather than followed, so a redirect cannot
  bounce an allowlisted request to an internal target.
- **Bounded time and size.** A per-request timeout and a response-size cap apply.

Built on the standard library only (``urllib`` / ``socket`` / ``ipaddress``) so the
provider layer adds no dependencies. Error messages never include the URL, headers
(which carry the API key), the request body, or the response body, so a failed
fetch is always safe to log.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

#: Default cap on a response body (1 MiB). Evidence responses are small JSON; a
#: larger body is treated as hostile/misbehaving and rejected.
DEFAULT_MAX_BYTES = 1_000_000

#: The only scheme an evidence fetch may use.
_ALLOWED_SCHEME = "https"

#: Resolver signature (``socket.getaddrinfo``), injectable so tests can drive the
#: private-address checks without real DNS.
Resolver = Callable[..., list[Any]]


class FetchPolicyError(Exception):
    """A request violated the fetch security policy (scheme/host/SSRF/redirect).

    Carries a short, fixed ``reason`` label (never the URL or any user data) so it
    is safe to persist on an estimation run or log. Raised *before* any data is
    fetched (or on a blocked redirect), so it always means "refused", never "failed".
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class FetchTransientError(Exception):
    """A transient transport failure (timeout, connection error, or 5xx).

    Retryable by the caller. The message is sanitized — it never echoes the URL,
    headers, or bodies.
    """


class FetchResponseError(Exception):
    """A non-retryable response failure (4xx, oversized, or non-JSON body).

    The remote answered but the answer is unusable; retrying the identical request
    will not help. The message is sanitized.
    """


def assert_url_allowed(
    url: str, *, allowed_hosts: frozenset[str], resolver: Resolver = socket.getaddrinfo
) -> None:
    """Raise :class:`FetchPolicyError` unless ``url`` satisfies the fetch policy.

    Enforces: ``https`` scheme, host in ``allowed_hosts`` (compared lower-cased),
    and every resolved IP for that host globally routable (no loopback/private/
    link-local/reserved targets). Pure except for the (injectable) DNS lookup.
    """

    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != _ALLOWED_SCHEME:
        raise FetchPolicyError("scheme_not_allowed")

    host = parts.hostname
    if not host or host.lower() not in allowed_hosts:
        raise FetchPolicyError("host_not_allowed")

    port = parts.port or 443
    try:
        infos = resolver(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        # DNS failure is treated as a refusal (fail closed); the host name is not
        # echoed into the error.
        raise FetchPolicyError("host_resolution_failed") from exc

    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise FetchPolicyError("host_resolution_failed")
    for address in addresses:
        if not _is_public_address(address):
            raise FetchPolicyError("private_address_blocked")


def _is_public_address(address: str) -> bool:
    """Return whether ``address`` is a public, globally-routable IP.

    Anything loopback, private, link-local (incl. the metadata service), multicast,
    reserved, or unspecified is non-public and must be blocked.
    """

    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that refuses every redirect instead of following it."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise FetchPolicyError("redirect_blocked")


def _build_opener() -> urllib.request.OpenerDirector:
    """An opener that blocks redirects and uses no proxy/auth handlers."""

    return urllib.request.build_opener(_NoRedirectHandler())


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    max_bytes: int = DEFAULT_MAX_BYTES,
    resolver: Resolver = socket.getaddrinfo,
    opener: urllib.request.OpenerDirector | None = None,
) -> dict[str, Any]:
    """POST ``payload`` as JSON to ``url`` through the hardened policy; return JSON.

    The URL is validated against the policy (scheme/host/SSRF) before the socket
    opens, redirects are refused, and the response is size-capped and required to be
    a JSON object.

    Raises:
        FetchPolicyError: the URL violated the policy, or a redirect was attempted.
        FetchTransientError: timeout, connection failure, or a ``5xx`` response.
        FetchResponseError: a ``4xx`` response, an oversized body, or a non-JSON body.
    """

    assert_url_allowed(url, allowed_hosts=allowed_hosts, resolver=resolver)

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 — scheme/host validated above
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    director = opener or _build_opener()
    try:
        with director.open(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read()  # drain without surfacing the body
        if status >= 500:
            raise FetchTransientError(f"provider returned HTTP {status}") from None
        raise FetchResponseError(f"provider returned HTTP {status}") from None
    except (urllib.error.URLError, TimeoutError):
        # URLError covers DNS/connection failures; TimeoutError the socket timeout.
        # The original is suppressed so its args (which can echo the URL) never leak.
        raise FetchTransientError("provider request failed") from None

    if len(raw) > max_bytes:
        raise FetchResponseError("provider response too large")
    if content_type != "application/json":
        raise FetchResponseError("provider returned a non-JSON content type")
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        raise FetchResponseError("provider returned a non-JSON body") from None
    if not isinstance(parsed, dict):
        raise FetchResponseError("provider returned a non-object JSON body") from None
    return parsed
