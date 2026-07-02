"""Search query sanitization and local SearXNG host policy."""

from __future__ import annotations

import ipaddress
import re
from typing import Final

#: Upper bound on a sanitized query before egress. Item identity is short; a longer
#: string is a sign of smuggled context and is truncated at the chokepoint.
MAX_QUERY_LEN: Final[int] = 256

#: The only host **names** the SearXNG backend may reach over plain HTTP: the
#: dev-stack service name and localhost. Loopback IP literals are matched by
#: :func:`is_local_search_host`; everything else must be HTTPS.
LOCAL_SEARXNG_HTTP_HOSTS: Final[frozenset[str]] = frozenset({"searxng", "localhost"})

#: Control characters (incl. newlines/tabs) are stripped before egress so a query
#: cannot smuggle multi-line / structured personal context past the chokepoint.
_CONTROL_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f]")

#: Collapse any run of whitespace to a single space.
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


def sanitize_query(query: str) -> str:
    """Return the single sanitized query string that may egress to the provider.

    The **single chokepoint** for data minimization: strips control characters
    (which could smuggle multi-line / structured personal context), collapses
    whitespace, and length-bounds the result. Only item identity reaches this
    function; the adapter never accepts profile, weight, history, or event
    metadata, so the closed provider request shapes cannot carry them.
    """

    no_control = _CONTROL_CHARS_RE.sub(" ", query)
    collapsed = _WHITESPACE_RE.sub(" ", no_control).strip()
    return collapsed[:MAX_QUERY_LEN]


def is_local_search_host(host: str) -> bool:
    """Return whether ``host`` is a local service name eligible for plain HTTP.

    The narrow FTY-164 rule: exactly the dev-stack service names
    (:data:`LOCAL_SEARXNG_HTTP_HOSTS`) plus loopback IP literals. Any other host,
    including private-range IPs and internal DNS names, must use HTTPS.
    """

    lowered = host.lower()
    if lowered in LOCAL_SEARXNG_HTTP_HOSTS:
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False
