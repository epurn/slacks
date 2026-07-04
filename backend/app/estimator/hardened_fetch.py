"""Hardened outbound HTTP for backend evidence lookups (FTY-044).

The estimator never gets open-ended network access: every external call goes
through this module, which enforces the evidence-retrieval security boundary
(``docs/architecture/evidence-retrieval.md`` and ``docs/security/security-baseline.md``):

- **HTTPS only.** ``http``/``file``/anything else is rejected before a socket opens.
  The single, narrow exception (FTY-164) is an explicitly named **local** HTTP
  service: a caller may pass ``local_http_hosts`` naming the local search service
  (e.g. the dev-stack SearXNG container), and plain HTTP is then allowed for
  exactly those hosts — and only when every resolved address is a loopback or
  private (RFC 1918 / ULA) target, never link-local (so the ``169.254.169.254``
  metadata service stays unreachable), so the exception cannot be repointed at
  the public internet or an internal metadata endpoint. Only :func:`get_json`
  exposes the seam; :func:`post_json` and :func:`fetch_text` remain HTTPS-only.
- **Host allowlist.** Only hosts the caller explicitly allowlists (the configured
  provider host) may be contacted; everything else fails closed.
- **SSRF / private-network blocking.** The host is resolved and every resolved IP
  must be a public, globally-routable address — loopback, private, link-local
  (incl. the cloud metadata service ``169.254.169.254``), multicast, reserved, and
  unspecified addresses are refused, so a DNS entry that points inward cannot be used.
- **Vetted-IP pinning (no DNS-rebinding TOCTOU, FTY-137).** The connection targets
  the exact IP the policy vetted rather than re-resolving the name at connect time,
  so a host that returns a public IP during the check and a private IP at connect
  cannot reach an internal target. The original hostname is still carried in the
  ``Host`` header and the TLS SNI (``server_hostname``) so virtual-hosting and
  certificate validation are unaffected.
- **No redirects.** A 3xx is refused rather than followed, so a redirect cannot
  bounce an allowlisted request to an internal target.
- **Bounded time and size.** A per-request timeout and a response-size cap apply.
- **Active-content stripping.** The official-source text fetch (:func:`fetch_text`,
  FTY-078) returns inert text only: scripts, styles, and other active-content
  elements are dropped and every tag/attribute is discarded, so downstream
  extraction never sees executable markup. The content type is allowlisted too.

Built on the standard library only (``urllib`` / ``socket`` / ``ipaddress`` /
``html.parser``) so the provider layer adds no dependencies. Error messages never
include the URL, headers (which carry the API key), the request body, or the
response body, so a failed fetch is always safe to log.
"""

from __future__ import annotations

import html.parser
import http.client
import ipaddress
import json
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

#: Default cap on a response body (1 MiB). Evidence responses are small JSON; a
#: larger body is treated as hostile/misbehaving and rejected.
DEFAULT_MAX_BYTES = 1_000_000

#: Default cap on an official-source page body (2 MiB). HTML pages are larger than
#: the small JSON evidence replies but still bounded; a larger body is treated as
#: hostile/misbehaving and rejected fail-closed.
DEFAULT_MAX_TEXT_BYTES = 2_000_000

#: Content types :func:`fetch_text` will accept. Anything else (an image, a PDF,
#: ``application/octet-stream``, an active-content type) fails closed.
DEFAULT_TEXT_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})

#: The only scheme an evidence fetch may use.
_ALLOWED_SCHEME = "https"

