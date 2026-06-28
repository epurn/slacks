"""Adversarial SSRF / egress-hardening suite (FTY-073).

Consolidates and *extends* the FTY-044/078 hardened-fetch negatives
(``tests/test_hardened_fetch.py``) into one cross-cutting proof that the egress
boundary fails closed for every untrusted target the threat model names. It fills
the gaps the per-feature suite left: IPv6 inward targets (loopback / unique-local
/ link-local / IPv4-mapped), IPv4 multicast and reserved ranges, a host that
resolves to a *mix* of public and private addresses, and DNS lookup failures —
across all three transport verbs (``post_json`` / ``get_json`` / ``fetch_text``).
Plus the ``get_json`` body limits (oversize / non-JSON / non-object content type).

Every blocked case must refuse **before a socket opens** (the exploding opener
proves transport is never reached) and carry a content-free reason.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    assert_url_allowed,
    fetch_text,
    get_json,
    post_json,
)
from tests.security._harness import (
    ExplodingOpener,
    FakeOpener,
    FakeResponse,
    resolver_empty,
    resolver_raising,
    resolver_returning,
)

USDA = frozenset({"api.nal.usda.gov"})
USDA_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
OFFICIAL = frozenset({"www.example-restaurant.com"})
OFFICIAL_URL = "https://www.example-restaurant.com/menu/nutrition"


# --- inward IPs the per-feature suite did not already pin -----------------------


@pytest.mark.parametrize(
    "inward_ip",
    [
        # IPv6 inward targets (the FTY-044 suite covered only IPv4).
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 unique-local (private)
        "fd00::1",  # IPv6 unique-local (private)
        "fe80::1",  # IPv6 link-local
        "::ffff:169.254.169.254",  # IPv4-mapped IPv6 of the cloud metadata service
        "::ffff:10.0.0.1",  # IPv4-mapped IPv6 of an RFC1918 host
        # IPv4 ranges the per-feature suite did not pin.
        "224.0.0.1",  # multicast
        "239.255.255.250",  # multicast (SSDP)
        "240.0.0.1",  # reserved
        "255.255.255.255",  # broadcast / reserved
    ],
)
def test_inward_ipv6_and_special_ipv4_targets_are_blocked(inward_ip: str) -> None:
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(USDA_URL, allowed_hosts=USDA, resolver=resolver_returning(inward_ip))
    assert exc.value.reason == "private_address_blocked"


def test_cgnat_shared_space_is_blocked_fail_closed() -> None:
    # FTY-081: RFC 6598 carrier-grade-NAT space (100.64.0.0/10) is non-global, so the
    # is_global allowlist-by-property check refuses it fail-closed (was FTY-073-F1).
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(USDA_URL, allowed_hosts=USDA, resolver=resolver_returning("100.64.0.1"))
    assert exc.value.reason == "private_address_blocked"


def test_host_resolving_to_mixed_public_and_private_is_blocked() -> None:
    # A host with several DNS records, one of which is private, must fail closed —
    # the policy inspects every resolved address, not just the first.
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(
            USDA_URL,
            allowed_hosts=USDA,
            resolver=resolver_returning("23.1.2.3", "10.0.0.5"),
        )
    assert exc.value.reason == "private_address_blocked"


def test_dns_failure_fails_closed_as_refusal() -> None:
    # A DNS lookup error is a refusal (fail closed), never a fetch attempt, and the
    # host name is not echoed into the reason.
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(
            USDA_URL, allowed_hosts=USDA, resolver=resolver_raising(OSError("no such host"))
        )
    assert exc.value.reason == "host_resolution_failed"
    assert "usda" not in str(exc.value)


def test_dns_empty_result_fails_closed() -> None:
    with pytest.raises(FetchPolicyError) as exc:
        assert_url_allowed(USDA_URL, allowed_hosts=USDA, resolver=resolver_empty())
    assert exc.value.reason == "host_resolution_failed"


# --- every transport verb refuses a blocked target before opening a socket ------


@pytest.mark.parametrize(
    ("url", "ip", "reason"),
    [
        ("http://api.nal.usda.gov/x", "23.1.2.3", "scheme_not_allowed"),
        ("file:///etc/passwd", "23.1.2.3", "scheme_not_allowed"),
        ("https://evil.example.com/x", "23.1.2.3", "host_not_allowed"),
        (USDA_URL, "::1", "private_address_blocked"),
        (USDA_URL, "169.254.169.254", "private_address_blocked"),
    ],
)
def test_post_json_refuses_before_socket(url: str, ip: str, reason: str) -> None:
    with pytest.raises(FetchPolicyError) as exc:
        post_json(
            url,
            headers={"X-Api-Key": "super-secret-key"},
            payload={"query": "rice"},
            timeout_seconds=1.0,
            allowed_hosts=USDA,
            resolver=resolver_returning(ip),
            opener=ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == reason


@pytest.mark.parametrize(
    ("url", "ip", "reason"),
    [
        ("http://api.nal.usda.gov/x", "23.1.2.3", "scheme_not_allowed"),
        ("https://evil.example.com/x", "23.1.2.3", "host_not_allowed"),
        (USDA_URL, "fc00::1", "private_address_blocked"),
        (USDA_URL, "239.255.255.250", "private_address_blocked"),
    ],
)
def test_get_json_refuses_before_socket(url: str, ip: str, reason: str) -> None:
    with pytest.raises(FetchPolicyError) as exc:
        get_json(
            url,
            timeout_seconds=1.0,
            allowed_hosts=USDA,
            resolver=resolver_returning(ip),
            opener=ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == reason


def test_fetch_text_refuses_metadata_via_ipv4_mapped_ipv6_before_socket() -> None:
    with pytest.raises(FetchPolicyError) as exc:
        fetch_text(
            OFFICIAL_URL,
            timeout_seconds=1.0,
            allowed_hosts=OFFICIAL,
            resolver=resolver_returning("::ffff:169.254.169.254"),
            opener=ExplodingOpener(),  # type: ignore[arg-type]
        )
    assert exc.value.reason == "private_address_blocked"


# --- get_json body limits (the FTY-078 text fetch pinned these only for text) ---


def _get_json(opener: FakeOpener, **kwargs: Any) -> dict[str, Any]:
    return get_json(
        USDA_URL,
        timeout_seconds=5.0,
        allowed_hosts=USDA,
        resolver=resolver_returning("23.1.2.3"),
        opener=opener,  # type: ignore[arg-type]
        **kwargs,
    )


def test_get_json_rejects_oversize_body_fail_closed() -> None:
    response = FakeResponse(b'{"x":1}' + b" " * 50, content_type="application/json")
    with pytest.raises(FetchResponseError) as exc:
        _get_json(FakeOpener(response), max_bytes=10)
    assert "too large" in str(exc.value)
    assert USDA_URL not in str(exc.value)


def test_get_json_rejects_non_json_content_type_fail_closed() -> None:
    response = FakeResponse(b'{"x":1}', content_type="text/html")
    with pytest.raises(FetchResponseError) as exc:
        _get_json(FakeOpener(response))
    assert "non-JSON content type" in str(exc.value)


def test_get_json_rejects_non_object_json_body_fail_closed() -> None:
    # A JSON array (not an object) is rejected — a provider reply must be a mapping.
    response = FakeResponse(json.dumps([1, 2, 3]).encode(), content_type="application/json")
    with pytest.raises(FetchResponseError) as exc:
        _get_json(FakeOpener(response))
    assert "non-object JSON body" in str(exc.value)
