"""Minimal JSON-over-HTTPS transport for provider adapters.

Implemented on the standard library (``urllib``) so the provider layer adds no
runtime dependencies. Providers call :func:`post_json`; tests monkeypatch it to
avoid live network calls. Error mapping lives here so every provider classifies
failures identically: timeouts, connection errors, and ``5xx`` become
retryable :class:`LLMTransientError`; ``4xx`` and non-JSON bodies become
non-retryable :class:`LLMResponseError`.

Error messages and the raised exception chain never include the request URL,
headers (which carry the key), the request body (the prompt), or the response
body, so transport failures are safe to log.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.llm.errors import LLMConfigurationError, LLMResponseError, LLMTransientError

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """POST ``payload`` as JSON to ``url`` and return the parsed JSON response.

    Raises:
        LLMConfigurationError: ``url`` is not an ``http(s)`` URL.
        LLMTransientError: timeout, connection failure, or a ``5xx`` response.
        LLMResponseError: a ``4xx`` response or a non-JSON body.
    """

    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        # Fail closed rather than let urllib open file:/ or other schemes.
        raise LLMConfigurationError("provider base URL must be an http(s) URL")

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 — scheme validated above
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(  # noqa: S310 — scheme validated above
            request, timeout=timeout_seconds
        ) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        # Drain so the connection can be reused, but never surface the body.
        exc.read()
        if status >= 500:
            raise LLMTransientError(f"provider returned HTTP {status}") from None
        raise LLMResponseError(f"provider returned HTTP {status}") from None
    except (urllib.error.URLError, TimeoutError):
        # URLError covers DNS/connection failures; TimeoutError covers the
        # socket timeout. The original is suppressed so its args (which can echo
        # the URL) never leak into logs.
        raise LLMTransientError("provider request failed") from None

    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        raise LLMResponseError("provider returned a non-JSON body") from None
    if not isinstance(parsed, dict):
        raise LLMResponseError("provider returned a non-object JSON body") from None
    return parsed
