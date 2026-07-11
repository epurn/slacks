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
            "SLACKS_LLM_PROVIDER": "openai",
            "SLACKS_LLM_API_KEY": "sk-test",
            "SLACKS_LLM_MODEL": "gpt-4o-mini",
            "SLACKS_LLM_TIMEOUT_SECONDS": "12.5",
            "SLACKS_LLM_MAX_RETRIES": "1",
        }
    )

    assert settings.provider == "openai"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "sk-test"
    assert settings.model == "gpt-4o-mini"
    assert settings.timeout_seconds == 12.5
    assert settings.max_retries == 1
    assert settings.resolved_base_url() == DEFAULT_OPENAI_BASE_URL


def test_supports_vision_defaults_off() -> None:
    settings = LLMSettings()

    assert settings.supports_vision is False


def test_supports_vision_loaded_from_env() -> None:
    settings = load_llm_settings(
        {
            "SLACKS_LLM_PROVIDER": "openai",
            "SLACKS_LLM_API_KEY": "sk-test",
            "SLACKS_LLM_MODEL": "gpt-4o",
            "SLACKS_LLM_SUPPORTS_VISION": "true",
        }
    )

    assert settings.supports_vision is True


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


def test_claude_code_loads_without_key_or_model() -> None:
    # Claude Code authenticates via its own local session, so no Slacks key and no
    # model are required; the settings must load cleanly.
    settings = load_llm_settings({"SLACKS_LLM_PROVIDER": "claude_code"})

    assert settings.provider == "claude_code"
    assert settings.api_key is None
    assert settings.model == ""


def test_claude_code_passes_model_through_when_supplied() -> None:
    settings = load_llm_settings(
        {"SLACKS_LLM_PROVIDER": "claude_code", "SLACKS_LLM_MODEL": "claude-sonnet-4-5"}
    )

    assert settings.provider == "claude_code"
    assert settings.model == "claude-sonnet-4-5"


def test_claude_code_ignores_a_supplied_key() -> None:
    # A key is not required and not used for claude_code, but supplying one must
    # not break loading.
    settings = LLMSettings(provider="claude_code", api_key=SecretStr("unused"))

    assert settings.provider == "claude_code"


def test_codex_loads_without_key_or_model() -> None:
    settings = load_llm_settings({"SLACKS_LLM_PROVIDER": "codex"})

    assert settings.provider == "codex"
    assert settings.api_key is None
    assert settings.model == ""


def test_codex_passes_model_through_when_supplied() -> None:
    settings = load_llm_settings(
        {"SLACKS_LLM_PROVIDER": "codex", "SLACKS_LLM_MODEL": "gpt-5-codex"}
    )

    assert settings.provider == "codex"
    assert settings.model == "gpt-5-codex"


def test_codex_accepts_optional_api_key_as_secret() -> None:
    settings = load_llm_settings(
        {
            "SLACKS_LLM_PROVIDER": "codex",
            "SLACKS_LLM_API_KEY": "codex-secret-key",
        }
    )

    assert settings.provider == "codex"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "codex-secret-key"
    assert "codex-secret-key" not in repr(settings)
    assert "codex-secret-key" not in settings.model_dump_json()


def test_codex_ignores_base_url_requirement() -> None:
    settings = load_llm_settings(
        {
            "SLACKS_LLM_PROVIDER": "codex",
            "SLACKS_LLM_BASE_URL": "https://llm.example.invalid/v1",
        }
    )

    assert settings.provider == "codex"
    assert settings.base_url == "https://llm.example.invalid/v1"


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
    # The loader reads only known fields, so a stray SLACKS_LLM_ var is dropped
    # rather than forbidden — it never reaches the model.
    settings = load_llm_settings({"SLACKS_LLM_UNEXPECTED": "x"})

    assert settings.provider == "fake"


def test_out_of_range_timeout_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_llm_settings({"SLACKS_LLM_TIMEOUT_SECONDS": "0"})


def test_api_key_is_not_exposed_in_repr_or_str() -> None:
    # Secret hygiene: the key must never leak through model repr/str/serialization.
    settings = LLMSettings(provider="openai", api_key=SecretStr("sk-super-secret"), model="m")

    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in str(settings)
    assert "sk-super-secret" not in settings.model_dump_json()


# ---------------------------------------------------------------------------
# FTY-089: Keyless openai_compatible path
# ---------------------------------------------------------------------------


def test_openai_compatible_loads_without_key() -> None:
    # A keyless local endpoint (Ollama/LM Studio/vLLM) must validate cleanly
    # when base_url and model are present but no api_key is supplied.
    settings = LLMSettings(
        provider="openai_compatible",
        model="llama3",
        base_url="http://localhost:11434/v1",
    )

    assert settings.provider == "openai_compatible"
    assert settings.api_key is None
    assert settings.model == "llama3"
    assert settings.resolved_base_url() == "http://localhost:11434/v1"


def test_openai_compatible_keyless_missing_base_url_fails() -> None:
    # base_url is still required even when no key is present — fail closed.
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai_compatible", model="llama3")


def test_openai_compatible_keyless_missing_model_fails() -> None:
    # model is still required even when no key is present — fail closed.
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai_compatible", base_url="http://localhost:11434/v1")


def test_openai_keyless_still_fails() -> None:
    # Keyless openai must still be rejected — only openai_compatible may run keyless.
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai", model="gpt-4o-mini")


def test_anthropic_keyless_still_fails() -> None:
    # Keyless anthropic must still be rejected — only openai_compatible may run keyless.
    with pytest.raises(ValidationError):
        LLMSettings(provider="anthropic", model="claude-3-5-haiku-20241022")
