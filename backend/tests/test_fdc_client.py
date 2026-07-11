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
    client, _transport = _client(_RICE_RESPONSE)

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


def test_lookup_malformed_payload_non_numeric_nutrient_raises_fdc_response_error() -> None:
    """A non-numeric nutrient value maps to FdcResponseError — never a raw ValidationError."""
    malformed: dict[str, Any] = {
        "foods": [
            {
                "fdcId": 1,
                "description": "Bad food",
                "foodNutrients": [{"nutrientId": 1008, "value": "not_a_number"}],
            }
        ]
    }
    client, _ = _client(malformed)

    with pytest.raises(FdcResponseError):
        client.lookup("rice")


def test_lookup_malformed_payload_missing_fdc_id_raises_fdc_response_error() -> None:
    """A missing required fdcId maps to FdcResponseError — never a raw ValidationError."""
    malformed: dict[str, Any] = {
        "foods": [
            {
                "description": "Bad food",
                "foodNutrients": [{"nutrientId": 1008, "value": 100.0}],
            }
        ]
    }
    client, _ = _client(malformed)

    with pytest.raises(FdcResponseError):
        client.lookup("rice")


def test_list_matches_malformed_payload_non_numeric_nutrient_raises_fdc_response_error() -> None:
    """list_matches also fails closed on a non-numeric nutrient (shared _search path)."""
    malformed: dict[str, Any] = {
        "foods": [
            {
                "fdcId": 1,
                "description": "Bad food",
                "foodNutrients": [{"nutrientId": 1008, "value": "not_a_number"}],
            }
        ]
    }
    client, _ = _client(malformed)

    with pytest.raises(FdcResponseError):
        client.list_matches("rice")


def test_list_matches_malformed_payload_missing_fdc_id_raises_fdc_response_error() -> None:
    """list_matches also fails closed on a missing fdcId (shared _search path)."""
    malformed: dict[str, Any] = {
        "foods": [
            {
                "description": "Bad food",
                "foodNutrients": [{"nutrientId": 1008, "value": 100.0}],
            }
        ]
    }
    client, _ = _client(malformed)

    with pytest.raises(FdcResponseError):
        client.list_matches("rice")


def test_lookup_long_description_truncates_not_rejects() -> None:
    """An over-long FDC description is truncated to 300 chars — the row still resolves."""
    # Name the queried food first so the FTY-254 compatibility gate keeps the row;
    # this test pins truncation behavior, not ranking.
    long_name = "Rice " + "A" * 500
    overlong_response: dict[str, Any] = {
        "foods": [
            {
                "fdcId": 1,
                "description": long_name,
                "foodNutrients": [{"nutrientId": 1008, "value": 100.0}],
            }
        ]
    }
    client, _ = _client(overlong_response)

    facts = client.lookup("rice")

    assert facts is not None
    assert len(facts.description) == 300
    assert facts.description == long_name[:300]


def test_list_matches_long_description_truncates_not_rejects() -> None:
    """list_matches also truncates over-long descriptions (shared _search path)."""
    long_name = "B" * 400
    overlong_response: dict[str, Any] = {
        "foods": [
            {
                "fdcId": 2,
                "description": long_name,
                "foodNutrients": [{"nutrientId": 1008, "value": 200.0}],
            }
        ]
    }
    client, _ = _client(overlong_response)

    matches = client.list_matches("protein")

    assert len(matches) == 1
    assert len(matches[0].description) == 300
    assert matches[0].description == long_name[:300]


def test_list_matches_maps_all_energy_bearing_foods_to_product_facts() -> None:
    """list_matches returns all energy-bearing foods and skips energy-less ones."""
    two_food_response: dict[str, Any] = {
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
            },
            {
                "fdcId": 9999,
                "description": "No energy food",
                "foodNutrients": [{"nutrientId": 1003, "value": 2.0}],
            },
        ]
    }
    client, _ = _client(two_food_response)

    matches = client.list_matches("Rice")

    assert len(matches) == 1
    assert matches[0].source_ref == "usda_fdc:168880"
    assert matches[0].query_key == "rice"
    assert matches[0].facts.calories == pytest.approx(130.0)
    assert matches[0].content_hash


def test_lookup_and_list_matches_produce_same_content_hash_for_same_food() -> None:
    """The shared _search path produces a consistent content_hash across both methods."""
    client_a, _ = _client(_RICE_RESPONSE)
    client_b, _ = _client(_RICE_RESPONSE)

    lookup_facts = client_a.lookup("white rice")
    list_facts = client_b.list_matches("white rice")

    assert lookup_facts is not None
    assert list_facts
    assert lookup_facts.content_hash == list_facts[0].content_hash


def test_settings_require_https_base_url() -> None:
    with pytest.raises(ValidationError):
        FdcSettings(api_key=SecretStr("k"), base_url="http://insecure.example.com/fdc/v1")


def test_settings_allowed_hosts_derived_from_base_url() -> None:
    settings = FdcSettings(api_key=SecretStr("k"))

    assert settings.allowed_hosts == frozenset({"api.nal.usda.gov"})
    assert settings.search_url == "https://api.nal.usda.gov/fdc/v1/foods/search"


def test_load_fdc_settings_reads_env_prefix() -> None:
    settings = load_fdc_settings({"SLACKS_FDC_API_KEY": "from-env", "SLACKS_FDC_MAX_RESULTS": "10"})

    assert settings.is_configured is True
    assert settings.max_results == 10
    # The key is a secret: it must not render in repr.
    assert "from-env" not in repr(settings)


