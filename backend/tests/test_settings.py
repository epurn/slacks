"""Settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import (
    DEFAULT_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS,
    DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR,
    Settings,
    load_settings,
)


def test_defaults() -> None:
    settings = Settings()

    assert settings.app_name == "fatty-backend"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.database_url == "postgresql://fatty:fatty@localhost:5432/fatty"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.estimator_clarify_mode == "estimate_first"
    assert settings.estimator_parse_clarify_threshold is None
    assert (
        settings.estimator_model_prior_confidence_floor
        == DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR
    )
    assert (
        settings.estimator_max_parse_repair_attempts == DEFAULT_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS
    )


def test_load_from_env_overrides_defaults() -> None:
    settings = load_settings(
        {
            "FATTY_ENVIRONMENT": "production",
            "FATTY_LOG_LEVEL": "ERROR",
            "FATTY_PORT": "9001",
            "FATTY_REDIS_URL": "redis://redis:6379/0",
            "FATTY_DATABASE_URL": "postgresql://fatty:fatty@postgres:5432/fatty",
            "FATTY_AUTH_SECRET": "a-real-production-secret",
            "FATTY_ESTIMATOR_CLARIFY_MODE": "balanced",
            "FATTY_ESTIMATOR_PARSE_CLARIFY_THRESHOLD": "0.82",
            "FATTY_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR": "0.74",
            "FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS": "4",
        }
    )

    assert settings.environment == "production"
    assert settings.log_level == "ERROR"
    assert settings.port == 9001
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.database_url == "postgresql://fatty:fatty@postgres:5432/fatty"
    assert settings.estimator_clarify_mode == "balanced"
    assert settings.estimator_parse_clarify_threshold == 0.82
    assert settings.estimator_model_prior_confidence_floor == 0.74
    assert settings.estimator_max_parse_repair_attempts == 4


@pytest.mark.parametrize("mode", ["balanced", "strict"])
def test_estimator_clarify_mode_stricter_overrides_load(mode: str) -> None:
    settings = load_settings({"FATTY_ESTIMATOR_CLARIFY_MODE": mode})

    assert settings.estimator_clarify_mode == mode


def test_unknown_estimator_clarify_mode_fails_clearly() -> None:
    with pytest.raises(ValidationError) as exc_info:
        load_settings({"FATTY_ESTIMATOR_CLARIFY_MODE": "always_ask"})

    message = str(exc_info.value)
    assert "estimator_clarify_mode" in message
    assert "estimate_first" in message
    assert "balanced" in message
    assert "strict" in message


def test_estimator_numeric_tunables_accept_documented_bounds() -> None:
    settings = load_settings(
        {
            "FATTY_ESTIMATOR_PARSE_CLARIFY_THRESHOLD": "0.0",
            "FATTY_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR": "1.0",
            "FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS": "10",
        }
    )

    assert settings.estimator_parse_clarify_threshold == 0.0
    assert settings.estimator_model_prior_confidence_floor == 1.0
    assert settings.estimator_max_parse_repair_attempts == 10


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("FATTY_ESTIMATOR_PARSE_CLARIFY_THRESHOLD", "-0.01"),
        ("FATTY_ESTIMATOR_PARSE_CLARIFY_THRESHOLD", "1.01"),
        ("FATTY_ESTIMATOR_PARSE_CLARIFY_THRESHOLD", "not-a-number"),
        ("FATTY_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR", "-0.01"),
        ("FATTY_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR", "1.01"),
        ("FATTY_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR", "not-a-number"),
        ("FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS", "-1"),
        ("FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS", "11"),
        ("FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS", "not-a-number"),
    ],
)
def test_estimator_numeric_tunables_reject_invalid_values(env_name: str, env_value: str) -> None:
    with pytest.raises(ValidationError):
        load_settings({env_name: env_value})


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
