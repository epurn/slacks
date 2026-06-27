"""Health endpoint integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_sources_reports_provider_capabilities(client: TestClient) -> None:
    response = client.get("/healthz/sources")

    assert response.status_code == 200
    sources = {s["id"]: s for s in response.json()["sources"]}

    # Open Food Facts (barcode) needs no credentials: enabled + available by default.
    off = sources["open_food_facts"]
    assert off["source_type"] == "product_database"
    assert off["kinds"] == ["barcode"]
    assert off["enabled"] is True
    assert off["available"] is True

    # USDA FDC (generic foods) advertises availability gated on an API key.
    fdc = sources["usda_fdc"]
    assert fdc["source_type"] == "trusted_nutrition_database"
    assert fdc["kinds"] == ["generic_food"]
    assert isinstance(fdc["available"], bool)
