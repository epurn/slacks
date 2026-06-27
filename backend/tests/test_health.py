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

    # Official-source search (FTY-079) advertises availability gated on an API key
    # (disabled-by-default posture; proven deterministically in the adapter tests).
    # The descriptor carries no secret.
    official = sources["official_source"]
    assert official["source_type"] == "official_source"
    assert official["kinds"] == ["named_product", "restaurant_item"]
    assert isinstance(official["available"], bool)
    assert "api_key" not in official
    assert "key" not in official


def test_healthz_egress_reports_official_fetch_policy(client: TestClient) -> None:
    response = client.get("/healthz/egress")

    assert response.status_code == 200
    policy = response.json()

    # Fail-closed default: no allowlist configured in the test environment.
    assert policy["allowed_hosts"] == []
    # The fixed hardened-fetch invariants are surfaced for the operator.
    assert policy["https_only"] is True
    assert policy["public_ip_only"] is True
    assert policy["redirects_followed"] is False
    assert policy["active_content_stripped"] is True
    # Bounded, inert-only limits.
    assert policy["max_bytes"] > 0
    assert policy["timeout_seconds"] > 0
    assert policy["allowed_content_types"] == [
        "application/xhtml+xml",
        "text/html",
        "text/plain",
    ]
    # No secret ever appears in the egress diagnostics.
    assert "api_key" not in policy
    assert "key" not in policy
