"""Security-headers and prod-docs-gating tests (FTY-112).

Acceptance criteria:
- Every response carries X-Content-Type-Options, X-Frame-Options, and
  Referrer-Policy regardless of environment.
- With environment=production, /docs, /redoc, and /openapi.json all return 404.
- With environment=development (and test), those three routes return 200,
  preserving current behaviour.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.main import create_app
from app.settings import Settings, load_settings


@pytest.fixture
def dev_client(db_engine: Engine) -> TestClient:
    """TestClient built against a development-environment app."""

    settings = Settings(environment="development", log_level="WARNING")
    app = create_app(settings=settings, engine=db_engine)
    return TestClient(app)


@pytest.fixture
def prod_client(db_engine: Engine) -> TestClient:
    """TestClient built against a production-environment app.

    Production requires a non-default auth secret; we supply a synthetic one
    via load_settings so the model validator passes without a real credential.
    """

    settings = load_settings(
        {
            "FATTY_ENVIRONMENT": "production",
            "FATTY_AUTH_SECRET": "synthetic-prod-secret-for-testing-only",
            "FATTY_LOG_LEVEL": "WARNING",
        }
    )
    app = create_app(settings=settings, engine=db_engine)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Security header presence (all environments)
# ---------------------------------------------------------------------------


class TestSecurityHeadersOnHealthEndpoint:
    """Headers must appear on every response regardless of environment."""

    def test_x_content_type_options_present(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options_present(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_referrer_policy_present(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.headers["Referrer-Policy"] == "no-referrer"

    def test_headers_present_on_non_200_response(self, client: TestClient) -> None:
        """Headers apply to error responses too, not only 200s."""

        response = client.get("/nonexistent-route-that-returns-404")
        assert response.status_code == 404
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"


class TestSecurityHeadersInDevelopment:
    """Headers are present in development (uses dev_client fixture)."""

    def test_all_three_headers_present(self, dev_client: TestClient) -> None:
        response = dev_client.get("/healthz")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"


class TestSecurityHeadersInProduction:
    """Headers are present in production (uses prod_client fixture)."""

    def test_all_three_headers_present(self, prod_client: TestClient) -> None:
        response = prod_client.get("/healthz")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"


# ---------------------------------------------------------------------------
# Prod docs gating: /docs, /redoc, /openapi.json must be 404 in production
# ---------------------------------------------------------------------------


class TestProdDocsGating:
    """In production the schema/UI routes must be absent (return 404)."""

    def test_docs_returns_404_in_production(self, prod_client: TestClient) -> None:
        response = prod_client.get("/docs")
        assert response.status_code == 404

    def test_redoc_returns_404_in_production(self, prod_client: TestClient) -> None:
        response = prod_client.get("/redoc")
        assert response.status_code == 404

    def test_openapi_json_returns_404_in_production(self, prod_client: TestClient) -> None:
        response = prod_client.get("/openapi.json")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Dev docs availability: /docs, /redoc, /openapi.json must be 200 in dev/test
# ---------------------------------------------------------------------------


class TestDevDocsAvailability:
    """In development (and test) the schema/UI routes must remain available."""

    def test_docs_returns_200_in_development(self, dev_client: TestClient) -> None:
        response = dev_client.get("/docs")
        assert response.status_code == 200

    def test_redoc_returns_200_in_development(self, dev_client: TestClient) -> None:
        response = dev_client.get("/redoc")
        assert response.status_code == 200

    def test_openapi_json_returns_200_in_development(self, dev_client: TestClient) -> None:
        response = dev_client.get("/openapi.json")
        assert response.status_code == 200

    def test_docs_returns_200_in_test(self, client: TestClient) -> None:
        """The default ``client`` fixture uses environment=test."""

        response = client.get("/docs")
        assert response.status_code == 200

    def test_openapi_json_returns_200_in_test(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
