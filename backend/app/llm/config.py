"""Typed LLM provider configuration.

A self-hoster points the estimator at a provider entirely through
``FATTY_LLM_``-prefixed environment variables (a Pi-inspired, config-driven
provider model). These variable names are a contract consumed by the self-host
docs (FTY-072) and must stay stable.

The API key is held as a :class:`pydantic.SecretStr` so it never appears in
``repr``/``str`` output, log records, or accidental serialization. Keys are read
from the environment only and are never exposed to clients.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

#: LLM settings are read from variables with this prefix, e.g. ``FATTY_LLM_PROVIDER``.
ENV_PREFIX = "FATTY_LLM_"

#: Supported provider selectors. ``openai_compatible`` covers any endpoint that
#: speaks the OpenAI Chat Completions wire format (vLLM, LM Studio, Together, ...).
#: ``fake`` is the in-memory test/dev provider and never makes network calls.
ProviderName = Literal["openai", "anthropic", "openai_compatible", "fake"]

#: Default OpenAI API base. ``openai_compatible`` has no default — the operator
#: must supply ``FATTY_LLM_BASE_URL`` for their endpoint.
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

#: Default Anthropic API base.
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"


class LLMSettings(BaseModel):
    """Validated LLM provider configuration.

    Frozen and ``extra="forbid"`` so configuration is immutable once loaded and
    unknown ``FATTY_LLM_`` keys are rejected rather than silently ignored. The
    cross-field rules (a real provider needs a key; ``openai_compatible`` needs a
    base URL) fail fast at load time instead of at the first provider call.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Defaults to ``fake`` so a fresh checkout and CI run with no live provider
    #: and no key. A real deployment must opt in to a network provider.
    provider: ProviderName = "fake"
    api_key: SecretStr | None = None
    base_url: str | None = None
    #: Provider model identifier (e.g. ``gpt-4o-mini``, ``claude-3-5-sonnet``).
    model: str = Field(default="", description="Provider model identifier.")
    #: Per-attempt wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    #: Number of *additional* attempts after the first on transient failures.
    #: ``0`` disables retries. A documented tunable.
    max_retries: int = Field(default=2, ge=0, le=10)

    @model_validator(mode="after")
    def _check_provider_requirements(self) -> LLMSettings:
        """Enforce the per-provider requirements the wire calls depend on."""

        if self.provider == "fake":
            return self
        if self.api_key is None or not self.api_key.get_secret_value():
            raise ValueError(f"provider {self.provider!r} requires FATTY_LLM_API_KEY")
        if not self.model:
            raise ValueError(f"provider {self.provider!r} requires FATTY_LLM_MODEL")
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("provider 'openai_compatible' requires FATTY_LLM_BASE_URL")
        return self

    def resolved_base_url(self) -> str:
        """Return the API base URL, applying per-provider defaults."""

        if self.base_url:
            return self.base_url
        if self.provider == "anthropic":
            return DEFAULT_ANTHROPIC_BASE_URL
        return DEFAULT_OPENAI_BASE_URL


def load_llm_settings(environ: Mapping[str, str] | None = None) -> LLMSettings:
    """Build :class:`LLMSettings` from ``FATTY_LLM_``-prefixed variables.

    Only known fields are read; missing values fall back to defaults and invalid
    or inconsistent values raise ``ValidationError``.
    """

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in LLMSettings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    return LLMSettings.model_validate(data)