# ---------------------------------------------------------------------------
# Plausibility gate tests (FTY-115)
# ---------------------------------------------------------------------------


def _food_response(
    fdcId: int,
    energy: float,
    protein: float = 0.0,
    carbs: float = 0.0,
    fat: float = 0.0,
    description: str = "Test Food",
) -> dict[str, Any]:
    """Build a minimal FDC /foods/search reply with the given per-100g nutrient values."""
    return {
        "foods": [
            {
                "fdcId": fdcId,
                "description": description,
                "foodNutrients": [
                    {"nutrientId": 1008, "value": energy},
                    {"nutrientId": 1003, "value": protein},
                    {"nutrientId": 1005, "value": carbs},
                    {"nutrientId": 1004, "value": fat},
                ],
            }
        ]
    }


def test_lookup_rejects_over_cap_energy_kj_as_kcal() -> None:
    """A kJ-mislabelled energy value (~1500/100g) maps to None — no ProductFacts."""
    client, _ = _client(_food_response(fdcId=1, energy=1500.0, protein=10.0, carbs=20.0, fat=50.0))

    assert client.lookup("butter") is None


def test_lookup_rejects_negative_energy() -> None:
    """A negative energy value maps to None — no ProductFacts."""
    client, _ = _client(_food_response(fdcId=2, energy=-10.0))

    assert client.lookup("bad food") is None


def test_lookup_accepts_zero_energy() -> None:
    """A genuine zero-calorie food (e.g. water) is a costable 0-kcal match, not a non-match."""
    client, _ = _client(_food_response(fdcId=3, energy=0.0, description="Water, bottled"))

    facts = client.lookup("water")

    assert facts is not None
    assert facts.facts.calories == pytest.approx(0.0)


def test_lookup_rejects_negative_protein() -> None:
    """A negative protein value maps to None — physically impossible macro."""
    client, _ = _client(_food_response(fdcId=4, energy=200.0, protein=-5.0, carbs=10.0, fat=5.0))

    assert client.lookup("bad food") is None


def test_lookup_rejects_negative_carbs() -> None:
    """A negative carbs value maps to None — physically impossible macro."""
    client, _ = _client(_food_response(fdcId=5, energy=200.0, protein=5.0, carbs=-3.0, fat=5.0))

    assert client.lookup("bad food") is None


def test_lookup_rejects_negative_fat() -> None:
    """A negative fat value maps to None — physically impossible macro."""
    client, _ = _client(_food_response(fdcId=6, energy=200.0, protein=5.0, carbs=10.0, fat=-2.0))

    assert client.lookup("bad food") is None


def test_lookup_no_false_reject_high_fat_food() -> None:
    """Olive oil (~884 kcal/100g, ~100g fat, 0 protein, 0 carbs) still resolves."""
    client, _ = _client(
        _food_response(
            fdcId=7,
            energy=884.0,
            protein=0.0,
            carbs=0.0,
            fat=100.0,
            description="Oil, olive, salad or cooking",
        )
    )

    facts = client.lookup("olive oil")

    assert facts is not None
    assert facts.facts.calories == pytest.approx(884.0)
    assert facts.facts.fat_g == pytest.approx(100.0)
    assert facts.facts.protein_g == pytest.approx(0.0)
    assert facts.facts.carbs_g == pytest.approx(0.0)


def test_lookup_accepts_exactly_900_kcal_per_100g() -> None:
    """A row at exactly the cap (900 kcal/100g) is accepted — the bound is inclusive."""
    # The plausibility rule rejects calories > 900, so the boundary value 900 passes.
    client, _ = _client(_food_response(fdcId=8, energy=900.0, protein=0.0, carbs=0.0, fat=100.0))

    facts = client.lookup("theoretical max food")

    assert facts is not None
    assert facts.facts.calories == pytest.approx(900.0)


def test_lookup_rejects_energy_just_above_cap() -> None:
    """A row at 900.1 kcal/100g (just above cap) maps to None."""
    client, _ = _client(_food_response(fdcId=9, energy=900.1, protein=0.0, carbs=0.0, fat=100.0))

    assert client.lookup("impossible food") is None


def test_list_matches_rejects_over_cap_energy() -> None:
    """list_matches also rejects implausible energy via the shared _food_to_facts path."""
    client, _ = _client(_food_response(fdcId=10, energy=1500.0, protein=10.0, carbs=20.0, fat=50.0))

    assert client.list_matches("butter") == []


def test_list_matches_accepts_zero_energy() -> None:
    """list_matches also accepts a genuine zero-calorie food via the shared _food_to_facts path."""
    client, _ = _client(_food_response(fdcId=11, energy=0.0))

    matches = client.list_matches("water")

    assert len(matches) == 1
    assert matches[0].facts.calories == pytest.approx(0.0)


def test_list_matches_rejects_negative_macro() -> None:
    """list_matches also rejects a negative macro via the shared _food_to_facts path."""
    client, _ = _client(_food_response(fdcId=12, energy=200.0, protein=-1.0))

    assert client.list_matches("bad food") == []


def test_list_matches_no_false_reject_high_fat_food() -> None:
    """list_matches also accepts olive oil (~884 kcal/100g) — no false reject."""
    client, _ = _client(_food_response(fdcId=13, energy=884.0, protein=0.0, carbs=0.0, fat=100.0))

    matches = client.list_matches("olive oil")

    assert len(matches) == 1
    assert matches[0].facts.calories == pytest.approx(884.0)
