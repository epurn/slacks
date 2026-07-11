"""Typed LLM provider configuration.

A self-hoster points the estimator at a provider entirely through
``SLACKS_LLM_``-prefixed environment variables (a Pi-inspired, config-driven
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

#: LLM settings are read from variables with this prefix, e.g. ``SLACKS_LLM_PROVIDER``.
ENV_PREFIX = "SLACKS_LLM_"

#: Supported provider selectors. ``openai_compatible`` covers any endpoint that
#: speaks the OpenAI Chat Completions wire format (vLLM, LM Studio, Together, ...).
#: ``claude_code`` wraps a locally installed, first-party Claude Code session
#: (subscription auth, no Slacks-side key). ``codex`` wraps a locally installed,
#: first-party Codex CLI session. ``fake`` is the in-memory test/dev provider
#: and never makes network calls.
ProviderName = Literal["openai", "anthropic", "openai_compatible", "claude_code", "codex", "fake"]

#: Default OpenAI API base. ``openai_compatible`` has no default — the operator
#: must supply ``SLACKS_LLM_BASE_URL`` for their endpoint.
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

#: Default Anthropic API base.
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"


class LLMSettings(BaseModel):
    """Validated LLM provider configuration.

    Frozen and ``extra="forbid"`` so configuration is immutable once loaded and
    unknown ``SLACKS_LLM_`` keys are rejected rather than silently ignored. The
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
    #: Required for ``openai``/``anthropic``/``openai_compatible``. **Optional for
    #: ``claude_code`` and ``codex``**: the local CLI session/config selects the
    #: model, so an empty value lets it use its default; a supplied value is
    #: passed through to the invocation (``--model``).
    model: str = Field(default="", description="Provider model identifier.")
    #: Per-attempt wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    #: Number of *additional* attempts after the first on transient failures.
    #: ``0`` disables retries. A documented tunable.
    max_retries: int = Field(default=2, ge=0, le=10)
    #: Declares the configured model as vision-capable. Image input
    #: (``structured_completion(..., images=...)``) is rejected fast unless this
    #: is set, so an image is never sent to a model that cannot read it. The
    #: operator opts in per the model they configured.
    supports_vision: bool = Field(default=False)

    @model_validator(mode="after")
    def _check_provider_requirements(self) -> LLMSettings:
        """Enforce the per-provider requirements the wire calls depend on."""

        if self.provider == "fake":
            return self
        if self.provider == "claude_code":
            # Claude Code owns its own authentication (``claude login``) and picks
            # the model from the active session/plan, so a Slacks-side key is
            # meaningless and the model is optional. A supplied model is honored
            # (passed through to the invocation); a supplied key is simply unused.
            return self
        if self.provider == "codex":
            # Codex owns its saved auth under CODEX_HOME unless an optional
            # Slacks-side key is supplied for this child process only. Its model is
            # also optional: an empty value lets the local Codex install choose
            # its configured/default model. SLACKS_LLM_BASE_URL is intentionally
            # ignored by the factory for this provider.
            return self
        if self.provider == "openai_compatible":
            # A keyless local endpoint (Ollama, LM Studio, vLLM) requires no API key
            # — authentication is either absent or handled out-of-band by the runtime.
            # The base URL and model are still required: without them the adapter has
            # nowhere to connect and nothing to ask for, so missing either is a
            # fail-closed misconfiguration.
            if not self.base_url:
                raise ValueError("provider 'openai_compatible' requires SLACKS_LLM_BASE_URL")
            if not self.model:
                raise ValueError("provider 'openai_compatible' requires SLACKS_LLM_MODEL")
            return self
        # All other non-fake providers (openai, anthropic) require both a key and a model.
        if self.api_key is None or not self.api_key.get_secret_value():
            raise ValueError(f"provider {self.provider!r} requires SLACKS_LLM_API_KEY")
        if not self.model:
            raise ValueError(f"provider {self.provider!r} requires SLACKS_LLM_MODEL")
        return self

    def resolved_base_url(self) -> str:
        """Return the API base URL, applying per-provider defaults."""

        if self.base_url:
            return self.base_url
        if self.provider == "anthropic":
            return DEFAULT_ANTHROPIC_BASE_URL
        return DEFAULT_OPENAI_BASE_URL


def load_llm_settings(environ: Mapping[str, str] | None = None) -> LLMSettings:
    """Build :class:`LLMSettings` from ``SLACKS_LLM_``-prefixed variables.

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
