"""LLM settings validation and secret-hygiene tests."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.llm.config import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_OPENAI_BASE_URL,
    LLMSettings,
    load_llm_settings,
)


def test_defaults_to_fake_provider() -> None:
    settings = LLMSettings()

    assert settings.provider == "fake"
    assert settings.api_key is None
    assert settings.timeout_seconds == 30.0
    assert settings.max_retries == 2


def test_load_openai_from_env() -> None:
    settings = load_llm_settings(
        {
            "FATTY_LLM_PROVIDER": "openai",
            "FATTY_LLM_API_KEY": "sk-test",
            "FATTY_LLM_MODEL": "gpt-4o-mini",
            "FATTY_LLM_TIMEOUT_SECONDS": "12.5",
            "FATTY_LLM_MAX_RETRIES": "1",
        }
    )

    assert settings.provider == "openai"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "sk-test"
    assert settings.model == "gpt-4o-mini"
    assert settings.timeout_seconds == 12.5
    assert settings.max_retries == 1
    assert settings.resolved_base_url() == DEFAULT_OPENAI_BASE_URL


def test_anthropic_uses_default_base_url() -> None:
    settings = LLMSettings(provider="anthropic", api_key=SecretStr("k"), model="claude")

    assert settings.resolved_base_url() == DEFAULT_ANTHROPIC_BASE_URL


def test_openai_compatible_requires_base_url() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai_compatible", api_key=SecretStr("k"), model="m")


def test_openai_compatible_with_base_url_is_valid() -> None:
    settings = LLMSettings(
        provider="openai_compatible",
        api_key=SecretStr("k"),
        model="m",
        base_url="https://llm.internal/v1",
    )

    assert settings.resolved_base_url() == "https://llm.internal/v1"


def test_real_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai", model="gpt-4o-mini")


def test_real_provider_requires_model() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai", api_key=SecretStr("k"))


def test_empty_api_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai", api_key=SecretStr(""), model="m")


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(unexpected="value")  # type: ignore[call-arg]


def test_unknown_env_var_is_ignored() -> None:
    # The loader reads only known fields, so a stray FATTY_LLM_ var is dropped
    # rather than forbidden — it never reaches the model.
    settings = load_llm_settings({"FATTY_LLM_UNEXPECTED": "x"})

    assert settings.provider == "fake"


def test_out_of_range_timeout_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_llm_settings({"FATTY_LLM_TIMEOUT_SECONDS": "0"})


def test_api_key_is_not_exposed_in_repr_or_str() -> None:
    # Secret hygiene: the key must never leak through model repr/str/serialization.
    settings = LLMSettings(provider="openai", api_key=SecretStr("sk-super-secret"), model="m")

    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in str(settings)
    assert "sk-super-secret" not in settings.model_dump_json()
