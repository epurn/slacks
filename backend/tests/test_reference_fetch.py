"""Searched-result (reference-source) fetch egress policy tests (FTY-166).

Pins the security boundary for fetching **arbitrary public search-result pages**:
the reference tier has no pre-configured host allowlist (the eligible targets are
whatever public URLs search returned), so these tests prove the compensating
controls hold against attacker-chosen URLs — HTTPS only, public-IP only (loopback /
private / link-local / metadata refused), redirects refused, bounded body size and
content type, active content stripped, content-free errors, and a fail-closed
``enabled`` switch. The DNS resolver and opener are injected so every check runs
without real network access.
"""

from __future__ import annotations

import socket
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    _NoRedirectHandler,
)
from app.estimator.reference_fetch import (
    ReferenceFetchSettings,
    fetch_searched_result,
    load_reference_fetch_settings,
)

RESULT_URL = "https://nutrition-reference.example.com/foods/gruel"


def _resolver_returning(*ips: str) -> Any:
    def _resolve(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)) for ip in ips
        ]

    return _resolve


class _ExplodingOpener:
    """A transport that must never be reached for a policy-blocked URL."""

    def open(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("transport must not be reached for a blocked URL")


class _Headers:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type

    def get_content_charset(self) -> str:
        return "utf-8"


class _Response:
    def __init__(self, body: bytes, *, content_type: str = "text/html") -> None:
        self._body = body
        self.headers = _Headers(content_type)

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: Any) -> Literal[False]:
        return False

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._body
        return self._body[:amount]


class _Opener:
    def __init__(self, response: _Response) -> None:
        self._response = response

    def open(self, request: Any, timeout: float | None = None) -> Any:
        return self._response


# --- settings ---------------------------------------------------------------------


def test_defaults_are_enabled_with_bounded_inert_text_policy() -> None:
    settings = load_reference_fetch_settings({})

    # On by default, like search itself (FTY-164): the reference tier is a default
    # capability, and the off switch is the explicit operator opt-out.
    assert settings.enabled is True
    assert settings.is_available is True
    # Inert-text content types only; sane bounded limits.
    assert settings.allowed_content_types == frozenset(
        {"text/html", "application/xhtml+xml", "text/plain"}
    )
    assert settings.max_bytes > 0
    assert settings.timeout_seconds > 0


def test_env_parses_enabled_flag_and_limits() -> None:
    settings = load_reference_fetch_settings(
        {
            "FATTY_REFERENCE_FETCH_ENABLED": "false",
            "FATTY_REFERENCE_FETCH_TIMEOUT_SECONDS": "7",
            "FATTY_REFERENCE_FETCH_MAX_BYTES": "1024",
            "FATTY_REFERENCE_FETCH_ALLOWED_CONTENT_TYPES": " text/HTML , text/plain ,",
        }
    )

    assert settings.enabled is False
    assert settings.is_available is False
    assert settings.timeout_seconds == 7.0
    assert settings.max_bytes == 1024
    assert settings.allowed_content_types == frozenset({"text/html", "text/plain"})


def test_unknown_env_key_is_rejected() -> None:
    with pytest.raises(ValidationError):  # extra="forbid"
        ReferenceFetchSettings(unexpected="x")  # type: ignore[call-arg]


# --- fail-closed switch and scheme/host policy --------------------------------------


