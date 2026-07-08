"""Optional manual OpenRouter structured-output smoke.

This test is deliberately inert in normal CI: it skips unless an operator supplies
``FATTY_OPENROUTER_SMOKE_API_KEY``. The prompt and schema are synthetic so no
diary text or personal data is ever sent during the smoke.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from app.llm.providers.openai import OpenAIProvider

_OPENROUTER_API_KEY_ENV = "FATTY_OPENROUTER_SMOKE_API_KEY"
_OPENROUTER_MODEL_ENV = "FATTY_OPENROUTER_SMOKE_MODEL"
_DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-pro"


class _SmokeResult(BaseModel):
    """Tiny schema for the live OpenRouter structured-output smoke."""

    label: str
    count: int


def test_optional_openrouter_structured_output_smoke() -> None:
    api_key = os.environ.get(_OPENROUTER_API_KEY_ENV)
    if not api_key:
        pytest.skip(f"set {_OPENROUTER_API_KEY_ENV} to run the manual OpenRouter smoke")

    provider = OpenAIProvider(
        api_key=api_key,
        model=os.environ.get(_OPENROUTER_MODEL_ENV, _DEFAULT_OPENROUTER_MODEL),
        base_url="https://openrouter.ai/api/v1",
        timeout_seconds=30.0,
        max_retries=1,
    )

    result = provider.structured_completion(
        "Return JSON matching the schema with label exactly ok and count exactly 2.",
        _SmokeResult,
    )

    assert result == _SmokeResult(label="ok", count=2)
