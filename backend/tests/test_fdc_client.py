"""Tests for the hardened USDA FoodData Central client (FTY-044).

Exercise the full mapping with a stubbed (network-free) transport: the client sends
only the sanitized food name, carries the API key in a header (never the URL), maps
the FDC payload to canonical per-100g :class:`ProductFacts`, skips energy-less
results, and classifies transport failures as retryable or terminal. Also pin the
config contract: a non-https base URL and a missing key fail closed.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.estimator.fdc import (
    FdcClient,
    FdcResponseError,
    FdcSettings,
    FdcTransientError,
    load_fdc_settings,
)
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)

# A minimal FDC /foods/search reply: white rice, Foundation/SR-Legacy per-100g values.
_RICE_RESPONSE: dict[str, Any] = {
    "foods": [
        {
            "fdcId": 168880,
            "description": "Rice, white, cooked",
            "servingSize": 158.0,
            "servingSizeUnit": "g",
            "foodNutrients": [
                {"nutrientId": 1008, "value": 130.0},
                {"nutrientId": 1003, "value": 2.69},
                {"nutrientId": 1005, "value": 28.2},
                {"nutrientId": 1004, "value": 0.28},
            ],
        }
    ]
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


def _client(reply: dict[str, Any] | Exception) -> tuple[FdcClient, _RecordingTransport]:
    settings = FdcSettings(api_key=SecretStr("test-key"))
    transport = _RecordingTransport(reply)
    return FdcClient(settings, transport=transport), transport


def test_lookup_maps_fdc_food_to_canonical_facts() -> None:
    client, transport = _client(_RICE_RESPONSE)

    facts = client.lookup("White Rice")

    assert facts is not None
    assert facts.source == "usda_fdc"
    assert facts.source_ref == "usda_fdc:168880"
    assert facts.query_key == "white rice"  # normalized, lower-cased
    assert facts.facts.calories == pytest.approx(130.0)
    assert facts.facts.protein_g == pytest.approx(2.69)
    assert facts.facts.carbs_g == pytest.approx(28.2)
    assert facts.facts.fat_g == pytest.approx(0.28)
    assert facts.default_serving_g == pytest.approx(158.0)
    assert facts.content_hash  # a non-empty fingerprint


def test_lookup_sends_key_in_header_and_only_sanitized_query() -> None:
    client, transport = _client(_RICE_RESPONSE)

    client.lookup("White Rice")

    call = transport.calls[0]
    # Key travels in a header, never in the URL/query string.
    assert call["headers"]["X-Api-Key"] == "test-key"
    assert "test-key" not in call["url"]
    # Only the normalized food name is sent — no personal context fields.
    assert call["payload"]["query"] == "white rice"
    assert set(call["payload"]) == {"query", "dataType", "pageSize"}


def test_lookup_skips_results_without_energy() -> None:
    no_energy = {
        "foods": [
            {
                "fdcId": 1,
                "description": "Mystery",
                "foodNutrients": [{"nutrientId": 1003, "value": 5.0}],
            }
        ]
    }
    client, _ = _client(no_energy)

    assert client.lookup("mystery") is None


def test_lookup_returns_none_on_empty_results() -> None:
    client, _ = _client({"foods": []})

    assert client.lookup("nonexistent food") is None


def test_disabled_client_makes_no_call() -> None:
    settings = FdcSettings()  # no api key
    transport = _RecordingTransport(_RICE_RESPONSE)
    client = FdcClient(settings, transport=transport)

    assert client.enabled is False
    assert client.lookup("rice") is None
    assert transport.calls == []


def test_transient_transport_error_maps_to_fdc_transient() -> None:
    client, _ = _client(FetchTransientError("provider request failed"))

    with pytest.raises(FdcTransientError):
        client.lookup("rice")


@pytest.mark.parametrize("error", [FetchResponseError("bad"), FetchPolicyError("host_not_allowed")])
def test_response_and_policy_errors_map_to_fdc_response(error: Exception) -> None:
    client, _ = _client(error)

    with pytest.raises(FdcResponseError):
        client.lookup("rice")


def test_settings_require_https_base_url() -> None:
    with pytest.raises(ValidationError):
        FdcSettings(api_key=SecretStr("k"), base_url="http://insecure.example.com/fdc/v1")


def test_settings_allowed_hosts_derived_from_base_url() -> None:
    settings = FdcSettings(api_key=SecretStr("k"))

    assert settings.allowed_hosts == frozenset({"api.nal.usda.gov"})
    assert settings.search_url == "https://api.nal.usda.gov/fdc/v1/foods/search"


def test_load_fdc_settings_reads_env_prefix() -> None:
    settings = load_fdc_settings({"FATTY_FDC_API_KEY": "from-env", "FATTY_FDC_MAX_RESULTS": "10"})

    assert settings.is_configured is True
    assert settings.max_results == 10
    # The key is a secret: it must not render in repr.
    assert "from-env" not in repr(settings)
