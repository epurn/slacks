"""Anthropic adapter tests: tool-call request construction and parsing.

The transport is monkeypatched, so these never make a network call.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.llm import transport
from app.llm.errors import LLMResponseError, StructuredOutputValidationError
from app.llm.providers.anthropic import AnthropicProvider
from tests.llm.conftest import (
    SENSITIVE_IMAGE_BYTES,
    Candidate,
    anthropic_tool_response,
    sample_image,
)


def _provider(*, supports_vision: bool = False) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="sk-secret-key",
        model="claude-3-5-sonnet",
        base_url="https://api.anthropic.com",
        timeout_seconds=5.0,
        max_retries=0,
        supports_vision=supports_vision,
    )


def test_builds_tool_request_and_parses_input(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post_json(
        url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return anthropic_tool_response({"name": "apple", "calories": 95})

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    result = _provider().structured_completion("an apple", Candidate)

    assert result == Candidate(name="apple", calories=95)
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-secret-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    tools = captured["payload"]["tools"]
    assert tools[0]["input_schema"] == Candidate.model_json_schema()
    assert captured["payload"]["tool_choice"] == {
        "type": "tool",
        "name": "emit_structured_output",
    }


def test_image_is_sent_as_a_base64_image_block(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post_json(
        url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        captured["payload"] = payload
        return anthropic_tool_response({"name": "granola bar", "calories": 190})

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    result = _provider(supports_vision=True).structured_completion(
        "extract the facts", Candidate, images=[sample_image()]
    )

    assert result == Candidate(name="granola bar", calories=190)
    content = captured["payload"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "extract the facts"}
    encoded = base64.b64encode(SENSITIVE_IMAGE_BYTES).decode("ascii")
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded},
    }


def test_missing_tool_use_block_is_a_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post_json(url: str, **_: Any) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": "no tool here"}]}

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    with pytest.raises(LLMResponseError):
        _provider().structured_completion("an apple", Candidate)


def test_schema_invalid_tool_input_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post_json(url: str, **_: Any) -> dict[str, Any]:
        # Well-formed tool_use block, but the input violates the schema.
        return anthropic_tool_response({"name": "apple", "calories": "many"})

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    # Validation happens in the base class; the wrong-typed field is rejected.
    with pytest.raises(StructuredOutputValidationError):
        _provider().structured_completion("an apple", Candidate)
