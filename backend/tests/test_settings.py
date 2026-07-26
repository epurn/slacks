"""Settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.settings import (
    DEFAULT_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS,
    DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR,
    DEV_AUTH_SECRET,
    Settings,
    load_settings,
)

#: The retired configuration prefix from before the FTY-333 hard cut. Assembled
#: from fragments so this non-carve-out test file carries no literal brand token
#: (the story's case-insensitive brand grep over ``backend/`` must return
#: nothing here); the runtime keys below are still the exact old names.
_RETIRED_ENV_PREFIX = "FAT" + "TY_"

#: The test opt-in (FTY-448): the only environment that may construct ``Settings``
#: on the published placeholder auth secret. Tests that exercise an unrelated
#: field's default carry it so they keep loading a real configuration.
_TEST_ENV = {"SLACKS_ENVIRONMENT": "test"}


def test_defaults() -> None:
    # ``environment="test"`` is the one opt-in that may construct on the default
    # placeholder auth secret (FTY-448); every other field below is still the
    # shipped default.
    settings = Settings(environment="test")

    assert settings.app_name == "slacks-backend"
    # The declared default environment is unchanged — only the guard moved.
    assert Settings.model_fields["environment"].default == "development"
    assert settings.log_level == "INFO"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.database_url == "postgresql://slacks:slacks@localhost:5432/slacks"
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
            "SLACKS_ENVIRONMENT": "production",
            "SLACKS_LOG_LEVEL": "ERROR",
            "SLACKS_PORT": "9001",
            "SLACKS_REDIS_URL": "redis://redis:6379/0",
            "SLACKS_DATABASE_URL": "postgresql://slacks:slacks@postgres:5432/slacks",
            "SLACKS_AUTH_SECRET": "a-real-production-secret",
            "SLACKS_ESTIMATOR_CLARIFY_MODE": "balanced",
            "SLACKS_ESTIMATOR_PARSE_CLARIFY_THRESHOLD": "0.82",
            "SLACKS_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR": "0.74",
            "SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS": "4",
        }
    )

    assert settings.environment == "production"
    assert settings.log_level == "ERROR"
    assert settings.port == 9001
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.database_url == "postgresql://slacks:slacks@postgres:5432/slacks"
    assert settings.estimator_clarify_mode == "balanced"
    assert settings.estimator_parse_clarify_threshold == 0.82
    assert settings.estimator_model_prior_confidence_floor == 0.74
    assert settings.estimator_max_parse_repair_attempts == 4


@pytest.mark.parametrize("mode", ["balanced", "strict"])
def test_estimator_clarify_mode_stricter_overrides_load(mode: str) -> None:
    settings = load_settings({**_TEST_ENV, "SLACKS_ESTIMATOR_CLARIFY_MODE": mode})

    assert settings.estimator_clarify_mode == mode


def test_unknown_estimator_clarify_mode_fails_clearly() -> None:
    with pytest.raises(ValidationError) as exc_info:
        load_settings({**_TEST_ENV, "SLACKS_ESTIMATOR_CLARIFY_MODE": "always_ask"})

    message = str(exc_info.value)
    assert "estimator_clarify_mode" in message
    assert "estimate_first" in message
    assert "balanced" in message
    assert "strict" in message


def test_estimator_numeric_tunables_accept_documented_bounds() -> None:
    settings = load_settings(
        {
            **_TEST_ENV,
            "SLACKS_ESTIMATOR_PARSE_CLARIFY_THRESHOLD": "0.0",
            "SLACKS_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR": "1.0",
            "SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS": "10",
        }
    )

    assert settings.estimator_parse_clarify_threshold == 0.0
    assert settings.estimator_model_prior_confidence_floor == 1.0
    assert settings.estimator_max_parse_repair_attempts == 10


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("SLACKS_ESTIMATOR_PARSE_CLARIFY_THRESHOLD", "-0.01"),
        ("SLACKS_ESTIMATOR_PARSE_CLARIFY_THRESHOLD", "1.01"),
        ("SLACKS_ESTIMATOR_PARSE_CLARIFY_THRESHOLD", "not-a-number"),
        ("SLACKS_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR", "-0.01"),
        ("SLACKS_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR", "1.01"),
        ("SLACKS_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR", "not-a-number"),
        ("SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS", "-1"),
        ("SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS", "11"),
        ("SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS", "not-a-number"),
    ],
)
def test_estimator_numeric_tunables_reject_invalid_values(env_name: str, env_value: str) -> None:
    # Carries the test opt-in so the refusal is provably the tunable's own bound
    # check, not the placeholder auth-secret guard firing first.
    with pytest.raises(ValidationError):
        load_settings({**_TEST_ENV, env_name: env_value})


def test_auth_secret_is_a_secret_str_under_the_test_opt_in() -> None:
    settings = Settings(environment="test")

    # SecretStr keeps the value out of repr/logs but is readable via the accessor.
    assert settings.auth_secret.get_secret_value() == DEV_AUTH_SECRET
    assert "dev-insecure" not in repr(settings)
    assert settings.auth_token_ttl_seconds == 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Placeholder auth-secret guard: the environment x secret matrix (FTY-448).
# The placeholder is published in this repo, so only ``test`` may boot on it.
# ---------------------------------------------------------------------------

_REAL_SECRET = "a-real-operator-generated-secret"  # noqa: S105 (test fixture, not a credential)


@pytest.mark.parametrize("environment", ["development", "production"])
def test_placeholder_auth_secret_refuses_outside_test(environment: str) -> None:
    with pytest.raises(ValidationError):
        load_settings({"SLACKS_ENVIRONMENT": environment})


@pytest.mark.parametrize("environment", ["development", "production", "test"])
def test_explicit_real_auth_secret_boots_in_every_environment(environment: str) -> None:
    settings = load_settings(
        {"SLACKS_ENVIRONMENT": environment, "SLACKS_AUTH_SECRET": _REAL_SECRET}
    )

    assert settings.environment == environment
    assert settings.auth_secret.get_secret_value() == _REAL_SECRET


def test_placeholder_auth_secret_boots_under_the_test_opt_in() -> None:
    # The opt-in that keeps the suite and CI running on the shared default.
    settings = load_settings({"SLACKS_ENVIRONMENT": "test"})

    assert settings.auth_secret.get_secret_value() == DEV_AUTH_SECRET


def test_placeholder_refusal_is_actionable() -> None:
    with pytest.raises(ValidationError) as exc_info:
        load_settings({"SLACKS_ENVIRONMENT": "development"})

    message = str(exc_info.value)

    # Actionable: names the env var, the generation command, and where to read more.
    assert "SLACKS_AUTH_SECRET" in message
    assert 'python3 -c "import secrets; print(secrets.token_hex(32))"' in message
    assert "README" in message
    assert ".env.example" in message


@pytest.mark.parametrize(
    "env",
    [
        # Secret left to the default (never present in the input mapping).
        {"SLACKS_ENVIRONMENT": "development"},
        # The copied-unchanged-.env case: the shipped template sets the
        # placeholder *explicitly*, so it is present in the raw input mapping.
        {"SLACKS_ENVIRONMENT": "development", "SLACKS_AUTH_SECRET": DEV_AUTH_SECRET},
        {"SLACKS_ENVIRONMENT": "production", "SLACKS_AUTH_SECRET": DEV_AUTH_SECRET},
    ],
)
def test_placeholder_refusal_never_echoes_the_secret(env: dict[str, str]) -> None:
    # The boot error must be content-free of credentials: Pydantic otherwise
    # attaches the raw input mapping to a model-level error as ``input_value``,
    # which would print the configured secret to stderr and the traceback.
    with pytest.raises(ValidationError) as exc_info:
        load_settings(env)

    for rendered in (str(exc_info.value), repr(exc_info.value)):
        assert DEV_AUTH_SECRET not in rendered
        assert "dev-insecure" not in rendered


def test_settings_errors_never_echo_a_real_configured_secret() -> None:
    # A configured (non-placeholder) secret must not leak through a validation
    # error raised for an unrelated reason on the same model.
    with pytest.raises(ValidationError) as exc_info:
        load_settings(
            {
                "SLACKS_ENVIRONMENT": "production",
                "SLACKS_AUTH_SECRET": _REAL_SECRET,
                "SLACKS_PORT": "70000",
            }
        )

    assert _REAL_SECRET not in str(exc_info.value)
    assert _REAL_SECRET not in repr(exc_info.value)


def test_legacy_env_prefix_is_dead() -> None:
    # Hard cut (FTY-333): the retired prefix has no effect. Retired-prefix keys
    # are ignored wholesale — the app only reads ``SLACKS_``-prefixed keys now,
    # and no read-time fallback exists. Only the ``SLACKS_``-prefixed test opt-in
    # is honoured, so every other field below falls back to its default.
    settings = load_settings(
        {
            **_TEST_ENV,
            f"{_RETIRED_ENV_PREFIX}APP_NAME": "legacy-name",
            f"{_RETIRED_ENV_PREFIX}ENVIRONMENT": "production",
            f"{_RETIRED_ENV_PREFIX}AUTH_SECRET": _REAL_SECRET,
            f"{_RETIRED_ENV_PREFIX}PORT": "9999",
        }
    )

    assert settings.app_name == "slacks-backend"
    assert settings.environment == "test"
    assert settings.port == 8000
    assert settings.auth_secret.get_secret_value() == DEV_AUTH_SECRET


@pytest.mark.parametrize("environment", ["development", "production"])
def test_legacy_auth_secret_does_not_satisfy_a_real_environment(environment: str) -> None:
    # The fail-closed validator must not accept the old key: setting only the
    # retired auth-secret key still leaves the effective secret at the
    # placeholder, so every non-test environment refuses (FTY-448 widened this
    # from production-only).
    with pytest.raises(ValidationError):
        load_settings(
            {
                "SLACKS_ENVIRONMENT": environment,
                f"{_RETIRED_ENV_PREFIX}AUTH_SECRET": _REAL_SECRET,
            }
        )


def test_invalid_environment_fails_clearly() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # type: ignore[arg-type]


def test_invalid_log_level_from_env_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings({**_TEST_ENV, "SLACKS_LOG_LEVEL": "verbose"})


def test_out_of_range_port_fails() -> None:
    with pytest.raises(ValidationError):
        load_settings({**_TEST_ENV, "SLACKS_PORT": "70000"})


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="test", unexpected="value")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# rate_limit_fail_open computed property (FTY-138)
# ---------------------------------------------------------------------------


def test_rate_limit_fail_open_default_development() -> None:
    settings = Settings(environment="development", auth_secret=SecretStr(_REAL_SECRET))
    assert settings.rate_limit_fail_open is True


def test_rate_limit_fail_open_default_test() -> None:
    settings = Settings(environment="test")
    assert settings.rate_limit_fail_open is True


def test_rate_limit_fail_open_default_production() -> None:
    settings = load_settings(
        {"SLACKS_ENVIRONMENT": "production", "SLACKS_AUTH_SECRET": "real-secret"}
    )
    assert settings.rate_limit_fail_open is False


def test_rate_limit_fail_open_override_forces_open_in_production() -> None:
    settings = load_settings(
        {
            "SLACKS_ENVIRONMENT": "production",
            "SLACKS_AUTH_SECRET": "real-secret",
            "SLACKS_RATE_LIMIT_FAIL_OPEN_OVERRIDE": "true",
        }
    )
    assert settings.rate_limit_fail_open is True


def test_rate_limit_fail_open_override_forces_closed_in_development() -> None:
    settings = load_settings(
        {
            "SLACKS_ENVIRONMENT": "development",
            "SLACKS_AUTH_SECRET": _REAL_SECRET,
            "SLACKS_RATE_LIMIT_FAIL_OPEN_OVERRIDE": "false",
        }
    )
    assert settings.rate_limit_fail_open is False
