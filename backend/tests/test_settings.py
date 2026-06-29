"""Settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings, load_settings


def test_defaults() -> None:
    settings = Settings()

    assert settings.app_name == "fatty-backend"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.database_url == "postgresql://fatty:fatty@localhost:5432/fatty"
    assert settings.redis_url == "redis://localhost:6379/0"


def test_load_from_env_overrides_defaults() -> None:
    settings = load_settings(
        {
            "FATTY_ENVIRONMENT": "production",
            "FATTY_LOG_LEVEL": "ERROR",
            "FATTY_PORT": "9001",
            "FATTY_REDIS_URL": "redis://redis:6379/0",
            "FATTY_DATABASE_URL": "postgresql://fatty:fatty@postgres:5432/fatty",
            "FATTY_AUTH_SECRET": "a-real-production-secret",
        }
    )

    assert settings.environment == "production"
    assert settings.log_level == "ERROR"
    assert settings.port == 9001
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.database_url == "postgresql://fatty:fatty@postgres:5432/fatty"


def test_auth_secret_defaults_for_local_dev() -> None:
    settings = Settings()

    # SecretStr keeps the value out of repr/logs but is readable via the accessor.
    assert "dev-insecure" in settings.auth_secret.get_secret_value()
    assert "dev-insecure" not in repr(settings)
    assert settings.auth_token_ttl_seconds == 7 * 24 * 3600


def test_production_rejects_default_auth_secret() -> None:
    # Fail closed: a production app must not run on the shared dev secret.
    with pytest.raises(ValidationError):
        load_settings({"FATTY_ENVIRONMENT": "production"})


def test_production_accepts_explicit_auth_secret() -> None:
    settings = load_settings(
        {"FATTY_ENVIRONMENT": "production", "FATTY_AUTH_SECRET": "override-me"}
    )

    assert settings.auth_secret.get_secret_value() == "override-me"


def test_invalid_environment_fails_clearly() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # type: ignore[arg-type]


def test_invalid_log_level_from_env_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings({"FATTY_LOG_LEVEL": "verbose"})


def test_out_of_range_port_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings({"FATTY_PORT": "70000"})


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(unexpected="value")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# rate_limit_fail_open computed property (FTY-138)
# ---------------------------------------------------------------------------


def test_rate_limit_fail_open_default_development() -> None:
    settings = Settings(environment="development")
    assert settings.rate_limit_fail_open is True


def test_rate_limit_fail_open_default_test() -> None:
    settings = Settings(environment="test")
    assert settings.rate_limit_fail_open is True


def test_rate_limit_fail_open_default_production() -> None:
    settings = load_settings(
        {"FATTY_ENVIRONMENT": "production", "FATTY_AUTH_SECRET": "real-secret"}
    )
    assert settings.rate_limit_fail_open is False


def test_rate_limit_fail_open_override_forces_open_in_production() -> None:
    settings = load_settings(
        {
            "FATTY_ENVIRONMENT": "production",
            "FATTY_AUTH_SECRET": "real-secret",
            "FATTY_RATE_LIMIT_FAIL_OPEN_OVERRIDE": "true",
        }
    )
    assert settings.rate_limit_fail_open is True


def test_rate_limit_fail_open_override_forces_closed_in_development() -> None:
    settings = load_settings({"FATTY_RATE_LIMIT_FAIL_OPEN_OVERRIDE": "false"})
    assert settings.rate_limit_fail_open is False