#: The scheme admitted solely for hosts named in ``local_http_hosts`` (FTY-164).
_LOCAL_HTTP_SCHEME = "http"

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
    headers, or bodies. ``status_code`` carries the HTTP status when one is known
    (a 5xx); it is ``None`` for a timeout or connection failure.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FetchResponseError(Exception):
    """A non-retryable response failure (4xx, oversized, or non-JSON body).

    The remote answered but the answer is unusable; retrying the identical request
    will not help. The message is sanitized. ``status_code`` carries the HTTP status
    when one is known (a 4xx, e.g. ``429`` rate-limit); it is ``None`` for an
    oversized or non-JSON body. The code is a non-sensitive integer, never the body.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def assert_url_allowed(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    resolver: Resolver = socket.getaddrinfo,
    local_http_hosts: frozenset[str] = frozenset(),
) -> str:
    """Vet ``url`` against the fetch policy and return the vetted public IP.

    Enforces: ``https`` scheme, host in ``allowed_hosts`` (compared lower-cased),
    and every resolved IP for that host globally routable (no loopback/private/
    link-local/reserved targets). Pure except for the (injectable) DNS lookup.

    ``local_http_hosts`` is the narrow FTY-164 exception for a **local** service
    (the self-hosted SearXNG container): plain ``http`` is admitted only for a
    host named in that set, and then the address requirement **inverts** — every
    resolved IP must be loopback or private (RFC 1918 / ULA), never link-local /
    metadata / public, so the exception can neither leak plaintext to the public
    internet nor be re-pointed at ``169.254.169.254``. With the default empty set
    the behaviour is exactly the HTTPS-only policy above.

    Returns the single vetted IP the connection must pin to — the first resolved
    address (every resolved address has already been required public, so any of
    them is a valid target; the first is chosen deterministically). Returning the
    address is additive to the raise-or-pass contract: a policy violation still
    raises :class:`FetchPolicyError` before any address is returned. Callers pin
    this IP at connect time so the address that passed the check is provably the
    address connected to (closing the DNS-rebinding TOCTOU, FTY-137).
    """

    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    host_lower = (parts.hostname or "").lower()
    local_http = scheme == _LOCAL_HTTP_SCHEME and host_lower in local_http_hosts
    if scheme != _ALLOWED_SCHEME and not local_http:
        raise FetchPolicyError("scheme_not_allowed")

    host = parts.hostname
    if not host or host.lower() not in allowed_hosts:
        raise FetchPolicyError("host_not_allowed")

    port = parts.port or (80 if local_http else 443)
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
        # Every resolved address must satisfy the scheme's posture — no relaxation,
        # no short-circuit before the full set is checked (a mixed set still fails).
        if local_http:
            # The local-HTTP exception is for a local service only: a name that
            # resolves outward (public) or sideways (link-local/metadata) is refused.
            if not _is_local_service_address(address):
                raise FetchPolicyError("local_http_target_not_local")
        elif not _is_public_address(address):
            raise FetchPolicyError("private_address_blocked")
    # All addresses vetted; pin the first one deterministically.
    return str(addresses[0])


def _is_public_address(address: str) -> bool:
    """Return whether ``address`` is a public, globally-routable *unicast* IP.

    Allowlist-by-property, not denylist-by-category: an address is accepted only
    when it is globally routable (:attr:`ipaddress.ip_address.is_global`) and is
    not multicast. This is fail-closed by construction — any non-global range is
    rejected, including ranges no enumerated category names, such as RFC 6598
    carrier-grade-NAT space (``100.64.0.0/10``). Loopback, private, link-local
    (incl. the metadata service), reserved, and unspecified addresses are all
    non-global and so refused. Multicast is excluded explicitly: the stdlib
    classes IPv4 multicast as ``is_global`` even though it is never a valid unicast
    egress target, so the positive requirement is paired with ``not is_multicast``.
    """

    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


def _is_local_service_address(address: str) -> bool:
    """Return whether ``address`` is a loopback or private-network *service* IP.

    The address posture for the FTY-164 local-HTTP exception — allowlist-by-property
    again, but inverted: only loopback (``127.0.0.0/8`` / ``::1``) and ordinary
    private unicast ranges (RFC 1918 / IPv6 ULA — where a compose/dev-stack service
    like the SearXNG container lives) are accepted. Link-local (incl. the
    ``169.254.169.254`` metadata service), multicast, reserved, unspecified, and
    every **public** address are refused, so a local-HTTP host that resolves
    anywhere but a genuinely local service fails closed.
    """

    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    return ip.is_private and not (
        ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that refuses every redirect instead of following it."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        raise FetchPolicyError("redirect_blocked")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """An ``HTTPSConnection`` that connects to a fixed, pre-vetted IP.

    The socket is opened to ``pinned_ip`` instead of re-resolving ``host``, so the
    address that passed :func:`assert_url_allowed` is provably the address connected
    to (no connect-time DNS re-resolution → no DNS-rebinding TOCTOU). The original
    hostname is preserved for both the TLS SNI / certificate check
    (``server_hostname``) and the ``Host`` header (set by ``urllib`` from the
    request host, which is left unchanged), so virtual-hosting and certificate
    validation behave exactly as a name-based connection would.
    """

    def __init__(
        self, host: str, *, pinned_ip: str, context: ssl.SSLContext | None = None, **kwargs: Any
    ) -> None:
        # Build a default verifying context when none is supplied (the default
        # opener path) so cert validation + hostname check stay on; keep our own
        # reference so we never reach into the base class's private ``_context``.
        if context is None:
            context = ssl.create_default_context()
        super().__init__(host, context=context, **kwargs)
        self._pinned_ip = pinned_ip
        self._pinned_context = context

    def connect(self) -> None:
        # Connect to the vetted IP, never re-resolving the name; present the
        # original hostname for SNI + cert validation. The pinned IP is deliberately
        # never logged or surfaced. No source address is ever bound (no proxy/bind is
        # configured), so the connect uses the default.
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._pinned_context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """An ``HTTPSHandler`` that routes every connection through a pinned IP.

    Subclassing the default ``HTTPSHandler`` means ``build_opener`` installs this in
    place of the stock one, so ``https`` requests open against the vetted IP while
    redirects stay refused by :class:`_NoRedirectHandler`.
    """

    def __init__(self, pinned_ip: str) -> None:
        super().__init__()
        self._pinned_ip = pinned_ip

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        pinned_ip = self._pinned_ip

        class _Conn(_PinnedHTTPSConnection):
            def __init__(self, host: str, **kwargs: Any) -> None:
                super().__init__(host, pinned_ip=pinned_ip, **kwargs)

        return self.do_open(_Conn, req)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """A plain ``HTTPConnection`` that connects to a fixed, pre-vetted local IP.

    The plain-HTTP counterpart of :class:`_PinnedHTTPSConnection`, used only for the
    FTY-164 local-service exception: the socket opens to ``pinned_ip`` (already
    required loopback/private by :func:`assert_url_allowed`) instead of re-resolving
    the name, so the local-HTTP path gets the same no-DNS-rebinding guarantee as the
    HTTPS path. The ``Host`` header still carries the original service name.
    """

    def __init__(self, host: str, *, pinned_ip: str, **kwargs: Any) -> None:
        super().__init__(host, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    """An ``HTTPHandler`` that routes every plain-HTTP connection through a pinned IP.

    Installed alongside :class:`_PinnedHTTPSHandler` so the rare vetted local-HTTP
    request (FTY-164) cannot fall through to the stock handler's connect-time DNS
    re-resolution.
    """

    def __init__(self, pinned_ip: str) -> None:
        super().__init__()
        self._pinned_ip = pinned_ip

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        pinned_ip = self._pinned_ip

        class _Conn(_PinnedHTTPConnection):
            def __init__(self, host: str, **kwargs: Any) -> None:
                super().__init__(host, pinned_ip=pinned_ip, **kwargs)

        return self.do_open(_Conn, req)


def _build_opener(pinned_ip: str) -> urllib.request.OpenerDirector:
    """An opener that blocks redirects and pins the connection to ``pinned_ip``."""

    return urllib.request.build_opener(
        _NoRedirectHandler(), _PinnedHTTPSHandler(pinned_ip), _PinnedHTTPHandler(pinned_ip)
    )


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

    vetted_ip = assert_url_allowed(url, allowed_hosts=allowed_hosts, resolver=resolver)

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 — scheme/host validated above
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    return _open_json(
        request,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        opener=opener,
        vetted_ip=vetted_ip,
    )


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    max_bytes: int = DEFAULT_MAX_BYTES,
    resolver: Resolver = socket.getaddrinfo,
    opener: urllib.request.OpenerDirector | None = None,
    local_http_hosts: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """GET ``url`` through the hardened policy and return the JSON object body.

    Same security guarantees as :func:`post_json` (scheme/host/SSRF validated before
    the socket opens, redirects refused, response size-capped and required to be a
    JSON object); the read-only verb for providers whose lookup is a GET (e.g. Open
    Food Facts' barcode endpoint). ``local_http_hosts`` opts a named **local**
    service (the self-hosted SearXNG container, FTY-164) into plain HTTP under the
    inverted address posture documented on :func:`assert_url_allowed`; leave it
    empty (the default) for the standard HTTPS-only policy.

    Raises:
        FetchPolicyError: the URL violated the policy, or a redirect was attempted.
        FetchTransientError: timeout, connection failure, or a ``5xx`` response.
        FetchResponseError: a ``4xx`` response, an oversized body, or a non-JSON body.
    """

    vetted_ip = assert_url_allowed(
        url, allowed_hosts=allowed_hosts, resolver=resolver, local_http_hosts=local_http_hosts
    )

    request = urllib.request.Request(  # noqa: S310 — scheme/host validated above
        url,
        headers={**(headers or {}), "Accept": "application/json"},
        method="GET",
    )
    return _open_json(
        request,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        opener=opener,
        vetted_ip=vetted_ip,
    )


def _open_json(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
    max_bytes: int,
    opener: urllib.request.OpenerDirector | None,
    vetted_ip: str,
) -> dict[str, Any]:
    """Open a pre-validated request, enforce the size/content-type/JSON limits.

    Shared by :func:`post_json` and :func:`get_json`; callers must have already run
    :func:`assert_url_allowed` against the request URL and pass the ``vetted_ip`` it
    returned so the connection pins to that address. Error messages never echo the
    URL, headers, request body, or response body.
    """

    director = opener or _build_opener(vetted_ip)
    try:
        with director.open(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read()  # drain without surfacing the body
        message = f"provider returned HTTP {status}"
        if status >= http.HTTPStatus.INTERNAL_SERVER_ERROR:
            raise FetchTransientError(message, status_code=status) from None
        raise FetchResponseError(message, status_code=status) from None
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


def fetch_text(
    url: str,
    *,
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    allowed_content_types: frozenset[str] = DEFAULT_TEXT_CONTENT_TYPES,
    max_bytes: int = DEFAULT_MAX_TEXT_BYTES,
    headers: dict[str, str] | None = None,
    resolver: Resolver = socket.getaddrinfo,
    opener: urllib.request.OpenerDirector | None = None,
) -> str:
    """Fetch an allowlisted official-source page and return sanitized inert text.

    The official-source egress path (FTY-078): the URL is validated against the full
    SSRF policy (scheme/host/private-address) *before* the socket opens, redirects are
    refused, and the response is bounded by ``timeout_seconds``, ``max_bytes``, and an
    ``allowed_content_types`` allowlist. The body is then reduced to **inert text** —
    scripts/styles/active-content elements are dropped and every tag and attribute is
    discarded — so downstream extraction only ever sees text, never executable markup.

    Error messages never echo the URL, headers, request body, or response body, so a
    failed fetch is always safe to log.

    Raises:
        FetchPolicyError: the URL violated the policy, or a redirect was attempted.
        FetchTransientError: timeout, connection failure, or a ``5xx`` response.
        FetchResponseError: a ``4xx`` response, an oversized body, or a disallowed
            content type.
    """

    vetted_ip = assert_url_allowed(url, allowed_hosts=allowed_hosts, resolver=resolver)

    request = urllib.request.Request(  # noqa: S310 — scheme/host validated above
        url,
        headers={
            **(headers or {}),
            "Accept": "text/html, application/xhtml+xml, text/plain",
        },
        method="GET",
    )
    return _open_text(
        request,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        allowed_content_types=allowed_content_types,
        opener=opener,
        vetted_ip=vetted_ip,
    )


def _open_text(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
    max_bytes: int,
    allowed_content_types: frozenset[str],
    opener: urllib.request.OpenerDirector | None,
    vetted_ip: str,
) -> str:
    """Open a pre-validated request and return its body as stripped inert text.

    Callers must have already run :func:`assert_url_allowed` against the request URL
    and pass the ``vetted_ip`` it returned so the connection pins to that address.
    Enforces the size and content-type limits, decodes the body using the response
    charset (replacing undecodable bytes), and strips active content. Error messages
    never echo the URL, headers, request body, or response body.
    """

    director = opener or _build_opener(vetted_ip)
    try:
        with director.open(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset()
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read()  # drain without surfacing the body
        message = f"provider returned HTTP {status}"
        if status >= http.HTTPStatus.INTERNAL_SERVER_ERROR:
            raise FetchTransientError(message, status_code=status) from None
        raise FetchResponseError(message, status_code=status) from None
    except (urllib.error.URLError, TimeoutError):
        # URLError covers DNS/connection failures; TimeoutError the socket timeout.
        # The original is suppressed so its args (which can echo the URL) never leak.
        raise FetchTransientError("provider request failed") from None

    if len(raw) > max_bytes:
        raise FetchResponseError("provider response too large")
    if content_type not in allowed_content_types:
        raise FetchResponseError("provider returned a disallowed content type")
    text = _decode_body(raw, charset)
    return strip_active_content(text)


def _decode_body(raw: bytes, charset: str | None) -> str:
    """Decode ``raw`` using the response charset, falling back to UTF-8.

    Undecodable bytes are replaced rather than raised, and an unknown/invalid charset
    name (which is attacker-influenced via the ``Content-Type`` header) falls back to
    UTF-8 instead of escaping as an uncaught ``LookupError``.
    """

    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


#: Elements whose entire subtree is active content or non-text and must be dropped
#: outright (the metadata service, scripts, styles, embedded objects, vector/active
#: graphics). Their text content never reaches downstream extraction.
_ACTIVE_CONTENT_ELEMENTS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "iframe",
        "frame",
        "frameset",
        "object",
        "embed",
        "applet",
        "svg",
        "math",
        "canvas",
    }
)

#: Block-level elements whose boundaries become newlines, so the inert text keeps a
#: little structure for downstream extraction instead of collapsing to one line.
_BLOCK_ELEMENTS = frozenset(
    {
        "p",
        "div",
        "br",
        "hr",
        "li",
        "ul",
        "ol",
        "tr",
        "table",
        "thead",
        "tbody",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "nav",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "td",
        "th",
        "dd",
        "dt",
        "dl",
        "figure",
        "figcaption",
    }
)

#: Collapse any run of whitespace within a single line to one space.
_INLINE_WS_RE = re.compile(r"[^\S\n]+")


class _InertTextExtractor(html.parser.HTMLParser):
    """Reduce HTML to inert text: drop active-content subtrees, discard all tags.

    Only text nodes outside active-content elements survive; every tag and every
    attribute (where ``onclick=`` / ``href="javascript:…"`` would live) is discarded,
    so the output cannot carry executable markup. Block-element boundaries become
    newlines so a little document structure is preserved.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        #: Depth of nested active-content elements currently open; text is dropped
        #: whenever this is non-zero.
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: Any) -> None:
        if tag in _ACTIVE_CONTENT_ELEMENTS:
            self._skip_depth += 1
        elif tag in _BLOCK_ELEMENTS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, _attrs: Any) -> None:
        # Self-closing tag (e.g. ``<br/>``): no subtree, just a possible break.
        if tag in _BLOCK_ELEMENTS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _ACTIVE_CONTENT_ELEMENTS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif tag in _BLOCK_ELEMENTS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_inert_text(self) -> str:
        joined = "".join(self._chunks)
        lines = (_INLINE_WS_RE.sub(" ", line).strip() for line in joined.split("\n"))
        return "\n".join(line for line in lines if line)


def strip_active_content(body: str) -> str:
    """Return ``body`` reduced to inert text with all active content removed.

    Scripts, styles, and other active-content subtrees are dropped, every tag and
    attribute is discarded, HTML entities are unescaped, and whitespace is normalized.
    The result is plain text safe for downstream extraction — it can contain no
    ``<script>``, inline event handler, or ``javascript:`` URL because no markup
    survives at all. Pure (no I/O); also used directly in tests.
    """

    parser = _InertTextExtractor()
    parser.feed(body)
    parser.close()
    return parser.get_inert_text()
