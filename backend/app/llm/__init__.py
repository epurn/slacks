"""Config-driven LLM provider layer.

Public surface for the estimator pipeline (FTY-042 consumes this). A self-hoster
configures a provider through ``SLACKS_LLM_`` environment variables;
:func:`build_provider` returns a :class:`Provider` exposing the single
``structured_completion(prompt, schema) -> validated object`` capability.

See ``docs/contracts/llm-provider.md`` for the contract.
"""

from __future__ import annotations

from app.llm.base import ImageInput, Provider
from app.llm.config import LLMSettings, ProviderName, load_llm_settings
from app.llm.errors import (
    LLMConfigurationError,
    LLMError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.llm.factory import build_provider

__all__ = [
    "ImageInput",
    "LLMConfigurationError",
    "LLMError",
    "LLMResponseError",
    "LLMSettings",
    "LLMTransientError",
    "Provider",
    "ProviderName",
    "StructuredOutputValidationError",
    "build_provider",
    "load_llm_settings",
]
