"""SSRF / allowlist negative tests for the hardened fetch policy (FTY-044).

These pin the security boundary the evidence-retrieval design requires
(``docs/architecture/evidence-retrieval.md``): only HTTPS, only allowlisted hosts,
and never a private/loopback/link-local target — even when a DNS entry resolves
inward. The DNS resolver is injected so the private-address checks run without real
network access, and ``post_json`` is exercised against a fake opener to prove the
policy gate runs before any socket work.
"""

from __future__ import annotations

import io
import socket
import urllib.error
import urllib.request
from typing import Any, Literal

import pytest

from app.estimator.hardened_fetch import (
    DEFAULT_TEXT_CONTENT_TYPES,
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
    _NoRedirectHandler,
    assert_url_allowed,
    fetch_text,
    get_json,
    post_json,
    strip_active_content,
)

ALLOWED = frozenset({"api.nal.usda.gov"})
OFF_ALLOWED = frozenset({"world.openfoodfacts.org"})
OFFICIAL_ALLOWED = frozenset({"www.example-restaurant.com"})
OFFICIAL_URL = "https://www.example-restaurant.com/menu/nutrition"


def _resolver_returning(ip: str) -> Any:
    """A fake ``getaddrinfo`` that resolves any host to ``ip``."""

    def _resolve(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]

    return _resolve


def test_https_allowlisted_public_host_is_allowed() -> None:
    # A public IP behind an allowlisted host passes the policy.
    assert_url_allowed(
        "https://api.nal.usda.gov/fdc/v1/foods/search",
        allowed_hosts=ALLOWED,
        resolver=_resolver_returning("23.1.2.3"),
    )


def test_non_https_scheme_is_blocked() -> None:
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(
            "http://api.nal.usda.gov/fdc/v1/foods/search",
            allowed_hosts=ALLOWED,
            resolver=_resolver_returning("23.1.2.3"),
        )
    assert exc.value.reason == "scheme_not_allowed"


def test_non_allowlisted_host_is_blocked() -> None:
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(
            "https://evil.example.com/fdc/v1/foods/search",
            allowed_hosts=ALLOWED,
            resolver=_resolver_returning("23.1.2.3"),
        )
    assert exc.value.reason == "host_not_allowed"


@pytest.mark.parametrize(
    "private_ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "192.168.1.10",  # private
        "169.254.169.254",  # link-local cloud metadata service
        "0.0.0.0",  # unspecified  # noqa: S104
    ],
)
def test_allowlisted_host_resolving_to_private_ip_is_blocked(private_ip: str) -> None:
    # DNS-rebinding defence: even an allowlisted host is refused when it resolves to
    # a non-public address.
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            allowed_hosts=ALLOWED,
            resolver=_resolver_returning(private_ip),
        )
    assert exc.value.reason == "private_address_blocked"