def test_disabled_settings_refuse_every_fetch_before_any_transport() -> None:
    settings = ReferenceFetchSettings(enabled=False)

    with pytest.raises(FetchPolicyError) as exc:
        fetch_searched_result(
            RESULT_URL,
            settings,
            resolver=_resolver_returning("23.1.2.3"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "reference_fetch_disabled"


@pytest.mark.parametrize(
    "url",
    [
        "http://nutrition-reference.example.com/foods/gruel",  # plain HTTP
        "http://localhost/foods",  # no local-HTTP exception on this path
        "file:///etc/passwd",
        "ftp://nutrition-reference.example.com/x",
    ],
)
def test_non_https_result_url_is_refused(url: str) -> None:
    with pytest.raises(FetchPolicyError) as exc:
        fetch_searched_result(
            url,
            ReferenceFetchSettings(),
            resolver=_resolver_returning("23.1.2.3"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "scheme_not_allowed"


def test_hostless_url_is_refused() -> None:
    with pytest.raises(FetchPolicyError) as exc:
        fetch_searched_result(
            "https:///no-host-here",
            ReferenceFetchSettings(),
            resolver=_resolver_returning("23.1.2.3"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "host_not_allowed"


# --- SSRF: private / loopback / link-local / metadata targets ------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.8",  # RFC 1918 private
        "192.168.1.20",  # RFC 1918 private
        "169.254.169.254",  # link-local / cloud metadata service
        "100.64.0.1",  # RFC 6598 CGNAT
        "0.0.0.0",  # unspecified  # noqa: S104 — an SSRF target under test, not a bind
    ],
)
def test_result_host_resolving_to_non_public_address_is_blocked(ip: str) -> None:
    # A public-looking result hostname whose DNS answer points inward is refused
    # before any socket opens — the searched-result path keeps the full SSRF posture
    # even though the host itself cannot be pre-allowlisted.
    with pytest.raises(FetchPolicyError) as exc:
        fetch_searched_result(
            RESULT_URL,
            ReferenceFetchSettings(),
            resolver=_resolver_returning(ip),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "private_address_blocked"


def test_mixed_public_and_private_resolution_is_blocked() -> None:
    # Every resolved address must be public; one inward-pointing record poisons the
    # whole set (no pick-the-public-one relaxation).
    with pytest.raises(FetchPolicyError) as exc:
        fetch_searched_result(
            RESULT_URL,
            ReferenceFetchSettings(),
            resolver=_resolver_returning("23.1.2.3", "10.0.0.8"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "private_address_blocked"


def test_private_ip_literal_result_url_is_blocked() -> None:
    with pytest.raises(FetchPolicyError) as exc:
        fetch_searched_result(
            "https://192.168.1.20/facts",
            ReferenceFetchSettings(),
            resolver=_resolver_returning("192.168.1.20"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "private_address_blocked"


def test_redirects_are_refused_on_the_shared_opener_path() -> None:
    # The searched-result fetch rides fetch_text, whose opener installs the
    # no-redirect handler: every 3xx is refused rather than followed, so a public
    # result page cannot bounce the request to a private/off-policy target.
    handler = _NoRedirectHandler()
    with pytest.raises(FetchPolicyError) as exc:
        handler.redirect_request(None, None, 302, "Found", {}, "https://10.0.0.1/private")
    assert exc.value.reason == "redirect_blocked"


# --- response bounds ---------------------------------------------------------------


def _fetch(response: _Response, **settings_kwargs: Any) -> str:
    return fetch_searched_result(
        RESULT_URL,
        ReferenceFetchSettings(**settings_kwargs),
        resolver=_resolver_returning("23.1.2.3"),
        opener=_Opener(response),  # type: ignore[arg-type]
    )


def test_oversized_result_body_fails_closed_without_echoing_the_url() -> None:
    with pytest.raises(FetchResponseError) as exc:
        _fetch(_Response(b"x" * 64), max_bytes=10)
    assert "too large" in str(exc.value)
    assert RESULT_URL not in str(exc.value)


@pytest.mark.parametrize(
    "content_type",
    ["application/pdf", "image/png", "application/octet-stream", "text/javascript"],
)
def test_non_text_content_type_fails_closed(content_type: str) -> None:
    with pytest.raises(FetchResponseError) as exc:
        _fetch(_Response(b"data", content_type=content_type))
    assert "disallowed content type" in str(exc.value)
    assert RESULT_URL not in str(exc.value)


def test_result_page_is_reduced_to_inert_text() -> None:
    body = (
        b"<html><head><script>window.location='http://169.254.169.254/'</script></head>"
        b'<body><p onclick="steal()">Gruel: 60 kcal per 100 g</p>'
        b'<a href="javascript:evil()">link</a></body></html>'
    )
    text = _fetch(_Response(body))

    assert "Gruel: 60 kcal per 100 g" in text
    assert "169.254.169.254" not in text
    assert "onclick" not in text
    assert "javascript" not in text
    # No markup of any kind survives — the output is inert text only.
    assert "<" not in text and ">" not in text
