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
    DEFAULT_OFF_USER_AGENT,
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
    # The default outbound identity is the brand user-agent `Slacks/1.0` (OFF etiquette).
    assert call["headers"]["User-Agent"] == DEFAULT_OFF_USER_AGENT
    assert call["headers"]["User-Agent"].startswith("Slacks/1.0")
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


def test_lookup_garbage_serving_quantity_raises_off_response_error() -> None:
    """A non-numeric serving_quantity maps to OffResponseError — never a raw ValidationError."""
    malformed: dict[str, Any] = {
        "status": 1,
        "product": {
            "product_name": "Cola",
            "serving_quantity": "not_a_number",
            "nutriments": {"energy-kcal_100g": 42.0},
        },
    }
    client, _ = _client(malformed)

    with pytest.raises(OffResponseError):
        client.lookup("0123456789012")


def test_lookup_structurally_broken_product_raises_off_response_error() -> None:
    """A product field that is not an object maps to OffResponseError, not ValidationError."""
    malformed: dict[str, Any] = {
        "status": 1,
        "product": "not_a_product_object",
    }
    client, _ = _client(malformed)

    with pytest.raises(OffResponseError):
        client.lookup("0123456789012")


def test_lookup_long_product_name_truncates_not_rejects() -> None:
    """An over-long product_name is truncated to 300 chars — the row still resolves."""
    long_name = "X" * 500
    overlong_response: dict[str, Any] = {
        "status": 1,
        "product": {
            "product_name": long_name,
            "nutriments": {"energy-kcal_100g": 42.0},
        },
    }
    client, _ = _client(overlong_response)

    facts = client.lookup("0123456789012")

    assert facts is not None
    assert len(facts.description) == 300
    assert facts.description == long_name[:300]


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
        {"SLACKS_OFF_ENABLED": "false", "SLACKS_OFF_USER_AGENT": "Custom/2.0 (contact)"}
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


# ---------------------------------------------------------------------------
# Plausibility gate tests (FTY-115)
# ---------------------------------------------------------------------------

_BARCODE = "0123456789012"


def _per_100g_response(
    energy: float, protein: float = 0.0, carbs: float = 0.0, fat: float = 0.0
) -> dict[str, Any]:
    """Build a minimal OFF reply with per-100g nutriment values."""
    return {
        "status": 1,
        "product": {
            "product_name": "Test Product",
            "nutriments": {
                "energy-kcal_100g": energy,
                "proteins_100g": protein,
                "carbohydrates_100g": carbs,
                "fat_100g": fat,
            },
        },
    }


def _per_serving_response(
    energy: float, serving_g: float, protein: float = 0.0, carbs: float = 0.0, fat: float = 0.0
) -> dict[str, Any]:
    """Build a minimal OFF reply with per-serving nutriment values and a gram serving size."""
    return {
        "status": 1,
        "product": {
            "product_name": "Test Product",
            "serving_quantity": serving_g,
            "nutriments": {
                "energy-kcal_serving": energy,
                "proteins_serving": protein,
                "carbohydrates_serving": carbs,
                "fat_serving": fat,
            },
        },
    }


def test_lookup_rejects_over_cap_energy_per_100g() -> None:
    """An OFF product with kJ-mislabelled per-100g energy (~1500/100g) maps to None."""
    client, _ = _client(_per_100g_response(energy=1500.0, protein=10.0, carbs=20.0, fat=50.0))

    assert client.lookup(_BARCODE) is None


def test_lookup_rejects_negative_energy_per_100g() -> None:
    """A negative per-100g energy maps to None."""
    client, _ = _client(_per_100g_response(energy=-10.0))

    assert client.lookup(_BARCODE) is None


def test_lookup_accepts_zero_energy_per_100g() -> None:
    """A genuine zero-calorie food (e.g. sparkling water) is a costable 0-kcal match."""
    client, _ = _client(_per_100g_response(energy=0.0))

    facts = client.lookup(_BARCODE)

    assert facts is not None
    assert facts.facts.calories == pytest.approx(0.0)


def test_lookup_rejects_negative_macro_per_100g() -> None:
    """A negative protein in per-100g facts maps to None."""
    client, _ = _client(_per_100g_response(energy=200.0, protein=-5.0, carbs=10.0, fat=5.0))

    assert client.lookup(_BARCODE) is None


def test_lookup_rejects_over_cap_energy_per_serving_branch() -> None:
    """A per-serving energy that converts to an over-cap per-100g value maps to None.

    Example: 750 kcal per 50g serving → 1500 kcal/100g, which exceeds the 900 cap.
    """
    # 750 kcal / 50g × 100 = 1500 kcal/100g → rejected
    client, _ = _client(_per_serving_response(energy=750.0, serving_g=50.0, fat=50.0))

    assert client.lookup(_BARCODE) is None


def test_lookup_accepts_zero_energy_per_serving_branch() -> None:
    """A zero per-serving energy converts to a valid zero per-100g, a costable match."""
    client, _ = _client(_per_serving_response(energy=0.0, serving_g=50.0))

    facts = client.lookup(_BARCODE)

    assert facts is not None
    assert facts.facts.calories == pytest.approx(0.0)


def test_lookup_rejects_negative_macro_per_serving_branch() -> None:
    """A negative per-serving macro converts to negative per-100g and maps to None."""
    # −5g protein per 50g serving → −10g/100g → rejected
    client, _ = _client(_per_serving_response(energy=200.0, serving_g=50.0, protein=-5.0))

    assert client.lookup(_BARCODE) is None


def test_lookup_no_false_reject_high_fat_food_per_100g() -> None:
    """Olive oil (~884 kcal/100g, ~100g fat, 0 protein, 0 carbs) still resolves."""
    client, _ = _client(_per_100g_response(energy=884.0, protein=0.0, carbs=0.0, fat=100.0))

    facts = client.lookup(_BARCODE)

    assert facts is not None
    assert facts.facts.calories == pytest.approx(884.0)
    assert facts.facts.fat_g == pytest.approx(100.0)
    assert facts.facts.protein_g == pytest.approx(0.0)
    assert facts.facts.carbs_g == pytest.approx(0.0)


def test_lookup_no_false_reject_high_fat_food_per_serving_branch() -> None:
    """A high-fat serving that converts just under the cap per-100g resolves correctly.

    442 kcal per 50g serving → 884 kcal/100g (< 900 cap) → accepted.
    """
    # 442 kcal / 50g serving × 100 = 884 kcal/100g → accepted
    client, _ = _client(_per_serving_response(energy=442.0, serving_g=50.0, fat=50.0))

    facts = client.lookup(_BARCODE)

    assert facts is not None
    assert facts.facts.calories == pytest.approx(884.0)
    assert facts.facts.fat_g == pytest.approx(100.0)
