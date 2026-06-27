"""Official-source fetch egress policy tests (FTY-078).

Pins the configuration boundary for official-source page retrieval: a fail-closed
default (empty allowlist), env parsing of the host allowlist / limits, and that the
wrapper applies the shared hardened-fetch SSRF policy. The DNS resolver and opener
are injected so every check runs without real network access.
"""

from __future__ import annotations

import socket
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from app.estimator.hardened_fetch import FetchPolicyError
from app.estimator.official_fetch import (
    OfficialFetchSettings,
    fetch_official_source,
    load_official_fetch_settings,
)

ALLOWED_HOST = "www.example-restaurant.com"
PAGE_URL = f"https://{ALLOWED_HOST}/menu/nutrition"


def _resolver_returning(ip: str) -> Any:
    def _resolve(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]

    return _resolve


def test_defaults_are_fail_closed_with_no_allowlist() -> None:
    settings = load_official_fetch_settings({})

    assert settings.allowed_hosts == frozenset()
    assert settings.is_available is False
    # Inert-text content types only; sane bounded limits.
    assert settings.allowed_content_types == frozenset(
        {"text/html", "application/xhtml+xml", "text/plain"}
    )
    assert settings.max_bytes > 0
    assert settings.timeout_seconds > 0


def test_env_parses_csv_allowlist_lowercased_and_trimmed() -> None:
    settings = load_official_fetch_settings(
        {
            "FATTY_OFFICIAL_FETCH_ALLOWED_HOSTS": " www.A.com , www.B.com ,",
            "FATTY_OFFICIAL_FETCH_TIMEOUT_SECONDS": "7",
            "FATTY_OFFICIAL_FETCH_MAX_BYTES": "1024",
        }
    )

    assert settings.allowed_hosts == frozenset({"www.a.com", "www.b.com"})
    assert settings.is_available is True
    assert settings.timeout_seconds == 7.0
    assert settings.max_bytes == 1024


def test_unknown_env_key_is_rejected() -> None:
    with pytest.raises(ValidationError):  # extra="forbid"
        OfficialFetchSettings(unexpected="x")  # type: ignore[call-arg]


def test_empty_allowlist_blocks_every_target_fail_closed() -> None:
    settings = OfficialFetchSettings()

    class _ExplodingOpener:
        def open(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
            raise AssertionError("transport must not be reached for a blocked URL")

    with pytest.raises(FetchPolicyError) as exc:
        fetch_official_source(
            PAGE_URL,
            settings,
            resolver=_resolver_returning("23.1.2.3"),
            opener=_ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "host_not_allowed"


def test_allowlisted_host_resolving_to_metadata_is_blocked() -> None:
    settings = OfficialFetchSettings(allowed_hosts=frozenset({ALLOWED_HOST}))

    with pytest.raises(FetchPolicyError) as exc:
        fetch_official_source(
            PAGE_URL,
            settings,
            resolver=_resolver_returning("169.254.169.254"),
        )
    assert exc.value.reason == "private_address_blocked"


def test_fetch_official_source_returns_inert_text_for_allowlisted_page() -> None:
    settings = OfficialFetchSettings(allowed_hosts=frozenset({ALLOWED_HOST}))

    class _Headers:
        def get_content_type(self) -> str:
            return "text/html"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _Response:
        headers = _Headers()

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> Literal[False]:
            return False

        def read(self, amount: int = -1) -> bytes:
            return b"<html><body><script>evil()</script><p>Fries 365 kcal</p></body></html>"

    class _Opener:
        def open(self, request: Any, timeout: float | None = None) -> Any:
            return _Response()

    text = fetch_official_source(
        PAGE_URL,
        settings,
        resolver=_resolver_returning("23.1.2.3"),
        opener=_Opener(),  # type: ignore[arg-type]
    )
    assert "Fries 365 kcal" in text
    assert "evil" not in text
    assert "<" not in text
