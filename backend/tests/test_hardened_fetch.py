"""SSRF / allowlist negative tests for the hardened fetch policy (FTY-044).

These pin the security boundary the evidence-retrieval design requires
(``docs/architecture/evidence-retrieval.md``): only HTTPS, only allowlisted hosts,
and never a private/loopback/link-local target — even when a DNS entry resolves
inward. The DNS resolver is injected so the private-address checks run without real
network access, and ``post_json`` is exercised against a fake opener to prove the
policy gate runs before any socket work.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from app.estimator.hardened_fetch import (
    FetchPolicyError,
    assert_url_allowed,
    get_json,
    post_json,
)

ALLOWED = frozenset({"api.nal.usda.gov"})
OFF_ALLOWED = frozenset({"world.openfoodfacts.org"})


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
