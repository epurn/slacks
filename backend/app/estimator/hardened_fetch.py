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
import ipaddress
import json
import re
import socket
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
    return _open_json(request, timeout_seconds=timeout_seconds, max_bytes=max_bytes, opener=opener)


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    max_bytes: int = DEFAULT_MAX_BYTES,
    resolver: Resolver = socket.getaddrinfo,
    opener: urllib.request.OpenerDirector | None = None,
) -> dict[str, Any]:
    """GET ``url`` through the hardened policy and return the JSON object body.

    Same security guarantees as :func:`post_json` (scheme/host/SSRF validated before
    the socket opens, redirects refused, response size-capped and required to be a
    JSON object); the read-only verb for providers whose lookup is a GET (e.g. Open
    Food Facts' barcode endpoint).

    Raises:
        FetchPolicyError: the URL violated the policy, or a redirect was attempted.
        FetchTransientError: timeout, connection failure, or a ``5xx`` response.
        FetchResponseError: a ``4xx`` response, an oversized body, or a non-JSON body.
    """

    assert_url_allowed(url, allowed_hosts=allowed_hosts, resolver=resolver)

    request = urllib.request.Request(  # noqa: S310 — scheme/host validated above
        url,
        headers={**(headers or {}), "Accept": "application/json"},
        method="GET",
    )
    return _open_json(request, timeout_seconds=timeout_seconds, max_bytes=max_bytes, opener=opener)


def _open_json(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
    max_bytes: int,
    opener: urllib.request.OpenerDirector | None,
) -> dict[str, Any]:
    """Open a pre-validated request, enforce the size/content-type/JSON limits.

    Shared by :func:`post_json` and :func:`get_json`; callers must have already run
    :func:`assert_url_allowed` against the request URL. Error messages never echo the
    URL, headers, request body, or response body.
    """

    director = opener or _build_opener()
    try:
        with director.open(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read()  # drain without surfacing the body
        message = f"provider returned HTTP {status}"
        if status >= 500:
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

    assert_url_allowed(url, allowed_hosts=allowed_hosts, resolver=resolver)

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
    )


def _open_text(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
    max_bytes: int,
    allowed_content_types: frozenset[str],
    opener: urllib.request.OpenerDirector | None,
) -> str:
    """Open a pre-validated request and return its body as stripped inert text.

    Callers must have already run :func:`assert_url_allowed` against the request URL.
    Enforces the size and content-type limits, decodes the body using the response
    charset (replacing undecodable bytes), and strips active content. Error messages
    never echo the URL, headers, request body, or response body.
    """

    director = opener or _build_opener()
    try:
        with director.open(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset()
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read()  # drain without surfacing the body
        message = f"provider returned HTTP {status}"
        if status >= 500:
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

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _ACTIVE_CONTENT_ELEMENTS:
            self._skip_depth += 1
        elif tag in _BLOCK_ELEMENTS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
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
