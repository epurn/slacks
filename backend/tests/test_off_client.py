"""Tests for the hardened Open Food Facts barcode client (FTY-060).

Exercise the full mapping with a stubbed (network-free) transport: the client sends
only the normalized, digits-only barcode (no personal context, no secret key), maps
the OFF payload to canonical per-100g :class:`ProductFacts` (preferring per-100g and
converting per-serving when needed), treats an energy-less or not-found product as a
non-match, and classifies transport failures as retryable or terminal. Also pin the
config contract: a non-https base URL fails closed and the source is on by default.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.off import (
    OFF_SOURCE,
    OffClient,
    OffResponseError,
    OffSettings,
    OffTransientError,
    load_off_settings,
    normalize_barcode,
)

# A minimal OFF v2 product reply with per-100g facts.
_COLA_RESPONSE: dict[str, Any] = {
    "status": 1,
    "product": {
        "product_name": "Cola",
        "serving_quantity": 330,
        "serving_size": "330 ml",
        "nutriments": {
            "energy-kcal_100g": 42.0,
            "proteins_100g": 0.0,
            "carbohydrates_100g": 10.6,
            "fat_100g": 0.1,
        },
    },
}

# A product carrying only per-serving facts plus a gram serving size (50 g).
_PROTEIN_BAR_RESPONSE: dict[str, Any] = {
    "status": 1,
    "product": {
        "product_name": "Protein Bar",
        "serving_quantity": 50,
        "nutriments": {
            "energy-kcal_serving": 200.0,
            "proteins_serving": 20.0,
            "carbohydrates_serving": 15.0,
            "fat_serving": 7.0,
        },
    },
}


class _RecordingTransport:
    """A fake transport that records its call and returns a canned reply (or raises)."""

    def __init__(self, reply: dict[str, Any] | Exception) -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _client(reply: dict[str, Any] | Exception) -> tuple[OffClient, _RecordingTransport]:
    transport = _RecordingTransport(reply)
    return OffClient(OffSettings(), transport=transport), transport


def test_lookup_maps_per_100g_product_to_canonical_facts() -> None:
    client, _ = _client(_COLA_RESPONSE)

    facts = client.lookup("0123456789012")

    assert facts is not None
    assert facts.source == OFF_SOURCE
    assert facts.source_ref == "open_food_facts:0123456789012"
    assert facts.query_key == "0123456789012"
    assert facts.barcode == "0123456789012"
    assert facts.facts.calories == pytest.approx(42.0)
    assert facts.facts.carbs_g == pytest.approx(10.6)
    assert facts.facts.fat_g == pytest.approx(0.1)
    assert facts.default_serving_g == pytest.approx(330.0)
    assert facts.content_hash  # a non-empty fingerprint


def test_lookup_converts_per_serving_facts_to_per_100g() -> None:
    client, _ = _client(_PROTEIN_BAR_RESPONSE)

    facts = client.lookup("0123456789012")

    assert facts is not None
    # 50 g serving → ×2 to reach per-100g.
    assert facts.facts.calories == pytest.approx(400.0)
    assert facts.facts.protein_g == pytest.approx(40.0)
    assert facts.facts.carbs_g == pytest.approx(30.0)
    assert facts.facts.fat_g == pytest.approx(14.0)
    assert facts.default_serving_g == pytest.approx(50.0)


def test_lookup_sends_only_normalized_barcode_and_user_agent() -> None:
    client, transport = _client(_COLA_RESPONSE)

    # Separators are stripped; only the digits reach OFF.
    client.lookup("012-345 678 9012")

    call = transport.calls[0]
    assert "0123456789012" in call["url"]
    # A non-secret identifying user-agent is sent; no api key, no personal context.
    assert call["headers"]["User-Agent"]
    assert "X-Api-Key" not in call["headers"]
    # Only the barcode and the static field list are in the URL — nothing else.
    assert "012-345" not in call["url"]


def test_lookup_skips_product_without_energy() -> None:
    no_energy = {
        "status": 1,
        "product": {"product_name": "Mystery", "nutriments": {"proteins_100g": 5.0}},
    }
    client, _ = _client(no_energy)

    assert client.lookup("0123456789012") is None


def test_lookup_per_serving_without_gram_serving_is_non_match() -> None:
    # Per-serving energy but no gram serving size → no derivable per-100g basis.
    reply = {
        "status": 1,
        "product": {"product_name": "Drink", "nutriments": {"energy-kcal_serving": 100.0}},
    }
    client, _ = _client(reply)

    assert client.lookup("0123456789012") is None


def test_lookup_returns_none_when_not_found() -> None:
    client, _ = _client({"status": 0, "product": None})

    assert client.lookup("0123456789012") is None


def test_lookup_returns_none_for_invalid_barcode_without_calling() -> None:
    client, transport = _client(_COLA_RESPONSE)

    assert client.lookup("12345") is None  # not a valid UPC/EAN length
    assert transport.calls == []


def test_disabled_source_makes_no_call() -> None:
    transport = _RecordingTransport(_COLA_RESPONSE)
    client = OffClient(OffSettings(enabled=False), transport=transport)

    assert client.enabled is False
    assert client.lookup("0123456789012") is None
    assert transport.calls == []


def test_transient_transport_error_maps_to_off_transient() -> None:
    client, _ = _client(FetchTransientError("provider request failed"))

    with pytest.raises(OffTransientError):
        client.lookup("0123456789012")


@pytest.mark.parametrize("error", [FetchResponseError("bad"), FetchPolicyError("host_not_allowed")])
def test_response_and_policy_errors_map_to_off_response(error: Exception) -> None:
    client, _ = _client(error)

    with pytest.raises(OffResponseError):
        client.lookup("0123456789012")


def test_settings_require_https_base_url() -> None:
    with pytest.raises(ValidationError):
        OffSettings(base_url="http://insecure.example.com")


def test_settings_allowed_hosts_and_product_url() -> None:
    settings = OffSettings()

    assert settings.allowed_hosts == frozenset({"world.openfoodfacts.org"})
    assert settings.product_url("0123456789012").startswith(
        "https://world.openfoodfacts.org/api/v2/product/0123456789012.json"
    )


def test_off_enabled_by_default_and_available_without_credentials() -> None:
    settings = OffSettings()

    assert settings.enabled is True
    assert settings.is_available is True


def test_load_off_settings_reads_env_prefix() -> None:
    settings = load_off_settings(
        {"FATTY_OFF_ENABLED": "false", "FATTY_OFF_USER_AGENT": "Custom/2.0 (contact)"}
    )

    assert settings.enabled is False
    assert settings.user_agent == "Custom/2.0 (contact)"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0123456789012", "0123456789012"),  # EAN-13
        ("012345678905", "012345678905"),  # UPC-A
        ("01234565", "01234565"),  # EAN-8
        ("012-345 678 9012", "0123456789012"),  # separators stripped → EAN-13
        ("abc", None),  # no digits
        ("12345", None),  # too short
        ("123456789012345", None),  # too long
        ("", None),
        (None, None),
    ],
)
def test_normalize_barcode(raw: str | None, expected: str | None) -> None:
    assert normalize_barcode(raw) == expected