def test_post_json_refuses_before_opening_a_socket() -> None:
    # A disallowed URL must never reach the transport. The opener raises if touched.
    class _ExplodingOpener:
        def open(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
            raise AssertionError("transport must not be reached for a blocked URL")

    with pytest.raises(FetchPolicyError):
        post_json(
            "http://api.nal.usda.gov/fdc/v1/foods/search",
            headers={"X-Api-Key": "secret"},
            payload={"query": "rice"},
            timeout_seconds=1.0,
            allowed_hosts=ALLOWED,
            resolver=_resolver_returning("23.1.2.3"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )


def test_get_json_refuses_non_https_off_target_before_opening_a_socket() -> None:
    # The OFF (GET) transport gates on the same policy: a non-https barcode URL is
    # refused before the socket opens. Proves the source fails closed.
    class _ExplodingOpener:
        def open(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
            raise AssertionError("transport must not be reached for a blocked URL")

    with pytest.raises(FetchPolicyError):
        get_json(
            "http://world.openfoodfacts.org/api/v2/product/0123456789012.json",
            timeout_seconds=1.0,
            allowed_hosts=OFF_ALLOWED,
            resolver=_resolver_returning("23.1.2.3"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )


def test_get_json_blocks_non_allowlisted_off_host() -> None:
    with pytest.raises(FetchPolicyError) as exc:
        get_json(
            "https://evil.example.com/api/v2/product/0123456789012.json",
            timeout_seconds=1.0,
            allowed_hosts=OFF_ALLOWED,
            resolver=_resolver_returning("23.1.2.3"),
        )
    assert exc.value.reason == "host_not_allowed"


def test_get_json_blocks_off_host_resolving_to_metadata_service() -> None:
    # SSRF / DNS-rebinding defence on the OFF transport: even an allowlisted host is
    # refused when it resolves to the cloud metadata address.
    with pytest.raises(FetchPolicyError) as exc:
        get_json(
            "https://world.openfoodfacts.org/api/v2/product/0123456789012.json",
            timeout_seconds=1.0,
            allowed_hosts=OFF_ALLOWED,
            resolver=_resolver_returning("169.254.169.254"),
        )
    assert exc.value.reason == "private_address_blocked"


# --- FTY-078: official-source text fetch (active-content stripping + egress) --------


class _FakeHeaders:
    """Minimal stand-in for an ``http.client`` headers object used by the fetcher."""

    def __init__(self, content_type: str, charset: str | None) -> None:
        self._content_type = content_type
        self._charset = charset

    def get_content_type(self) -> str:
        return self._content_type

    def get_content_charset(self) -> str | None:
        return self._charset


class _FakeResponse:
    """A context-manager HTTP response exposing only what ``_open_text`` reads."""

    def __init__(
        self, body: bytes, *, content_type: str = "text/html", charset: str | None = "utf-8"
    ) -> None:
        self._body = body
        self.headers = _FakeHeaders(content_type, charset)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: Any) -> Literal[False]:
        return False

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._body
        return self._body[:amount]


class _FakeOpener:
    """An opener that returns a canned response (or raises) without any socket."""

    def __init__(self, response: Any = None, *, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc

    def open(self, request: Any, timeout: float | None = None) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._response


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        OFFICIAL_URL,
        status,
        "err",
        {},  # type: ignore[arg-type]
        io.BytesIO(b"secret error body"),
    )


def _fetch(opener: _FakeOpener, **kwargs: Any) -> str:
    return fetch_text(
        OFFICIAL_URL,
        timeout_seconds=5.0,
        allowed_hosts=OFFICIAL_ALLOWED,
        resolver=_resolver_returning("23.1.2.3"),
        opener=opener,  # type: ignore[arg-type]
        **kwargs,
    )


def test_fetch_text_returns_active_content_stripped_inert_text() -> None:
    body = (
        b"<html><head><title>Menu</title>"
        b"<script>alert('xss'); window.location='http://169.254.169.254/'</script>"
        b"<style>.x{color:red}</style></head>"
        b"<body><h1>Burger</h1>"
        b'<p onclick="steal()">Calories: 500 kcal</p>'
        b'<a href="javascript:evil()">link</a>'
        b'<iframe src="http://10.0.0.1/"></iframe></body></html>'
    )
    text = _fetch(_FakeOpener(_FakeResponse(body)))

    # Visible facts survive; active content does not.
    assert "Burger" in text
    assert "Calories: 500 kcal" in text
    assert "Menu" in text
    assert "alert" not in text
    assert "javascript" not in text
    assert "onclick" not in text
    assert "steal" not in text
    assert "color:red" not in text
    assert "169.254.169.254" not in text
    # No markup of any kind survives — the output is inert text only.
    assert "<" not in text and ">" not in text


def test_fetch_text_falls_back_to_utf8_on_invalid_charset() -> None:
    # The charset is attacker-influenced via Content-Type; an unknown codec name must
    # fall back to UTF-8, never escape as an uncaught LookupError.
    response = _FakeResponse(b"<p>Soup 120 kcal</p>", charset="totally-bogus-charset")
    text = _fetch(_FakeOpener(response))
    assert "Soup 120 kcal" in text


def test_fetch_text_rejects_disallowed_content_type_fail_closed() -> None:
    response = _FakeResponse(b"<svg/>", content_type="image/svg+xml")
    with pytest.raises(FetchResponseError) as exc:
        _fetch(_FakeOpener(response))
    # Content-free: no URL or body echoed.
    assert "disallowed content type" in str(exc.value)
    assert OFFICIAL_URL not in str(exc.value)


def test_fetch_text_rejects_oversize_body_fail_closed() -> None:
    response = _FakeResponse(b"x" * 50)
    with pytest.raises(FetchResponseError) as exc:
        _fetch(_FakeOpener(response), max_bytes=10)
    assert "too large" in str(exc.value)
    assert OFFICIAL_URL not in str(exc.value)


def test_fetch_text_maps_5xx_to_transient_without_leaking_body() -> None:
    with pytest.raises(FetchTransientError) as exc:
        _fetch(_FakeOpener(exc=_http_error(503)))
    assert exc.value.status_code == 503
    assert "secret error body" not in str(exc.value)


def test_fetch_text_maps_4xx_to_response_error_without_leaking_body() -> None:
    with pytest.raises(FetchResponseError) as exc:
        _fetch(_FakeOpener(exc=_http_error(404)))
    assert exc.value.status_code == 404
    assert "secret error body" not in str(exc.value)


def test_fetch_text_maps_timeout_to_content_free_transient() -> None:
    with pytest.raises(FetchTransientError) as exc:
        _fetch(_FakeOpener(exc=TimeoutError("connect to 10.0.0.1 timed out")))
    # The original message (which can echo a target) is suppressed.
    assert "10.0.0.1" not in str(exc.value)
    assert str(exc.value) == "provider request failed"


@pytest.mark.parametrize(
    ("url", "resolver_ip", "expected_reason"),
    [
        # file: and non-https schemes.
        ("file:///etc/passwd", "23.1.2.3", "scheme_not_allowed"),
        ("http://www.example-restaurant.com/menu", "23.1.2.3", "scheme_not_allowed"),
        # off-allowlist host.
        ("https://evil.example.com/menu", "23.1.2.3", "host_not_allowed"),
        # allowlisted host resolving inward (private/loopback/link-local/metadata).
        (OFFICIAL_URL, "127.0.0.1", "private_address_blocked"),
        (OFFICIAL_URL, "10.0.0.5", "private_address_blocked"),
        (OFFICIAL_URL, "169.254.169.254", "private_address_blocked"),
    ],
)
def test_fetch_text_ssrf_suite_refuses_before_opening_a_socket(
    url: str, resolver_ip: str, expected_reason: str
) -> None:
    class _ExplodingOpener:
        def open(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
            raise AssertionError("transport must not be reached for a blocked URL")

    with pytest.raises(FetchPolicyError) as exc:
        fetch_text(
            url,
            timeout_seconds=5.0,
            allowed_hosts=OFFICIAL_ALLOWED,
            resolver=_resolver_returning(resolver_ip),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == expected_reason


def test_redirects_are_refused_so_redirect_to_private_cannot_bounce() -> None:
    # Every 3xx is refused rather than followed (or re-validated), so a redirect can
    # never bounce an allowlisted request to a private/off-allowlist target.
    handler = _NoRedirectHandler()
    with pytest.raises(FetchPolicyError) as exc:
        handler.redirect_request(
            urllib.request.Request(OFFICIAL_URL),  # noqa: S310 — https URL, never opened
            io.BytesIO(b""),
            302,
            "Found",
            {},
            "https://10.0.0.1/internal",
        )
    assert exc.value.reason == "redirect_blocked"


def test_default_text_content_types_are_inert_only() -> None:
    # The default allowlist is text/HTML only — no active or binary content types.
    assert DEFAULT_TEXT_CONTENT_TYPES == frozenset(
        {"text/html", "application/xhtml+xml", "text/plain"}
    )


def test_strip_active_content_drops_scripts_styles_and_attributes() -> None:
    body = (
        "<div>before"
        "<script>var x = 1;</script>"
        "<noscript>fallback</noscript>"
        "<style>body{}</style>"
        "<img src=x onerror=alert(1)>"
        "after</div>"
    )
    text = strip_active_content(body)
    assert "before" in text
    assert "after" in text
    assert "var x" not in text
    assert "fallback" not in text
    assert "body{}" not in text
    assert "onerror" not in text
    assert "alert" not in text
